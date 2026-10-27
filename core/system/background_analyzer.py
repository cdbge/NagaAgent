#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台意图分析器 - 基于博弈论的对话分析机制
分析对话片段，提取潜在任务意图
"""

import asyncio
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from core.system.config import config, logger
from langchain_openai import ChatOpenAI

from core.system.config import get_prompt

# ---------------------------------------------------------------------------
# MCP 工具清单的依赖注入点
#
# 意图分析需要把可用工具注入提示词，但工具注册表在 `servers/mcpserver/`。
# 若在此直接 import，core 就反向依赖了 servers —— 那样服务端与核心层
# 互相纠缠，且 `core` 无法脱离 servers 单独使用。
#
# 改为：由 servers 层在启动时调用 `set_tool_provider()` 注入一个取值函数，
# core 只认识这个不透明的可调用对象。
# ---------------------------------------------------------------------------

_tool_provider: Optional[Callable[[], Dict[str, Any]]] = None


def set_tool_provider(provider: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """注入「返回 MCP 服务信息字典」的函数；由 servers 层启动时调用。

    传入 ``None`` 可清除注入（测试用）。provider 应返回
    ``{服务名: 服务信息字典}``，与本模块原先的 services_info 结构一致。
    """
    global _tool_provider
    _tool_provider = provider


def _collect_services_info() -> Dict[str, Any]:
    """取可用服务信息；未注入时返回空字典（分析照常进行，只是没有工具清单）。"""
    if _tool_provider is None:
        return {}
    try:
        return _tool_provider() or {}
    except Exception as e:  # 注入方出错不应让意图分析整体失败
        logger.warning("获取 MCP 服务信息失败，本次分析不含工具清单: %s", e)
        return {}


class ConversationAnalyzer:
    """
    对话分析器模块：分析语音对话轮次以推断潜在任务意图
    输入是跨服务器的文本转录片段；输出是零个或多个标准化的任务查询
    """
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.api.model,
            base_url=config.api.base_url,
            api_key=config.api.api_key,
            temperature=0
        )

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        lines = []
        for m in messages[-config.api.max_history_rounds:]:
            role = m.get('role', 'user')
            # 修复：使用content字段而不是text字段
            content = m.get('content', '')
            # 清理文本，移除可能导致格式化问题的字符
            content = content.replace('{', '{{').replace('}', '}}')
            lines.append(f"{role}: {content}")
        conversation = "\n".join(lines)
        
        # 获取可用的MCP工具信息，注入到意图识别中
        # 工具清单由 servers 层在启动时注入（见下方 set_tool_provider），
        # core 不反向 import servers。
        try:
            services_info = _collect_services_info()
            
            # 构建工具信息摘要
            tools_summary = []
            for name, info in services_info.items():
                if info:
                    display_name = info.get("displayName", name)
                    description = info.get("description", "")
                    capabilities = info.get("capabilities", {})
                    
                    # 提取工具名称 - 从invocationCommands中提取
                    tools = []
                    invocation_commands = capabilities.get('invocationCommands', [])
                    for cmd in invocation_commands:
                        tool_name = cmd.get('command', '')
                        if tool_name:
                            tools.append(tool_name)

                    if tools:
                        tools_summary.append(f"- {display_name}: {description} (工具: {', '.join(tools)})")
                    else:
                        tools_summary.append(f"- {display_name}: {description}")
            
            if tools_summary:
                available_tools = "\n".join(tools_summary)
                # 将工具信息注入到对话分析提示词中
                return get_prompt("conversation_analyzer_prompt",
                                conversation=conversation,
                                available_tools=available_tools)
        except Exception as e:
            logger.debug(f"获取MCP工具信息失败: {e}")
        
        return get_prompt("conversation_analyzer_prompt", conversation=conversation)

    def analyze(self, messages: List[Dict[str, str]]):
        logger.info(f"[ConversationAnalyzer] 开始分析对话，消息数量: {len(messages)}")
        prompt = self._build_prompt(messages)
        logger.info(f"[ConversationAnalyzer] 构建提示词完成，长度: {len(prompt)}")

        # 使用简化的非标准JSON解析
        result = self._analyze_with_non_standard_json(prompt)
        if result and result.get("tool_calls"):
            return result

        # 解析失败
        logger.info("[ConversationAnalyzer] 未发现可执行任务")
        return {"tasks": [], "reason": "未发现可执行任务", "raw": "", "tool_calls": []}

    def _analyze_with_non_standard_json(self, prompt: str) -> Optional[Dict]:
        """非标准JSON格式解析 - 直接调用LLM，避免嵌套线程池"""
        logger.info("[ConversationAnalyzer] 尝试非标准JSON格式解析")
        try:
            # 直接调用LLM，避免嵌套线程池
            resp = self.llm.invoke([
                {"role": "system", "content": "你是精确的任务意图提取器与MCP调用规划器。"},
                {"role": "user", "content": prompt},
            ])
            
            text = resp.content.strip()
            logger.info(f"[ConversationAnalyzer] LLM响应完成，响应长度: {len(text)}")
            logger.info(f"[ConversationAnalyzer] LLM原始响应内容: {text}")

            # 解析非标准JSON格式
            tool_calls = self._parse_non_standard_json(text)
            
            if tool_calls:
                logger.info(f"[ConversationAnalyzer] 非标准JSON解析成功，发现 {len(tool_calls)} 个工具调用")
                return {
                    "tasks": [],
                    "reason": f"非标准JSON解析成功，发现 {len(tool_calls)} 个工具调用",
                    "tool_calls": tool_calls
                }
            else:
                logger.info("[ConversationAnalyzer] 未发现工具调用")
                return None

        except Exception as e:
            logger.error(f"[ConversationAnalyzer] 非标准JSON解析失败: {e}")
            return None

    def _parse_non_standard_json(self, text: str) -> List[Dict[str, Any]]:
        """解析非标准JSON格式 - 处理中文括号和标准JSON"""
        from core.system.naga_parsing import parse_non_standard_json
        return parse_non_standard_json(text)


class BackgroundAnalyzer:
    """后台分析器 - 管理异步意图分析。

    「博弈论」是这套机制的历史叫法：它分析对话、发现潜在任务，
    再通过 MCP 把工具调用分发出去。为了让它可观测、可开关，
    这里额外维护一份**最近分析记录**（有界队列），供 UI 的
    「博弈图」页展示。
    """

    #: 最多保留多少条分析记录
    MAX_RECORDS = 200

    def __init__(self):
        self.analyzer = ConversationAnalyzer()
        self.running_analyses = {}
        # 开关：关闭后不再发起后台意图分析（UI 上的「博弈论」按钮控制它）
        self.enabled = True
        # 最近分析记录（线程安全：分析跑在线程池里）
        self._records: "deque" = deque(maxlen=self.MAX_RECORDS)
        self._records_lock = threading.Lock()
        self._record_seq = 0
        # 最近一次工具分发结果，随记录一起展示
        self._last_dispatched: List[Dict[str, Any]] = []

    # ------------------------------------------------------------ 记录与开关
    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        logger.info(f"[意图分析] 已{'启用' if self.enabled else '停用'}")
        return self.enabled

    def is_enabled(self) -> bool:
        return self.enabled

    def _add_record(
        self,
        *,
        session_id: str,
        status: str,
        reason: str = "",
        tasks: Optional[List] = None,
        tool_calls: Optional[List] = None,
        dispatched: Optional[List] = None,
        duration_ms: int = 0,
    ) -> None:
        """追加一条分析记录（只保留字段摘要，避免撑爆内存）。"""
        summary = []
        for tc in (tool_calls or [])[:8]:
            if isinstance(tc, dict):
                summary.append({
                    "tool_name": tc.get("tool_name", ""),
                    "service_name": tc.get("service_name", ""),
                    "agent_type": tc.get("agentType", tc.get("agent_type", "")),
                })
        try:
            with self._records_lock:
                self._record_seq += 1
                self._records.append({
                    "seq": self._record_seq,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "session_id": session_id,
                    "status": status,               # ok / empty / skipped / timeout / error
                    "reason": reason,
                    "task_count": len(tasks or []),
                    "tool_count": len(tool_calls or []),
                    "tool_calls": summary,
                    "dispatched": (dispatched or [])[:8],
                    "duration_ms": duration_ms,
                })
        except Exception as exc:
            logger.debug(f"[意图分析] 写记录失败: {exc}")

    def get_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        """返回最近的分析记录（最新在前）。"""
        with self._records_lock:
            items = list(self._records)
        items.reverse()
        return items[: max(1, int(limit))]

    def clear_records(self) -> int:
        with self._records_lock:
            n = len(self._records)
            self._records.clear()
        logger.info(f"[意图分析] 已清空 {n} 条记录")
        return n

    def stats(self) -> Dict[str, Any]:
        """概览：开关状态、记录总数、各状态计数。"""
        with self._records_lock:
            items = list(self._records)
        by_status: Dict[str, int] = {}
        for it in items:
            by_status[it["status"]] = by_status.get(it["status"], 0) + 1
        return {
            "enabled": self.enabled,
            "running": len(self.running_analyses),
            "total": len(items),
            "by_status": by_status,
            "last": items[-1] if items else None,
        }

    async def analyze_intent_async(self, messages: List[Dict[str, str]], session_id: str):
        """异步意图分析 - 基于博弈论的背景分析机制"""
        if not self.enabled:
            return {"has_tasks": False, "reason": "意图分析已停用", "tasks": [], "priority": "low"}

        # 检查是否已经有分析在进行中
        if session_id in self.running_analyses:
            logger.info(f"[博弈论] 会话 {session_id} 已有意图分析在进行中，跳过重复执行")
            self._add_record(session_id=session_id, status="skipped", reason="已有分析在进行中")
            return {"has_tasks": False, "reason": "已有分析在进行中", "tasks": [], "priority": "low"}

        # 创建独立的意图分析会话
        analysis_session_id = f"analysis_{session_id}_{int(time.time())}"
        logger.info(f"[博弈论] 创建独立分析会话: {analysis_session_id}")

        # 标记分析开始
        self.running_analyses[session_id] = analysis_session_id
        started = time.time()

        try:
            logger.info(f"[博弈论] 开始异步意图分析，消息数量: {len(messages)}")
            loop = asyncio.get_running_loop()
            # Offload sync LLM call to threadpool to avoid blocking event loop
            logger.info(f"[博弈论] 在线程池中执行LLM分析...")

            # 添加异步超时机制
            try:
                analysis = await asyncio.wait_for(
                    loop.run_in_executor(None, self.analyzer.analyze, messages),
                    timeout=60.0  # 60秒超时
                )
                logger.info(f"[博弈论] LLM分析完成，结果类型: {type(analysis)}")
            except asyncio.TimeoutError:
                logger.error("[博弈论] 意图分析超时（60秒）")
                self._add_record(session_id=session_id, status="timeout", reason="意图分析超时（60秒）",
                                 duration_ms=int((time.time() - started) * 1000))
                return {"has_tasks": False, "reason": "意图分析超时", "tasks": [], "priority": "low"}

        except Exception as e:
            logger.error(f"[博弈论] 意图分析失败: {e}")
            import traceback
            logger.error(f"[博弈论] 详细错误信息: {traceback.format_exc()}")
            self._add_record(session_id=session_id, status="error", reason=f"分析失败: {e}",
                             duration_ms=int((time.time() - started) * 1000))
            return {"has_tasks": False, "reason": f"分析失败: {e}", "tasks": [], "priority": "low"}

        try:
            tasks = analysis.get("tasks", []) if isinstance(analysis, dict) else []
            tool_calls = analysis.get("tool_calls", []) if isinstance(analysis, dict) else []

            if not tasks and not tool_calls:
                self._add_record(session_id=session_id, status="empty", reason="未发现可执行任务",
                                 duration_ms=int((time.time() - started) * 1000))
                return {"has_tasks": False, "reason": "未发现可执行任务", "tasks": [], "priority": "low"}

            logger.info(f"[博弈论] 分析会话 {analysis_session_id} 发现 {len(tasks)} 个任务和 {len(tool_calls)} 个工具调用")

            # 处理工具调用 - 根据agentType分发到不同服务器
            if tool_calls:
                # 通知UI工具调用开始
                await self._notify_ui_tool_calls(tool_calls, session_id)
                await self._dispatch_tool_calls(tool_calls, session_id, analysis_session_id)

            # 返回分析结果
            result = {
                "has_tasks": True,
                "reason": analysis.get("reason", "发现潜在任务"),
                "tasks": tasks,
                "tool_calls": tool_calls,
                "priority": "medium"  # 可以根据任务数量或类型调整优先级
            }

            # 记录任务详情
            for task in tasks:
                logger.info(f"发现任务: {task}")
            for tool_call in tool_calls:
                logger.info(f"发现工具调用: {tool_call}")

            self._add_record(
                session_id=session_id, status="ok",
                reason=result["reason"], tasks=tasks, tool_calls=tool_calls,
                dispatched=self._last_dispatched,
                duration_ms=int((time.time() - started) * 1000),
            )
            return result

        except Exception as e:
            logger.error(f"任务处理失败: {e}")
            self._add_record(session_id=session_id, status="error", reason=f"处理失败: {e}",
                             duration_ms=int((time.time() - started) * 1000))
            return {"has_tasks": False, "reason": f"处理失败: {e}", "tasks": [], "priority": "low"}
        finally:
            # 清除分析状态标记
            if session_id in self.running_analyses:
                del self.running_analyses[session_id]
                logger.info(f"[博弈论] 会话 {session_id} 分析状态已清除")

    async def _notify_ui_tool_calls(self, tool_calls: List[Dict[str, Any]], session_id: str):
        """批量通知UI工具调用开始 - 优化网络请求"""
        try:
            import httpx
            
            # 批量构建工具调用通知
            tool_names = [tool_call.get("tool_name", "未知工具") for tool_call in tool_calls]
            
            # 批量发送通知（减少HTTP请求次数）
            notification_payload = {
                "session_id": session_id,
                "tool_calls": [
                    {
                        "tool_name": tool_call.get("tool_name", "未知工具"),
                        "service_name": tool_call.get("service_name", "未知服务"),
                        "status": "starting"
                    }
                    for tool_call in tool_calls
                ],
                "message": f"🔧 正在执行 {len(tool_calls)} 个工具: {', '.join(tool_names)}"
            }
            
            from core.system.config import get_server_port
            url = f"http://localhost:{get_server_port('api_server')}/tool_notification"

            # 尽力而为的通知：API 服务器可能尚未监听完（启动竞态），
            # 或事件循环正忙导致 5s 超时。给一次快速重试，仍失败就放弃。
            last_exc = None
            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(url, json=notification_payload)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt == 0:
                        await asyncio.sleep(0.5)

            if last_exc is not None:
                raise last_exc

        except Exception as e:
            # 注意：httpx 的超时类异常与 asyncio.CancelledError 的 str() 都是空串，
            # 只打印 {e} 会得到 "批量通知UI工具调用失败: " 这种无信息日志。
            # 因此这里补上类型与 repr，级别降为 warning ——
            # 该通知是「尽力而为」的 UX 增强，失败不影响工具实际执行
            # （工具结果仍由 tool_result_callback 回传）。
            logger.warning(
                f"批量通知UI工具调用失败（不影响工具执行）: "
                f"{type(e).__name__}: {e!r}"
            )
    
    async def _dispatch_tool_calls(self, tool_calls: List[Dict[str, Any]], session_id: str, analysis_session_id: str = None):
        """根据agentType将工具调用分发到相应的服务器"""
        self._last_dispatched = []
        try:
            
            # 按agentType分组
            mcp_calls = []
            agent_calls = []
            
            for tool_call in tool_calls:
                agent_type = tool_call.get("agentType", "")
                if agent_type == "mcp":
                    mcp_calls.append(tool_call)
                elif agent_type == "agent":
                    agent_calls.append(tool_call)
            
            # 分发MCP任务到MCP服务器
            if mcp_calls:
                ok, detail = await self._send_to_mcp_server(mcp_calls, session_id, analysis_session_id)
                self._last_dispatched.append({
                    "target": "mcp_server", "count": len(mcp_calls),
                    "ok": ok, "detail": detail,
                })
            
            # 分发Agent任务到agentserver
            if agent_calls:
                ok, detail = await self._send_to_agent_server(agent_calls, session_id, analysis_session_id)
                self._last_dispatched.append({
                    "target": "agent_server", "count": len(agent_calls),
                    "ok": ok, "detail": detail,
                })
                
        except Exception as e:
            logger.error(f"工具调用分发失败: {e}")
            self._last_dispatched.append({"target": "unknown", "count": len(tool_calls),
                                          "ok": False, "detail": str(e)})
    
    async def _send_to_mcp_server(self, mcp_calls: List[Dict[str, Any]], session_id: str, analysis_session_id: str = None):
        """发送MCP任务到MCP服务器。返回 (是否成功, 说明)。"""
        try:
            import httpx
            import uuid
            
            from core.system.config import get_server_port
            # 构建MCP服务器请求
            mcp_payload = {
                "query": f"批量MCP工具调用 ({len(mcp_calls)} 个)",
                "tool_calls": mcp_calls,
                "session_id": session_id,
                "request_id": str(uuid.uuid4()),
                "callback_url": f"http://localhost:{get_server_port('api_server')}/tool_result_callback"
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"http://localhost:{get_server_port('mcp_server')}/schedule",
                    json=mcp_payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    task_id = result.get("task_id", "unknown")
                    logger.info(f"[博弈论] 分析会话 {analysis_session_id or 'unknown'} MCP任务调度成功: {task_id}")
                    return True, f"task_id={task_id}"
                else:
                    logger.error(f"[博弈论] MCP任务调度失败: {response.status_code} - {response.text}")
                    return False, f"HTTP {response.status_code}"
                    
        except Exception as e:
            logger.error(f"[博弈论] 发送MCP任务失败: {e}")
            return False, str(e)
    
    async def _send_to_agent_server(self, agent_calls: List[Dict[str, Any]], session_id: str, analysis_session_id: str = None):
        """发送Agent任务到agentserver - 应用与MCP服务器相同的会话管理逻辑"""
        try:
            import httpx
            import uuid
            
            from core.system.config import get_server_port
            # 构建agentserver请求 - 应用与MCP服务器相同的会话管理逻辑
            agent_payload = {
                "query": f"批量Agent任务执行 ({len(agent_calls)} 个)",
                "agent_calls": agent_calls,  # 传递完整的agent_calls信息
                "session_id": session_id,
                "analysis_session_id": analysis_session_id,  # 传递独立分析会话ID
                "request_id": str(uuid.uuid4()),  # 生成独立请求ID
                "callback_url": f"http://localhost:{get_server_port('api_server')}/agent_result_callback"  # 添加回调URL
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"http://localhost:{get_server_port('agent_server')}/schedule",  # 使用统一的schedule端点
                    json=agent_payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    task_id = result.get("task_id", "unknown")
                    logger.info(f"[博弈论] 分析会话 {analysis_session_id or 'unknown'} Agent任务调度成功: {task_id}")
                    return True, f"task_id={task_id}"
                else:
                    logger.error(f"[博弈论] Agent任务调度失败: {response.status_code} - {response.text}")
                    return False, f"HTTP {response.status_code}"
                    
        except Exception as e:
            logger.error(f"[博弈论] 发送Agent任务失败: {e}")
            return False, str(e)


# 全局分析器实例
_background_analyzer = None

def get_background_analyzer() -> BackgroundAnalyzer:
    """获取全局后台分析器实例"""
    global _background_analyzer
    if _background_analyzer is None:
        _background_analyzer = BackgroundAnalyzer()
    return _background_analyzer
