#!/usr/bin/env python3
"""工具回调：任务通知、工具结果回传、工具对话落盘。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.system.config import get_prompt
from core.system.event_bus import event_bus
from core.system.message_manager import message_manager

from ..api_server import (
    _extract_tool_result,
    _notify_ui_refresh,
    logger,
)
from ..llm_service import get_llm_service

router = APIRouter(tags=["工具"])


@router.post("/tool_notification")
async def tool_notification(payload: Dict[str, Any]):
    """接收工具调用状态通知，只显示工具调用状态，不显示结果"""
    try:
        session_id = payload.get("session_id")
        tool_calls = payload.get("tool_calls", [])
        message = payload.get("message", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        # 记录工具调用状态（不处理结果，结果由tool_result_callback处理）
        for tool_call in tool_calls:
            tool_name = tool_call.get("tool_name", "未知工具")
            service_name = tool_call.get("service_name", "未知服务")
            status = tool_call.get("status", "starting")
            logger.info(f"工具调用状态: {tool_name} ({service_name}) - {status}")

        # 这里可以添加WebSocket通知UI的逻辑，让UI显示工具调用状态
        # 目前先记录日志，UI可以通过其他方式获取工具调用状态

        return {
            "success": True,
            "message": "工具调用状态通知已接收",
            "tool_calls": tool_calls,
            "display_message": message
        }

    except Exception as e:
        logger.error(f"工具调用通知处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@router.post("/tool_result_callback")
async def tool_result_callback(payload: Dict[str, Any]):
    """接收MCP工具执行结果回调，让主AI基于原始对话和工具结果重新生成回复"""
    try:
        session_id = payload.get("session_id")
        task_id = payload.get("task_id")
        result = payload.get("result", {})
        success = payload.get("success", False)

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"[工具回调] 开始处理工具回调，会话: {session_id}, 任务ID: {task_id}")
        logger.info(f"[工具回调] 回调内容: {result}")

        # 获取工具执行结果。
        #
        # MCP 回调的结构是 {"success":..., "results":[{tool,result,...}], "message":...}，
        # 真实结果在 results[i]["result"] 里，**不在**顶层 result["result"]。
        # 旧代码只取顶层 `result.get('result', '执行成功')`，于是永远拿不到数据，
        # 退化成字面量 "执行成功"，模型只能回"没给我数据"。
        tool_result = _extract_tool_result(result, success)
        logger.info(f"[工具回调] 工具执行结果: {str(tool_result)[:500]}")

        # 获取原始对话的最后一条用户消息（触发工具调用的消息）
        session_messages = message_manager.get_messages(session_id)
        original_user_message = ""
        for msg in reversed(session_messages):
            if msg.get('role') == 'user':
                original_user_message = msg.get('content', '')
                break

        # 构建包含工具结果的用户消息
        enhanced_message = f"{original_user_message}\n\n[工具执行结果]: {tool_result}"
        logger.info(f"[工具回调] 构建增强消息: {enhanced_message[:200]}...")

        # 构建对话风格提示词和消息
        system_prompt = get_prompt("conversation_style_prompt", include_skills=True)
        messages = message_manager.build_conversation_messages(
            session_id=session_id,
            system_prompt=system_prompt,
            current_message=enhanced_message
        )

        logger.info(f"[工具回调] 开始生成工具后回复...")

        # 使用LLM服务基于原始对话和工具结果重新生成回复
        try:
            llm_service = get_llm_service()
            response_text = await llm_service.chat_with_context(messages, temperature=0.7)
            logger.info(f"[工具回调] 工具后回复生成成功，内容: {response_text[:200]}...")
        except Exception as e:
            logger.error(f"[工具回调] 调用LLM服务失败: {e}")
            response_text = f"处理工具结果时出错: {str(e)}"

        # 只保存AI回复到历史记录（用户消息已在正常对话流程中保存）
        message_manager.add_message(session_id, "assistant", response_text)
        logger.info(f"[工具回调] AI回复已保存到历史")

        # 保存对话日志到文件
        message_manager.save_conversation_log(original_user_message, response_text, dev_mode=False)
        logger.info(f"[工具回调] 对话日志已保存")

        # 通过UI通知接口将AI回复发送给UI
        logger.info(f"[工具回调] 开始发送AI回复到UI...")
        await _notify_ui_refresh(session_id, response_text)

        logger.info(f"[工具回调] 工具结果处理完成，回复已发送到UI")

        return {
            "success": True,
            "message": "工具结果已通过主AI处理并返回给UI",
            "response": response_text,
            "task_id": task_id,
            "session_id": session_id
        }

    except Exception as e:
        logger.error(f"[工具回调] 工具结果回调处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@router.post("/tool_result")
async def tool_result(payload: Dict[str, Any]):
    """接收工具执行结果并显示在UI上"""
    try:
        session_id = payload.get("session_id")
        result = payload.get("result", "")
        notification_type = payload.get("type", "")
        ai_response = payload.get("ai_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"工具执行结果: {result}")

        # 如果是工具完成后的AI回复，通过事件总线通知界面显示
        # （服务端不 import ui；界面在启动时订阅 "tool.ai_response"）
        if notification_type == "tool_completed_with_ai_response" and ai_response:
            n = event_bus.publish("tool.ai_response", text=ai_response)
            if n:
                logger.info(f"[UI] 已通知界面显示AI回复，长度: {len(ai_response)}")
            else:
                logger.warning("[UI] 当前无界面订阅者，AI回复未显示（长度: %d）",
                               len(ai_response))

        return {
            "success": True,
            "message": "工具结果已接收",
            "result": result,
            "session_id": session_id
        }

    except Exception as e:
        logger.error(f"处理工具结果失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@router.post("/save_tool_conversation")
async def save_tool_conversation(payload: Dict[str, Any]):
    """保存工具对话历史"""
    try:
        session_id = payload.get("session_id")
        user_message = payload.get("user_message", "")
        assistant_response = payload.get("assistant_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"[保存工具对话] 开始保存工具对话历史，会话: {session_id}")

        # 保存用户消息（工具执行结果）
        if user_message:
            message_manager.add_message(session_id, "user", user_message)

        # 保存AI回复
        if assistant_response:
            message_manager.add_message(session_id, "assistant", assistant_response)

        logger.info(f"[保存工具对话] 工具对话历史已保存，会话: {session_id}")

        return {
            "success": True,
            "message": "工具对话历史已保存",
            "session_id": session_id
        }

    except Exception as e:
        logger.error(f"[保存工具对话] 保存工具对话历史失败: {e}")
        raise HTTPException(500, f"保存失败: {str(e)}")
