#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP调度器 - 负责MCP任务的调度和执行
基于博弈论设计，提供任务去重、并发控制、失败重试等功能
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from core.system.config import logger

# 能力信息从注册中心获取，由上层管理


@dataclass
class MCPTask:
    """MCP任务数据结构"""
    id: str
    query: str
    tool_calls: List[Dict[str, Any]]
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    callback_url: Optional[str] = None
    status: str = "queued"
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

class MCPScheduler:
    """MCP调度器 - 负责任务调度和执行"""
    
    def __init__(self, mcp_manager=None):
        self.mcp_manager = mcp_manager
        self.active_tasks: Dict[str, MCPTask] = {}
        self.completed_tasks: Dict[str, MCPTask] = {}
        self.task_queue = asyncio.Queue()
        self.worker_tasks: List[asyncio.Task] = []
        self.max_concurrent = 10
        self.shutdown_event = asyncio.Event()
        
        # 启动工作线程
        self._start_workers()
    
    def _start_workers(self):
        """启动工作线程"""
        for i in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.worker_tasks.append(worker)
    
    async def _worker(self, worker_name: str):
        """工作线程"""
        while not self.shutdown_event.is_set():
            try:
                # 等待任务或关闭信号
                task = await asyncio.wait_for(
                    self.task_queue.get(), 
                    timeout=1.0
                )
                
                if task is None:  # 关闭信号
                    break
                
                await self._execute_task(task)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"工作线程 {worker_name} 执行任务失败: {e}")
        
        logger.info(f"MCP调度器工作线程 {worker_name} 关闭")
    
    async def _execute_task(self, task: MCPTask):
        """执行单个任务"""
        try:
            task.status = "running"
            task.started_at = datetime.utcnow().isoformat() + "Z"
            
            logger.info(f"开始执行MCP任务: {task.id} - {task.query[:50]}...")
            
            # 能力分析（已简化/可选）
            # 如需根据能力做路由，可在此从注册中心获取信息
                
            # 执行工具调用
            results = []
            for tool_call in task.tool_calls:
                try:
                    result = await self._execute_single_tool_call(tool_call)
                    results.append(result)
                except Exception as e:
                    logger.error(f"工具调用失败: {tool_call} - {e}")
                    results.append({
                        "tool": tool_call.get("tool_name", "unknown"),
                        "success": False,
                        "error": str(e)
                    })
            
            # 更新任务状态
            # success 必须由各工具调用的实际结果决定。原先无条件写 True、
            # 消息写死「成功执行 N 个」，导致全部工具失败也上报成功。
            ok_count = sum(
                1 for r in results
                if isinstance(r, dict) and r.get("success") is not False
            )
            fail_count = len(results) - ok_count

            task.status = "completed" if fail_count == 0 else "failed"
            task.completed_at = datetime.utcnow().isoformat() + "Z"
            if fail_count == 0:
                summary = f"成功执行 {ok_count} 个工具调用"
            elif ok_count == 0:
                summary = f"{fail_count} 个工具调用全部失败"
            else:
                summary = f"部分成功：{ok_count} 个成功 / {fail_count} 个失败"

            task.result = {
                "success": fail_count == 0,
                "results": results,
                "message": summary,
            }
            if fail_count:
                task.error = summary
                logger.warning(f"MCP任务 {task.id} {summary}")
            
            logger.info(f"MCP任务完成: {task.id}")
            # 回调通知（可选）
            await self._maybe_callback(task)
            
        except Exception as e:
            logger.error(f"MCP任务执行失败: {task.id} - {e}")
            task.status = "failed"
            task.completed_at = datetime.utcnow().isoformat() + "Z"
            task.error = str(e)
            task.result = {
                "success": False,
                "error": str(e),
                "message": f"任务执行失败: {str(e)}"
            }
            # 回调失败也尝试通知
            try:
                await self._maybe_callback(task)
            except Exception:
                pass
        
        finally:
            # 移动到已完成任务
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]
            self.completed_tasks[task.id] = task

    async def _maybe_callback(self, task: MCPTask) -> None:
        """如果提供了callback_url，则POST回传任务结果"""
        if not task.callback_url:
            return
        try:
            import aiohttp
            payload = {
                "task_id": task.id,
                "session_id": task.session_id,
                "success": task.result.get("success") if task.result else False,
                "result": task.result,
                "error": task.error,
                "completed_at": task.completed_at,
            }
            async with aiohttp.ClientSession() as session:
                # 直接调用外部回调URL（通常是apiserver的tool_result_callback）
                callback_url = task.callback_url
                if not callback_url.startswith('http'):
                    # 如果是相对路径，构建完整URL
                    from core.system.config import get_server_port
                    callback_url = f"http://localhost:{get_server_port('api_server')}/tool_result_callback"
                
                async with session.post(callback_url, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"工具结果回调成功: {task.id}")
                    else:
                        logger.error(f"工具结果回调失败: {response.status}")
        except Exception as e:
            logger.error(f"回调通知失败: {e}")
    
    async def _execute_single_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个工具调用（通过 mcp_manager 统一调用）。

        失败时必须返回 ``success: False``。

        原先无论「抛异常」「mcp_manager 未初始化」还是「缺 service_name/tool_name」，
        都会落到同一段「回退：最小占位实现」，返回
        ``{"success": True, "result": "已提交调用: xxx"}`` —— 这个假成功经
        mcp_server 原样 200 返回，被 api_server.py:88 判为成功，
        最终以「某某工具: 已提交调用: xxx」写进模型上下文，让模型以为工具真执行了。
        """
        service_name = tool_call.get("service_name", "")
        tool_name = tool_call.get("tool_name", "")
        base = {
            "tool": tool_name or "unknown",
            "service_name": service_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        # 参数/依赖不满足 —— 属于明确失败，不再伪造成功
        if not self.mcp_manager:
            reason = "MCP 管理器未初始化"
        elif not service_name or not tool_name:
            reason = f"工具调用缺少 service_name/tool_name（service={service_name!r}, tool={tool_name!r}）"
        else:
            reason = None

        if reason:
            logger.error(f"无法执行工具调用: {reason}")
            return {**base, "success": False, "error": reason, "result": None}

        # 保留所有非标准字段作为参数
        args = {
            key: value
            for key, value in tool_call.items()
            if key not in ["agentType", "service_name", "tool_name"]
        }

        try:
            logger.info(f"执行工具调用: {service_name}.{tool_name} with args: {args}")
            result = await self.mcp_manager.unified_call(service_name, tool_name, args)
        except Exception as e:
            logger.error(f"工具调用失败 {service_name}.{tool_name}: {type(e).__name__}: {e}")
            return {
                **base,
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "result": None,
            }

        # unified_call 失败时会返回结构化 dict（而不是抛异常），需要一并识别
        if isinstance(result, dict) and result.get("success") is False:
            return {
                **base,
                "success": False,
                "error": result.get("error") or result.get("message") or "工具返回失败",
                "result": result,
            }

        return {**base, "success": True, "result": result}
    
    async def schedule_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """调度任务"""
        try:
            # 创建任务对象
            task = MCPTask(
                id=task_info["id"],
                query=task_info["query"],
                tool_calls=task_info["tool_calls"],
                session_id=task_info.get("session_id"),
                request_id=task_info.get("request_id"),
                callback_url=task_info.get("callback_url"),
                created_at=task_info["created_at"]
            )
            
            # 添加到活跃任务
            self.active_tasks[task.id] = task
            
            # 加入队列
            await self.task_queue.put(task)
            
            return {
                "success": True,
                "message": "任务已加入调度队列",
                "task_id": task.id
            }
            
        except Exception as e:
            logger.error(f"任务调度失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"任务调度失败: {str(e)}"
            }
    
    async def check_duplicate(self, query: str, tool_calls: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """检查任务重复"""
        # 简单的重复检查逻辑
        for task_id, task in self.active_tasks.items():
            if (task.query == query and 
                len(task.tool_calls) == len(tool_calls) and
                all(tc.get("tool_name") == tc2.get("tool_name") 
                    for tc, tc2 in zip(task.tool_calls, tool_calls))):
                return True, task_id
        
        return False, None
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.status = "cancelled"
            task.completed_at = datetime.utcnow().isoformat() + "Z"
            
            # 移动到已完成任务
            del self.active_tasks[task_id]
            self.completed_tasks[task_id] = task
            
            return True
        
        return False
    
    async def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        return {
            "active_tasks": len(self.active_tasks),
            "completed_tasks": len(self.completed_tasks),
            "queue_size": self.task_queue.qsize(),
            "max_concurrent": self.max_concurrent,
            "workers": len(self.worker_tasks)
        }
    
    async def shutdown(self):
        """关闭调度器"""
        logger.info("MCP调度器关闭中...")
        
        # 设置关闭信号
        self.shutdown_event.set()
        
        # 等待工作线程完成
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        
        logger.info("MCP调度器已关闭")
