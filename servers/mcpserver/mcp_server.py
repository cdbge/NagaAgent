#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP服务器 - 独立的MCP工具调度服务
基于博弈论的MCPServer设计，提供MCP工具调用的统一调度和管理
"""

import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from .mcp_scheduler import MCPScheduler
from core.system.config import logger
from core.system.contracts import install_problem_handlers
from core.system.timeutil import now_iso_utc
# 能力发现逻辑已由注册中心承担，移除独立能力管理器
# 精简：移除流式工具调用与独立工具解析执行，统一走调度器与管理器

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI应用生命周期：替代 on_event startup/shutdown"""
    # startup
    logger.info("MCP服务器启动中...")
    
    
    # 初始化MCP管理器（用于工具调用执行）
    try:
        from servers.mcpserver.mcp_manager import get_mcp_manager
        Modules.mcp_manager = get_mcp_manager()
        logger.info("MCP管理器初始化完成")

        # 手动触发MCP服务注册，避免循环导入死锁
        from servers.mcpserver.mcp_registry import auto_register_mcp
        auto_register_mcp()
        logger.info("MCP服务自动注册完成")

        # 把工具清单注入 core 的意图分析器。
        # core 需要这份清单来构造提示词，但不能反向 import servers，
        # 因此由这里（servers 层）注入一个取值函数。
        try:
            from core.system.background_analyzer import set_tool_provider
            from servers.mcpserver.mcp_registry import (
                get_registered_services, get_service_info)
            set_tool_provider(
                lambda: {n: get_service_info(n) for n in get_registered_services()})
            logger.info("已向意图分析器注入 MCP 工具清单")
        except Exception as e:
            logger.warning(f"注入 MCP 工具清单失败（意图分析将不含工具信息）: {e}")

    except Exception as e:
        logger.warning(f"MCP管理器初始化失败: {e}")
        Modules.mcp_manager = None
    
    # 初始化调度器（注入mcp_manager）
    Modules.scheduler = MCPScheduler(Modules.mcp_manager)
    
    logger.info("MCP服务器启动完成")
    
    yield
    
    # shutdown
    logger.info("MCP服务器关闭中...")
    if Modules.scheduler:
        await Modules.scheduler.shutdown()
    logger.info("MCP服务器已关闭")


app = FastAPI(
    title="Naga MCP Server", 
    description="独立的MCP工具调度服务",
    version="1.0.0",
    lifespan=lifespan
)

# 统一错误契约，见 core/system/contracts.py
install_problem_handlers(app, type_base="https://nagaagent.local/problems")

class Modules:
    """全局模块管理"""
    scheduler: Optional[MCPScheduler] = None
    # 任务注册表
    task_registry: Dict[str, Dict[str, Any]] = {}
    # 幂等性缓存
    completed_requests: Dict[str, Dict[str, Any]] = {}
    # MCP管理器（用于工具调用执行）
    mcp_manager: Optional[Any] = None

def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串（带 Z 后缀）。

    统一走 core.system.timeutil.now_iso_utc()：原先本服务与其他服务
    各写一份，且一处用本地时间（无时区）、一处用 UTC，
    导致跨服务的 created_at/completed_at 无法直接比较。
    """
    return now_iso_utc()

# （已迁移至 lifespan 上下文）

@app.post("/schedule")
async def schedule_mcp_task(payload: Dict[str, Any]):
    """
    调度MCP任务 - 主要入口点
    基于博弈论的MCPServer设计，提供统一的MCP工具调用调度
    """
    try:
        # 提取请求参数
        query = payload.get("query", "")
        tool_calls = payload.get("tool_calls", [])
        session_id = payload.get("session_id")
        request_id = payload.get("request_id", str(uuid.uuid4()))
        callback_url = payload.get("callback_url")
        
        if not query and not tool_calls:
            raise HTTPException(400, "query或tool_calls不能同时为空")
        
        # 幂等性检查
        if request_id in Modules.completed_requests:
            logger.info(f"幂等请求命中: {request_id}")
            return Modules.completed_requests[request_id]
        
        # 任务去重检查
        if Modules.scheduler:
            is_duplicate, matched_id = await Modules.scheduler.check_duplicate(query, tool_calls)
            if is_duplicate:
                logger.info(f"任务重复，跳过: {query[:50]}... (匹配: {matched_id})")
                response = {
                    "success": True,
                    "task_id": matched_id,
                    "message": "任务重复，已跳过",
                    "idempotent": True,
                    "request_id": request_id
                }
                Modules.completed_requests[request_id] = response
                return response
        
        # 并发控制
        if Modules.scheduler and len(Modules.scheduler.active_tasks) >= 50:
            raise HTTPException(429, "MCP调度器繁忙，请稍后再试")
        
        # 创建任务
        task_id = str(uuid.uuid4())
        task_info = {
            "id": task_id,
            "query": query,
            "tool_calls": tool_calls,
            "session_id": session_id,
            "request_id": request_id,
            "callback_url": callback_url,
            "status": "queued",
            "created_at": _now_iso(),
            "result": None,
            "error": None
        }
        
        Modules.task_registry[task_id] = task_info
        
        # 调度执行
        if Modules.scheduler:
            result = await Modules.scheduler.schedule_task(task_info)
            task_info.update(result)
            
            # 缓存结果
            response = {
                "success": result.get("success", False),
                "task_id": task_id,
                "message": result.get("message", ""),
                "result": result.get("result"),
                "request_id": request_id
            }
            Modules.completed_requests[request_id] = response
            return response
        else:
            raise HTTPException(500, "MCP调度器未初始化")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP任务调度失败: {e}")
        raise HTTPException(500, f"内部服务器错误: {str(e)}")

@app.get("/status")
async def get_mcp_status():
    """获取MCP服务器状态"""
    try:
        status = {
            "server": "running",
            "timestamp": _now_iso(),
            "tasks": {
                "total": len(Modules.task_registry),
                "active": len([t for t in Modules.task_registry.values() if t.get("status") == "running"]),
                "completed": len([t for t in Modules.task_registry.values() if t.get("status") == "completed"]),
                "failed": len([t for t in Modules.task_registry.values() if t.get("status") == "failed"])
            }
        }
        
        if Modules.scheduler:
            scheduler_status = await Modules.scheduler.get_status()
            status["scheduler"] = scheduler_status
            
    # 能力统计可由注册中心提供（此处先省略）
        
        return status
        
    except Exception as e:
        logger.error(f"获取MCP状态失败: {e}")
        raise HTTPException(500, f"获取状态失败: {str(e)}")

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取特定任务状态"""
    if task_id not in Modules.task_registry:
        raise HTTPException(404, "任务不存在")
    
    return Modules.task_registry[task_id]

@app.get("/tasks")
async def list_tasks(status: Optional[str] = None, session_id: Optional[str] = None):
    """列出任务"""
    tasks = list(Modules.task_registry.values())
    
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    
    if session_id:
        tasks = [t for t in tasks if t.get("session_id") == session_id]
    
    return {"tasks": tasks, "count": len(tasks)}

@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    if task_id not in Modules.task_registry:
        raise HTTPException(404, "任务不存在")
    
    task = Modules.task_registry[task_id]
    if task.get("status") in ["completed", "failed"]:
        raise HTTPException(400, "任务已完成，无法取消")
    
    if Modules.scheduler:
        await Modules.scheduler.cancel_task(task_id)
    
    task["status"] = "cancelled"
    task["cancelled_at"] = _now_iso()
    
    return {"success": True, "message": "任务已取消"}

# 流式处理统一通过 /schedule 进入调度流程
# 工具结果回调由apiserver统一处理

if __name__ == "__main__":
    import uvicorn
    from core.system.config import get_current_port
    port = get_current_port("mcp_server")
    uvicorn.run(app, host="0.0.0.0", port=port)
