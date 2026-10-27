#!/usr/bin/env python3
"""会话管理、记忆统计、日志上下文。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

import traceback

from fastapi import APIRouter, HTTPException

from core.system.message_manager import message_manager


router = APIRouter(tags=["会话"])


@router.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""
    
    try:
        # 记忆系统现在由main.py直接管理
        try:
            from core.summer_memory.memory_manager import memory_manager
            if memory_manager and memory_manager.enabled:
                stats = memory_manager.get_memory_stats()
                return {
                    "status": "success",
                    "memory_stats": stats
                }
            else:
                return {
                    "status": "success",
                    "memory_stats": {"enabled": False, "message": "记忆系统未启用"}
                }
        except ImportError:
            return {
                "status": "success",
                "memory_stats": {"enabled": False, "message": "记忆系统模块未找到"}
            }
    except Exception as e:
        print(f"获取记忆统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}")


@router.get("/sessions")
async def get_sessions():
    """获取所有会话信息 - 委托给message_manager"""
    try:
        return message_manager.get_all_sessions_api()
    except Exception as e:
        print(f"获取会话信息错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """获取指定会话的详细信息 - 委托给message_manager"""
    try:
        return message_manager.get_session_detail_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"获取会话详情错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话 - 委托给message_manager"""
    try:
        return message_manager.delete_session_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"删除会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions")
async def clear_all_sessions():
    """清空所有会话 - 委托给message_manager"""
    try:
        return message_manager.clear_all_sessions_api()
    except Exception as e:
        print(f"清空会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/context/statistics")
async def get_log_context_statistics(days: int = 7):
    """获取日志上下文统计信息"""
    try:
        statistics = message_manager.get_context_statistics(days)
        return {
            "status": "success",
            "statistics": statistics
        }
    except Exception as e:
        print(f"获取日志上下文统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/logs/context/load")
async def load_log_context(days: int = 3, max_messages: int = None):
    """加载日志上下文"""
    try:
        messages = message_manager.load_recent_context(days=days, max_messages=max_messages)
        return {
            "status": "success",
            "messages": messages,
            "count": len(messages),
            "days": days
        }
    except Exception as e:
        print(f"加载日志上下文错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载上下文失败: {str(e)}")
