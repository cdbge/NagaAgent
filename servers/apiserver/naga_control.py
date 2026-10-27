#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Naga 自身控制：把「操作应用自己」也做成模型可调用的工具。

模型能通过原生 function calling 调用这里的动作，例如：

    用户：把语音关掉
    模型 → naga_control(action="toggle_voice", enabled=False)

    用户：换个开心一点的表情
    模型 → naga_control(action="set_emotion", emotion="happy")

设计约束
========

**不能直接 import ui**。服务端与界面分属不同线程，服务端 import `ui.controller.chat`
会把 Qt 单例构造到非 GUI 线程上（`QTimer` 会失效）。因此：

* 改配置 → 走 `core/system/config_manager.update_config()`（自带持久化与热重载）
* 影响界面 → `event_bus.publish("control.<动作>", ...)`，界面自行订阅并转交 GUI 线程

风险边界
========

`update_config` 等于把配置写权限交给模型。因此：

* 只允许改**白名单内**的配置路径（见 ``_WRITABLE_PREFIXES``）；
* `api_key` / 密码类字段一律拒绝；
* 每次修改都写日志，便于事后追溯。

需要更严格的限制时，把 `config.api.control_enabled` 关掉即可 —— 此时所有
`naga_control` 工具都不会出现在模型的工具表里。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIONS",
    "is_enabled",
    "execute",
    "get_action_schemas",
    "WRITABLE_PREFIXES",
]

# 允许模型修改的配置路径前缀。
# 刻意**不含** api.api_key / grag.neo4j_password / mqtt.password 等凭据字段。
WRITABLE_PREFIXES = (
    "api.model",
    "api.temperature",
    "api.max_tokens",
    "api.thinking_enabled",
    "api.reasoning_effort",
    "api.function_calling_enabled",
    "system.voice_enabled",
    "system.log_level",
    "ui.font_size",
    "ui.font_name",
    "ui.user_name",
    "live2d.enabled",
    "live2d.model_path",
    "live2d.auto_emotion",
    "live2d.lip_sync_enabled",
    "tts.default_voice",
    "tts.default_speed",
    "voice_realtime.voice_mode",
    "grag.enabled",
    "grag.graph_backend",
)

# 禁止写入的键名片段（双重保险：即使路径在白名单里也拦下）
_FORBIDDEN_KEYS = ("api_key", "password", "token", "secret")


def is_enabled() -> bool:
    """是否向模型暴露 naga_control 工具。"""
    try:
        from core.system.config import config

        return bool(getattr(config.api, "control_enabled", True))
    except Exception:
        return True


def _ok(**fields: Any) -> Dict[str, Any]:
    return {"success": True, **fields}


def _fail(error: str, code: str = "error") -> Dict[str, Any]:
    return {"success": False, "error": error, "error_code": code}


# ---------------------------------------------------------------------------
# 动作实现
# ---------------------------------------------------------------------------
def _action_get_config(params: Dict[str, Any]) -> Dict[str, Any]:
    from core.system.config_manager import get_config_snapshot

    section = (params.get("section") or "").strip()
    snapshot = get_config_snapshot() or {}
    if section:
        if section not in snapshot:
            return _fail(f"配置节 {section!r} 不存在", "unknown_section")
        return _ok(section=section, config=snapshot[section])
    # 不给 key 的话整份配置里含凭据 —— 只返回节名，避免泄漏
    return _ok(sections=sorted(snapshot.keys()),
               hint="传入 section 读取具体内容")


def _action_update_config(params: Dict[str, Any]) -> Dict[str, Any]:
    from core.system.config_manager import update_config

    updates = params.get("config")
    if not isinstance(updates, dict) or not updates:
        return _fail("config 必须是非空对象，例如 {\"api\": {\"temperature\": 0.5}}",
                     "invalid_params")

    # 展开成扁平路径做白名单校验
    flat: Dict[str, Any] = {}

    def _walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(f"{prefix}.{k}" if prefix else str(k), v)
        else:
            flat[prefix] = node

    _walk("", updates)

    rejected: List[str] = []
    for path in flat:
        low = path.lower()
        if any(bad in low for bad in _FORBIDDEN_KEYS):
            rejected.append(path)
        elif not any(path == w or path.startswith(w + ".") for w in WRITABLE_PREFIXES):
            rejected.append(path)

    if rejected:
        return _fail(
            f"这些配置项不允许由模型修改：{', '.join(sorted(rejected))}",
            "forbidden_keys")

    try:
        ok = update_config(updates)
    except Exception as exc:
        logger.error(f"[naga_control] 更新配置失败: {exc}")
        return _fail(f"更新失败: {type(exc).__name__}: {exc}", "update_failed")

    if not ok:
        return _fail("配置更新被拒绝（请检查取值是否合法）", "update_rejected")

    logger.info(f"[naga_control] 模型修改配置: {sorted(flat)}")
    return _ok(updated=sorted(flat))


def _action_get_status(params: Dict[str, Any]) -> Dict[str, Any]:
    from core.system.config import config

    info: Dict[str, Any] = {
        "ai_name": getattr(config.system, "ai_name", "Naga"),
        "model": config.api.model,
        "voice_enabled": bool(getattr(config.system, "voice_enabled", False)),
        "live2d_enabled": bool(getattr(config.live2d, "enabled", False)),
        "function_calling_enabled": bool(
            getattr(config.api, "function_calling_enabled", False)),
    }
    try:
        from core.system.health_check import get_health_checker
        checker = get_health_checker()
        info["services"] = {
            name: port for name, port in checker.ports.items()
        }
    except Exception:
        pass
    return _ok(status=info)


def _action_toggle_voice(params: Dict[str, Any]) -> Dict[str, Any]:
    """运行时开关语音（不改配置文件）。"""
    enabled = params.get("enabled")
    if not isinstance(enabled, bool):
        return _fail("enabled 必须是 true/false", "invalid_params")
    try:
        from core.system.event_bus import event_bus

        delivered = event_bus.publish("control.voice", enabled=enabled)
        return _ok(enabled=enabled, delivered=delivered)
    except Exception as exc:
        return _fail(f"发送控制事件失败: {exc}", "publish_failed")


def _action_toggle_live2d(params: Dict[str, Any]) -> Dict[str, Any]:
    """运行时开关 Live2D（不改配置文件）。"""
    enabled = params.get("enabled")
    if not isinstance(enabled, bool):
        return _fail("enabled 必须是 true/false", "invalid_params")
    try:
        from core.system.event_bus import event_bus

        delivered = event_bus.publish("control.live2d", enabled=enabled)
        return _ok(enabled=enabled, delivered=delivered)
    except Exception as exc:
        return _fail(f"发送控制事件失败: {exc}", "publish_failed")


# 模型可选的 Live2D 情绪。与 ui/live2d/emotion_binding.py 的 detect_emotion
# 产出的情绪名保持一致，避免两套词表。
EMOTIONS = ("normal", "happy", "enjoy", "sad", "surprise", "angry", "shy")


def _action_set_emotion(params: Dict[str, Any]) -> Dict[str, Any]:
    """让模型主动指定形象情绪（比自动识别多一次调用，但更贴合语义）。"""
    emotion = str(params.get("emotion") or "").strip().lower()
    if emotion not in EMOTIONS:
        return _fail(f"emotion 必须是 {', '.join(EMOTIONS)} 之一", "invalid_params")
    try:
        intensity = float(params.get("intensity", 1.0))
    except (TypeError, ValueError):
        intensity = 1.0
    intensity = max(0.0, min(1.0, intensity))

    try:
        from core.system.event_bus import event_bus

        delivered = event_bus.publish(
            "control.live2d_emotion", emotion=emotion, intensity=intensity)
        return _ok(emotion=emotion, intensity=intensity, delivered=delivered)
    except Exception as exc:
        return _fail(f"发送情绪事件失败: {exc}", "publish_failed")


def _action_set_model(params: Dict[str, Any]) -> Dict[str, Any]:
    from core.system.deepseek import (
        DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_MODEL_FLASH, DEEPSEEK_MODEL_PRO,
    )

    known = {DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_MODEL_FLASH, DEEPSEEK_MODEL_PRO}
    model = str(params.get("model") or "").strip()
    if not model:
        return _fail("model 不能为空", "invalid_params")
    if model not in known:
        return _fail(
            f"未知模型 {model!r}，可选：{', '.join(sorted(known))}",
            "unknown_model")
    return _action_update_config({"config": {"api": {"model": model}}})


def _action_list_sessions(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        limit = int(params.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        from core.system.message_manager import message_manager

        data = message_manager.get_all_sessions_api() or {}
        sessions = data.get("sessions") or {}
        items = [
            {"session_id": sid,
             "message_count": info.get("message_count"),
             "last_message": str(info.get("last_message", ""))[:60]}
            for sid, info in sessions.items()
        ]
        items.sort(key=lambda x: x.get("message_count") or 0, reverse=True)
        return _ok(total=len(items), sessions=items[:max(1, limit)])
    except Exception as exc:
        return _fail(f"读取会话失败: {exc}", "read_failed")


def _action_clear_session(params: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(params.get("session_id") or "").strip()
    if not session_id:
        return _fail("session_id 不能为空", "invalid_params")
    try:
        from core.system.message_manager import message_manager

        ok = message_manager.delete_session(session_id)
        if not ok:
            return _fail(f"清除会话 {session_id!r} 失败", "clear_failed")
        return _ok(session_id=session_id)
    except Exception as exc:
        return _fail(f"清除会话失败: {exc}", "clear_failed")


def _action_list_skills(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from core.system.skill_manager import get_skill_manager

        mgr = get_skill_manager()
        # 技能元数据在 _metadata_cache 里（_skills 是正文缓存，按需加载）
        skills = getattr(mgr, "_metadata_cache", None) or {}
        return _ok(
            total=len(skills),
            skills=[{"name": n, "description": getattr(s, "description", "")[:80]}
                    for n, s in skills.items()],
        )
    except Exception as exc:
        return _fail(f"读取技能失败: {exc}", "read_failed")


# ---------------------------------------------------------------------------
# 动作表
# ---------------------------------------------------------------------------
# 每个动作：处理函数 + 给模型看的参数 schema
ACTIONS: Dict[str, Dict[str, Any]] = {
    "get_config": {
        "handler": _action_get_config,
        "description": "读取 Naga 的配置。不给 section 时只返回可用的配置节名",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "配置节名，如 api / system / tts / live2d / grag",
                },
            },
            "required": [],
        },
    },
    "update_config": {
        "handler": _action_update_config,
        "description": "修改配置并持久化。只接受白名单内的路径，凭据类字段会被拒绝",
        "parameters": {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": "嵌套配置对象，如 {\"api\": {\"temperature\": 0.5}}",
                },
            },
            "required": ["config"],
        },
    },
    "get_status": {
        "handler": _action_get_status,
        "description": "获取当前运行状态：模型、语音/Live2D 开关、各服务端口",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "toggle_voice": {
        "handler": _action_toggle_voice,
        "description": "运行时暂停或恢复语音播报（不改配置文件）",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "true 开启 / false 暂停"},
            },
            "required": ["enabled"],
        },
    },
    "toggle_live2d": {
        "handler": _action_toggle_live2d,
        "description": "运行时显示或隐藏 Live2D 形象（不改配置文件）",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "true 显示 / false 隐藏"},
            },
            "required": ["enabled"],
        },
    },
    "set_emotion": {
        "handler": _action_set_emotion,
        "description": (
            "设置虚拟形象的表情。当你判断这句话带有明显情绪时调用 —— "
            "肯定/同意用 happy，愉快/赞叹用 enjoy，否定/拒绝用 sad，"
            "意外用 surprise，中性陈述可以省略不调"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": list(EMOTIONS),
                    "description": "情绪名",
                },
                "intensity": {
                    "type": "number",
                    "description": "强度 0.0–1.0，默认 1.0",
                },
            },
            "required": ["emotion"],
        },
    },
    "set_model": {
        "handler": _action_set_model,
        "description": "切换对话使用的 LLM 模型",
        "parameters": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "模型名，如 deepseek-flash"},
            },
            "required": ["model"],
        },
    },
    "list_sessions": {
        "handler": _action_list_sessions,
        "description": "列出最近的会话",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数，默认 10"},
            },
            "required": [],
        },
    },
    "clear_session": {
        "handler": _action_clear_session,
        "description": "清空指定会话的历史记录（不可恢复）",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
    },
    "list_skills": {
        "handler": _action_list_skills,
        "description": "列出已安装的技能",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


async def execute(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行一个控制动作，永不抛异常。"""
    spec = ACTIONS.get(str(action or "").strip())
    if not spec:
        return _fail(
            f"未知动作 {action!r}，可用动作：{', '.join(sorted(ACTIONS))}",
            "unknown_action")
    try:
        result = spec["handler"](params or {})
        if isinstance(result, dict):
            return result
        return _ok(result=result)
    except Exception as exc:
        logger.error(f"[naga_control] 动作 {action} 失败: {exc}", exc_info=True)
        return _fail(f"执行 {action} 时异常: {type(exc).__name__}: {exc}",
                     "action_failed")


def get_action_schemas() -> List[Dict[str, Any]]:
    """把动作表转成 OpenAI function calling 的 tools 定义。"""
    if not is_enabled():
        return []
    out: List[Dict[str, Any]] = []
    for name, spec in ACTIONS.items():
        out.append({
            "type": "function",
            "function": {
                "name": f"naga_control__{name}",
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        })
    return out


def format_result(result: Dict[str, Any]) -> str:
    """把执行结果转成给模型看的文本。"""
    return json.dumps(result, ensure_ascii=False, default=str)
