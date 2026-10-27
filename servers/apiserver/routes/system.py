#!/usr/bin/env python3
"""系统与诊断端点：根路径、健康检查、系统信息。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

import asyncio
from typing import Dict

from fastapi import APIRouter

from core.system.config import config

from ..api_server import logger, SystemInfoResponse

router = APIRouter(tags=["系统"])


@router.get("/", response_model=Dict[str, str])
async def root():
    """API根路径"""
    return {
        "name": "NagaAgent API",
        "version": "4.0.0",
        "status": "running",
        "docs": "/docs",
    }


@router.get("/health")
async def health_check():
    """轻量健康检查（只回答「进程活着吗」）。

    不要在这个端点里做探活/依赖检查 —— 它会被负载均衡或监控高频调用，
    变重之后会拖慢整体。需要详细诊断请用 ``/health/full``。
    """
    return {
        "status": "healthy",
        "agent_ready": True,
        "timestamp": str(asyncio.get_event_loop().time())
    }


@router.get("/health/full")
async def full_health_check():
    """完整连通性诊断：各服务端口/端点、关键依赖、存储可写性。

    与 ``/health`` 的区别：这里会真的去连其它服务的端口并请求其探活端点，
    单次耗时通常 2–3 秒。适合排查「启动了但某个功能不工作」这类问题，
    例如端口被 Windows 保留段占掉、dashscope 未安装等。

    任何单项异常都被 health_check 内部捕获，本端点不会因检查失败而报错。
    """
    try:
        from core.system.health_check import get_health_checker

        checker = get_health_checker()
        results = await checker.check_all()
        summary = checker.get_summary(results)
        return {
            "success": True,
            "summary": summary,
            "details": {
                name: {
                    "status": r.status.value,
                    "message": r.message,
                    "checks": r.checks,
                    "latency_ms": r.latency_ms,
                }
                for name, r in results.items()
            },
        }
    except Exception as exc:
        logger.error(f"[健康检查] 诊断失败: {exc}")
        return {
            "success": False,
            "error": f"健康检查执行失败: {type(exc).__name__}: {exc}",
            "error_code": "health_check_failed",
        }


@router.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    """获取系统信息"""
    
    return SystemInfoResponse(
        version="4.0.0",
        status="running",
        available_services=[],  # MCP服务现在由mcpserver独立管理
        api_key_configured=bool(config.api.api_key and config.api.api_key != "sk-placeholder-key-not-set")
    )


@router.get("/system/config")
async def get_system_config(section: str = ""):
    """读取配置。

    不带 ``section`` 时只返回配置节名 —— 整份配置里含 api_key / 数据库密码，
    不应该通过 HTTP 一次性吐出去。
    """
    try:
        from core.system.config_manager import get_config_snapshot

        snapshot = get_config_snapshot() or {}
        if not section:
            return {"success": True, "sections": sorted(snapshot.keys())}
        if section not in snapshot:
            return {"success": False, "error": f"配置节 {section!r} 不存在",
                    "error_code": "unknown_section"}
        return {"success": True, "section": section, "config": snapshot[section]}
    except Exception as exc:
        logger.error(f"[系统配置] 读取失败: {exc}")
        return {"success": False, "error": str(exc), "error_code": "read_failed"}


@router.post("/system/config")
async def update_system_config(payload: Dict):
    """修改配置并持久化。

    与模型侧走同一套白名单（`naga_control._action_update_config`），
    凭据类字段与白名单外的路径一律拒绝。
    """
    try:
        from ..naga_control import _action_update_config, is_enabled

        if not is_enabled():
            return {"success": False, "error": "配置修改已禁用（api.control_enabled=false）",
                    "error_code": "control_disabled"}
        result = _action_update_config({"config": payload.get("config")})
        return result
    except Exception as exc:
        logger.error(f"[系统配置] 更新失败: {exc}")
        return {"success": False, "error": str(exc), "error_code": "update_failed"}
