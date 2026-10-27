#!/usr/bin/env python3
"""对话端点：普通请求与 SSE 流式请求。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

import threading
import traceback
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.system.config import config, get_prompt
from core.system.message_manager import message_manager
from core.system.response_util import extract_message

from ..api_server import (
    ChatRequest,
    ChatResponse,
    _decode_sse_data,
    _save_conversation_and_logs,
    _schedule_memory_extraction,
    _trigger_background_analysis,
    logger,
)
from ..llm_service import get_llm_service

router = APIRouter(tags=["对话"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """普通对话接口 - 仅处理纯文本对话"""
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    try:
        # 博弈论（self_game）流程已随 game/ 模块一并移除：
        # 请求侧 use_self_game 恒为 false，且相关配置项（config.game）也已被删除。
        # 此处直接走普通对话分支。

        # 获取或创建会话ID
        session_id = message_manager.create_session(request.session_id)
        
        # 构建系统提示词（只使用对话风格提示词）
        system_prompt = get_prompt("conversation_style_prompt", include_skills=True)
        
        # 使用消息管理器构建完整的对话消息（纯聊天，不触发工具）
        messages = message_manager.build_conversation_messages(
            session_id=session_id,
            system_prompt=system_prompt,
            current_message=request.message
        )
        
        # 使用整合后的LLM服务
        llm_service = get_llm_service()
        response_text = await llm_service.chat_with_context(messages, config.api.temperature)
        
        # 处理完成
        # 统一保存对话历史与日志
        _save_conversation_and_logs(session_id, request.message, response_text)
        # 投递给 GRAG 记忆系统异步抽取五元组（不阻塞回复）
        _schedule_memory_extraction(request.message, response_text)

        # 在用户消息保存到历史后触发后台意图分析（除非明确跳过）
        if not request.skip_intent_analysis:
            _trigger_background_analysis(session_id=session_id)

        return ChatResponse(
            response=extract_message(response_text) if response_text else response_text,
            session_id=session_id,
            status="success"
        )
    except Exception as e:
        print(f"对话处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 - 流式文本处理交给streaming_tool_extractor用于TTS"""
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    async def generate_response() -> AsyncGenerator[str, None]:
        complete_text = ""  # V19: 用于累积完整文本以生成音频
        try:
            # 获取或创建会话ID
            session_id = message_manager.create_session(request.session_id)
            
            # 发送会话ID信息
            yield f"data: session_id: {session_id}\n\n"
            
            # 注意：这里不触发后台分析，将在对话保存后触发
            
            # 构建系统提示词（只使用对话风格提示词）
            system_prompt = get_prompt("conversation_style_prompt", include_skills=True)
            
            # 使用消息管理器构建完整的对话消息
            messages = message_manager.build_conversation_messages(
                session_id=session_id,
                system_prompt=system_prompt,
                current_message=request.message
            )

            # 初始化语音集成（根据voice_mode和return_audio决定）
            # V19: 如果客户端请求返回音频，则在服务器端生成
            voice_integration = None

            # V19: 混合模式下，如果请求return_audio，则在服务器生成音频
            # 修复双音频问题：return_audio时不启用实时TTS，只在最后生成完整音频
            should_enable_tts = (
                config.system.voice_enabled
                and not request.return_audio  # 修复：return_audio时不启用实时TTS
                and config.voice_realtime.voice_mode != "hybrid"
                and not request.disable_tts  # 兼容旧版本的disable_tts
            )

            if should_enable_tts:
                try:
                    from core.voice.output.voice_integration import get_voice_integration
                    voice_integration = get_voice_integration()
                    logger.info(f"[API Server] 实时语音集成已启用 (return_audio={request.return_audio}, voice_mode={config.voice_realtime.voice_mode})")
                except Exception as e:
                    print(f"语音集成初始化失败: {e}")
            else:
                if request.return_audio:
                    logger.info("[API Server] return_audio模式，将在最后生成完整音频")
                elif config.voice_realtime.voice_mode == "hybrid" and not request.return_audio:
                    logger.info("[API Server] 混合模式下且未请求音频，不处理TTS")
                elif request.disable_tts:
                    logger.info("[API Server] 客户端禁用了TTS (disable_tts=True)")

            # 初始化流式文本切割器（仅用于TTS处理）
            # 始终创建tool_extractor以累积文本内容，确保日志保存
            tool_extractor = None
            try:
                from .streaming_tool_extractor import StreamingToolCallExtractor
                tool_extractor = StreamingToolCallExtractor()
                # 只有在需要实时TTS且不是return_audio模式时，才设置voice_integration
                if voice_integration and not request.return_audio:
                    tool_extractor.set_callbacks(
                        on_text_chunk=None,  # 不需要回调，直接处理TTS
                        voice_integration=voice_integration
                    )
            except Exception as e:
                print(f"流式文本切割器初始化失败: {e}")
            
            # 使用整合后的流式处理
            llm_service = get_llm_service()

            # ------------------------------------------------------------------
            # 原生 function calling：让模型自己决定是否调工具
            #
            # 旧链路是「先跑一次意图分析判断要调什么 → 再调模型生成」，多一次往返。
            # 开启后由模型在生成过程中直接发起 tool_calls，省掉那次纯判断。
            #
            # 三条降级路径，保证任何情况下对话都不会断：
            #   1. 配置关闭 function_calling_enabled  -> 走原单轮流式
            #   2. 工具表为空（没有 MCP 服务）        -> 走原单轮流式
            #   3. 工具表构建异常                     -> 走原单轮流式
            # ------------------------------------------------------------------
            use_agentic = bool(getattr(config.api, "function_calling_enabled", True))
            tool_schemas = []
            if use_agentic:
                try:
                    from ..tool_schemas import build_tool_schemas
                    tool_schemas = build_tool_schemas()
                except Exception as exc:
                    logger.warning(f"[API Server] 工具表构建失败，退回普通流式: {exc}")
                    tool_schemas = []

            # 工具路由（默认关闭）：工具数量多时先缩小工具表，避免每轮都为
            # 用不到的工具付 token。工具少时 shortlist_tools 直接返回 None。
            if tool_schemas:
                try:
                    from ..intent_router import shortlist_tools
                    routed = await shortlist_tools(request.message or "", tool_schemas)
                    if routed is not None:
                        tool_schemas = routed
                        if not tool_schemas:
                            logger.info("[API Server] 路由判定本句无需工具，禁用工具调用")
                except Exception as exc:
                    logger.debug(f"[API Server] 工具路由跳过: {exc}")

            if use_agentic and tool_schemas:
                from ..agentic_tool_loop import run_agentic_loop
                logger.info(
                    f"[API Server] 启用原生 function calling（{len(tool_schemas)} 个工具）")
                chunk_source = run_agentic_loop(
                    messages, session_id=session_id, tools=tool_schemas
                )
            else:
                if use_agentic:
                    logger.info("[API Server] 无可用工具，使用普通流式对话")
                chunk_source = llm_service.stream_chat_with_context(
                    messages, config.api.temperature
                )

            async for chunk in chunk_source:
                # V19: 如果需要返回音频，累积文本
                if request.return_audio:
                    decoded = _decode_sse_data(chunk)
                    if decoded:
                        complete_text += decoded
                
                # 送入流式切割器：它负责「累积完整文本（用于日志）」+「按句切分后投递给 TTS」。
                #
                # ⚠️ 必须调用 process_text_chunk()，不能直接 `tool_extractor.complete_text += decoded`：
                # 后者只完成了累积这一步，跳过了切句与 _send_to_voice_integration()，
                # 导致 voice_integration 永远收不到文本 —— 表现为 AI 回复完全不朗读。
                if tool_extractor:
                    decoded = _decode_sse_data(chunk)
                    if decoded:
                        await tool_extractor.process_text_chunk(decoded)
                
                yield chunk
            
            # 处理完成

            # V19: 如果请求返回音频，在这里生成并返回音频URL
            if request.return_audio and complete_text:
                try:
                    logger.info(f"[API Server V19] 生成音频，文本长度: {len(complete_text)}")

                    # 使用服务器端的TTS生成音频
                    from core.voice.tts_wrapper import generate_speech_safe

                    # 生成音频文件
                    tts_voice = config.voice_realtime.tts_voice or "zh-CN-XiaoyiNeural"
                    audio_file = generate_speech_safe(
                        text=complete_text,
                        voice=tts_voice,
                        response_format="mp3",
                        speed=1.0
                    )

                    # 直接使用voice/output播放音频，不再返回给客户端
                    try:
                        from core.voice.output.voice_integration import get_voice_integration
                        voice_integration = get_voice_integration()
                        voice_integration.receive_audio_url(audio_file)
                        logger.info(f"[API Server V19] 音频已直接播放: {audio_file}")
                    except Exception as e:
                        logger.error(f"[API Server V19] 音频播放失败: {e}")
                        # 如果播放失败，仍然返回给客户端作为备选
                        yield f"data: audio_url: {audio_file}\n\n"

                except Exception as e:
                    logger.error(f"[API Server V19] 音频生成失败: {e}")
                    # traceback已经在文件顶部导入，直接使用
                    print(f"[API Server V19] 详细错误信息:")
                    traceback.print_exc()

            # 完成流式文本切割器处理（非return_audio模式，不阻塞）
            if tool_extractor and not request.return_audio:
                try:
                    # 冲刷切割器剩余缓冲：以标点结尾的句子在流式过程中已投递，
                    # 但最后一段往往**没有句末标点**（如「语音测试一二三」），
                    # 不冲刷它就会永远留在缓冲区里、不会被朗读。
                    if tool_extractor and voice_integration and not request.return_audio:
                        await tool_extractor._flush_text_buffer()
                except Exception as e:
                    print(f"流式文本切割器完成处理错误: {e}")
            
            # 完成语音处理
            if voice_integration and not request.return_audio:  # V19: return_audio模式不需要这里的处理
                try:
                    threading.Thread(
                        target=voice_integration.finish_processing,
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"语音集成完成处理错误: {e}")

            # 流式处理完成后，获取完整文本用于保存
            complete_response = ""
            if tool_extractor:
                try:
                    # 获取完整文本内容
                    complete_response = tool_extractor.get_complete_text()
                except Exception as e:
                    print(f"获取完整响应文本失败: {e}")
            elif request.return_audio:
                # V19: 如果是return_audio模式，使用累积的文本
                complete_response = complete_text
            
            # 统一保存对话历史与日志
            _save_conversation_and_logs(session_id, request.message, complete_response)
            # 投递给 GRAG 记忆系统异步抽取五元组（不阻塞流式回复）
            _schedule_memory_extraction(request.message, complete_response)

            # 在用户消息保存到历史后触发后台意图分析（除非明确跳过）
            if not request.skip_intent_analysis:
                _trigger_background_analysis(session_id)

            yield "data: [DONE]\n\n"
            
        except Exception as e:
            print(f"流式对话处理错误: {e}")
            # 使用顶部导入的traceback
            traceback.print_exc()
            yield f"data: 错误: {str(e)}\n\n"
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no"  # 禁用nginx缓冲
        }
    )
