#!/usr/bin/env python3
"""意图分析（界面上叫「博弈图」）的记录、开关与清空。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..api_server import logger

router = APIRouter(tags=["意图分析"])


@router.get("/intent_analysis/records")
async def intent_analysis_records(limit: int = 50):
    """最近的分析记录（最新在前）+ 概览统计。"""
    try:
        from core.system.background_analyzer import get_background_analyzer

        analyzer = get_background_analyzer()
        return {
            "success": True,
            "stats": analyzer.stats(),
            "records": analyzer.get_records(limit),
        }
    except Exception as e:
        logger.error(f"读取意图分析记录失败: {e}")
        raise HTTPException(500, f"读取失败: {str(e)}")


@router.post("/intent_analysis/toggle")
async def intent_analysis_toggle(payload: Optional[Dict[str, Any]] = None):
    """启用 / 停用后台意图分析。不传 enabled 则取反。"""
    try:
        from core.system.background_analyzer import get_background_analyzer

        analyzer = get_background_analyzer()
        payload = payload or {}
        if "enabled" in payload:
            state = analyzer.set_enabled(bool(payload["enabled"]))
        else:
            state = analyzer.set_enabled(not analyzer.is_enabled())
        return {"success": True, "enabled": state}
    except Exception as e:
        logger.error(f"切换意图分析开关失败: {e}")
        raise HTTPException(500, f"切换失败: {str(e)}")


@router.post("/intent_analysis/clear")
async def intent_analysis_clear():
    """清空分析记录（不影响开关状态）。"""
    try:
        from core.system.background_analyzer import get_background_analyzer

        n = get_background_analyzer().clear_records()
        return {"success": True, "cleared": n}
    except Exception as e:
        logger.error(f"清空意图分析记录失败: {e}")
        raise HTTPException(500, f"清空失败: {str(e)}")
