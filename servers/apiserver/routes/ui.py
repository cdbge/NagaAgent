#!/usr/bin/env python3
"""界面通知端点。

路由从 `api_server.py` 拆出（原先 962 行单文件里混着 21 个端点）。
依赖方向单向：本模块从 `..api_server` 取 logger / Pydantic 模型 /
共享辅助函数，`api_server` 在文件末尾再 include 本模块的 router ——
这样不存在真正的循环依赖（注册发生时 api_server 已完成定义）。
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.system.event_bus import event_bus

from ..api_server import logger

router = APIRouter(tags=["界面"])


@router.post("/ui_notification")
async def ui_notification(payload: Dict[str, Any]):
    """UI通知接口 - 用于直接控制UI显示"""
    try:
        session_id = payload.get("session_id")
        action = payload.get("action", "")
        ai_response = payload.get("ai_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"UI通知: {action}, 会话: {session_id}")

        # 处理显示工具AI回复的动作
        if action == "show_tool_ai_response" and ai_response:
            n = event_bus.publish("tool.ai_response", text=ai_response)
            if not n:
                # 服务端可脱离界面运行；此时如实告知，不假装成功
                raise HTTPException(503, "当前没有界面在监听，无法显示 AI 回复")
            logger.info(f"[UI通知] 已通知界面显示工具AI回复，长度: {len(ai_response)}")
            return {
                "success": True,
                "message": "AI回复已显示"
            }

        return {
            "success": True,
            "message": "UI通知已处理"
        }

    except Exception as e:
        logger.error(f"处理UI通知失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")
