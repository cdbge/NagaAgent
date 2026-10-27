#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MCP 服务清单转成 OpenAI function calling 所需的 ``tools`` 定义。

背景
====

原来的工具链路是「两次模型往返」：

    用户消息 → [LLM #1 意图分析] → 代码解析出要调哪个工具
             → 调用工具 → [LLM #2 结合结果回答]

而原生 function calling 让模型在一次调用里**同时完成「判断要不要调工具」和
「生成调用参数」**，省掉那次纯为分类而跑的往返。本模块负责把本地的 MCP
服务清单翻译成模型认识的 ``tools`` 结构。

本地清单的形状（与 OpenAI 不同）
--------------------------------

``servers/mcpserver/*/agent-manifest.json`` 里每条命令长这样::

    {
      "command": "下载漫画",
      "description": "下载指定ID的漫画到桌面；参数：album_id（漫画ID，必需）",
      "example": "{\"tool_name\": \"下载漫画\", \"album_id\": \"422866\"}"
    }

注意三点：

1. **没有结构化参数定义** —— 全部 manifest 都只有 ``command`` /
   ``description`` / ``example``。参数信息藏在散文里。
2. ``example`` 是**可以解析的 JSON**，且稳定包含 ``tool_name``（派发键）
   与真实参数。因此参数表从 example 反推，比解析散文可靠得多。
3. ``command`` 是中文。OpenAI 规定 function name 必须匹配
   ``^[a-zA-Z0-9_-]{1,64}$``，所以必须生成 ASCII 名并把中文原样放进
   ``description`` —— 模型是靠 description 选工具的，名字只要唯一即可。

命名约定
--------

``mcp__{service}__{序号}``：``mcp__agent_comic_downloader__1``。
``service`` 来自目录名（天然 ASCII），序号保证唯一。

为什么不用中文命令名做 function name
------------------------------------

试过直接用中文，DeepSeek 能接受，但 OpenAI 兼容层不保证；而且一旦调用方
换成别的模型就会静默失败。用 ASCII 名 + 中文 description 在任何模型上都成立。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "build_tool_schemas",
    "get_tool_map",
    "execute_tool_call",
    "invalidate_cache",
]

# 缓存：构建 schema 要扫全部 manifest，调用频繁，缓存 60 秒
_CACHE_TTL_SECONDS = 60.0
_cache: Dict[str, Any] = {"schemas": None, "map": None, "built_at": 0.0}

# function name 前缀，用于识别「这个调用是不是我们的 MCP 工具」
PREFIX = "mcp__"

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _service_slug(name: str) -> str:
    """服务名转 ASCII 片段（目录名本来就合规，这里只是兜底）。"""
    slug = _SANITIZE_RE.sub("_", name or "")
    return slug.strip("_") or "svc"


def _json_type(value: Any) -> str:
    """把示例值的 Python 类型映射成 JSON Schema 类型。"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _params_from_example(example: str) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """从 example JSON 反推参数表。

    Returns:
        (properties, required, unknown) —— unknown 是解析失败时的空结果标记
    """
    try:
        obj = json.loads(example) if isinstance(example, str) else dict(example)
    except Exception:
        return {}, [], ["example_unparsable"]
    if not isinstance(obj, dict):
        return {}, [], ["example_not_object"]

    properties: Dict[str, Any] = {}
    required: List[str] = []
    for key, value in obj.items():
        # tool_name 是本地派发用的键，不属于「模型要填的参数」
        if key == "tool_name":
            continue
        properties[key] = {
            "type": _json_type(value),
            "description": f"示例值: {value!r}" if value not in ("", None) else "",
        }
        required.append(key)
    return properties, required, []


def _param_clause(description: str, key: str) -> str:
    """截出「某个参数自己的说明子句」。

    难点在于描述是散文，而且**括号内部也有逗号**::

        url（网页地址，必需），css_selector（可选CSS选择器）…

    直接按逗号切会把 `url` 的句子切到括号中间；按固定窗口又会越界到下一个
    参数（`css_selector` 的"可选"会被误判给 `url`）。

    因此从这里开始向后扫描，**只在括号外**遇到分隔符才停：
    括号外的第一个 `，,；;\\n` 就是该参数的说明边界。
    """
    idx = description.find(key)
    if idx < 0:
        return ""
    depth = 0
    out = []
    for ch in description[idx: idx + 200]:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in "，,；;\n":
            break
        out.append(ch)
    return "".join(out)


def _drop_optional_from_required(
    properties: Dict[str, Any], required: List[str], description: str
) -> List[str]:
    """从描述里的「选填 / 可选 / 默认 / 不传」字样判断哪些参数其实不必填。

    manifest 把参数说明写成了散文，没有机器可读的 required 标记。这里只看
    **该参数自己的说明子句**（见 `_param_clause`），不会被邻居的参数污染。

    保守原则：默认全部必填；只有明确标了可选才移除。宁可让模型多填一个
    参数，也不要让它少填导致工具静默使用错误的默认值。
    """
    if not description or not required:
        return required

    optional_marks = (
        "选填", "可选", "默认", "optional", "非必需", "非必填",
        "不传", "可省略", "自动识别",
    )

    keep: List[str] = []
    for key in required:
        clause = _param_clause(description, key)
        if clause and any(mark in clause for mark in optional_marks):
            continue
        keep.append(key)
    return keep


def _build_one(
    service_key: str,
    slug: str,
    display_name: str,
    index: int,
    command: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Tuple[str, str]]]:
    """把一条 invocationCommand 转成一个 OpenAI tool 定义。

    Args:
        service_key: 注册表里的服务键（= manifest 的 displayName，可能是中文），
                     调用时要用它去 ``unified_call``
        slug: ASCII 片段（取目录名），只用于生成 function name
        display_name: 展示名（写进 description，模型据此理解工具用途）
    """
    cmd_name = (command.get("command") or "").strip()
    if not cmd_name:
        return None

    func_name = f"{PREFIX}{slug}__{index}"
    desc = (command.get("description") or "").strip()
    example = command.get("example") or ""

    properties, required, problems = _params_from_example(example)
    required = _drop_optional_from_required(properties, required, desc)

    if problems:
        # 没有可用参数信息时退化成自由对象：模型仍可调用，只是参数不被约束
        logger.debug(f"[tool_schemas] {service_key}.{cmd_name} 参数推断失败: {problems}")
        parameters: Dict[str, Any] = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
    else:
        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # description 里必须带上中文命令名 —— 模型据此判断该不该用这个工具
    full_desc = f"【{display_name}】{cmd_name}"
    if desc:
        full_desc += f"：{desc}"
    if not properties:
        full_desc += "（无固定参数）"

    schema = {
        "type": "function",
        "function": {
            "name": func_name,
            "description": full_desc[:1024],   # 各家的 description 上限不一，取保守值
            "parameters": parameters,
        },
    }
    return schema, (service_key, cmd_name)


def _collect() -> Tuple[List[Dict[str, Any]], Dict[str, Tuple[str, str]]]:
    """扫描 MCP manifest，产出 (tools, name→(service_key, command))。

    **为什么直接读磁盘而不是走注册表**：注册表的键是 manifest 的
    ``displayName``（中文），而 ``MCP_REGISTRY`` 只在 MCP 服务启动时由
    ``scan_and_register_mcp_agents()`` 填充 —— 那一步会**实例化每个 agent**
    （import 模块 + 构造对象）。API 服务在启动早期或独立进程里调用会拿到空表，
    而且为了「列出工具」付出实例化代价并不划算。

    这里只读 ``agent-manifest.json``：轻量、无副作用、不受启动顺序影响。
    function name 的 ASCII 片段取自**目录名**（``agent_comic_downloader``），
    ``displayName`` 则原样作为调用键写进 description。
    """
    from pathlib import Path

    tools: List[Dict[str, Any]] = []
    mapping: Dict[str, Tuple[str, str]] = {}

    mcp_dir = Path(__file__).resolve().parent.parent / "mcpserver"
    if not mcp_dir.is_dir():
        logger.warning(f"[tool_schemas] MCP 目录不存在: {mcp_dir}")
        return tools, mapping

    for manifest_path in sorted(mcp_dir.glob("*/agent-manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
        except Exception as exc:
            logger.warning(f"[tool_schemas] 读取 {manifest_path} 失败: {exc}")
            continue

        if (manifest.get("agentType") or "mcp") != "mcp":
            continue

        service_key = manifest.get("displayName") or manifest_path.parent.name
        display_name = service_key
        slug = _service_slug(manifest_path.parent.name)   # 目录名天然 ASCII

        cmds = (manifest.get("capabilities") or {}).get("invocationCommands") or []
        for i, cmd in enumerate(cmds, start=1):
            try:
                built = _build_one(service_key, slug, display_name, i, cmd)
            except Exception as exc:
                logger.warning(f"[tool_schemas] 构建 {service_key}#{i} 失败: {exc}")
                continue
            if not built:
                continue
            schema, meta = built
            mapping[schema["function"]["name"]] = meta
            tools.append(schema)

    return tools, mapping


def invalidate_cache() -> None:
    """清空缓存（注册表变化后调用）。"""
    _cache.update({"schemas": None, "map": None, "built_at": 0.0})


def _ensure_cache() -> None:
    now = time.time()
    if _cache["schemas"] is not None and (now - _cache["built_at"]) < _CACHE_TTL_SECONDS:
        return
    try:
        tools, mapping = _collect()
    except Exception as exc:
        logger.error(f"[tool_schemas] 构建工具表失败: {exc}")
        tools, mapping = [], {}
    # 内置工具（控制应用自身）：不来自 manifest，单独追加
    try:
        from .naga_control import get_action_schemas

        builtin = get_action_schemas()
        if builtin:
            tools = list(tools) + builtin
    except Exception as exc:
        logger.warning(f"[tool_schemas] 内置工具加载失败: {exc}")
    _cache.update({"schemas": tools, "map": mapping, "built_at": now})
    logger.info(f"[tool_schemas] 工具表就绪：{len(tools)} 个工具 / {len(mapping)} 个 MCP 映射")


def build_tool_schemas(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """返回 OpenAI function calling 的 ``tools`` 列表。"""
    if force_refresh:
        invalidate_cache()
    _ensure_cache()
    return list(_cache["schemas"] or [])


def get_tool_map() -> Dict[str, Tuple[str, str]]:
    """返回 ``function_name -> (service_name, command_name)`` 映射。"""
    _ensure_cache()
    return dict(_cache["map"] or {})


async def execute_tool_call(function_name: str, arguments: str) -> str:
    """执行一次工具调用，返回给模型看的文本结果。

    Args:
        function_name: 形如 ``mcp__{service}__{n}``
        arguments: 模型给出的 JSON 字符串

    Returns:
        一定返回字符串（失败也是可读的错误文本），绝不抛异常 ——
        工具失败必须让模型看见原因并决定重试或换条路，而不是中断整个对话。
    """
    mapping = get_tool_map()

    # 内置工具（naga_control__*）：不走 MCP 派发，交给 naga_control 执行
    if function_name.startswith("naga_control__"):
        action = function_name[len("naga_control__"):]
        try:
            from .naga_control import execute, format_result

            args = json.loads(arguments) if arguments else {}
            if not isinstance(args, dict):
                return "错误：参数必须是 JSON 对象"
            result = await execute(action, args)
            return format_result(result)
        except Exception as exc:
            logger.error(f"[tool_schemas] 内置工具 {function_name} 失败: {exc}")
            return f"错误：执行 {action} 时异常：{type(exc).__name__}: {exc}"

    target = mapping.get(function_name)
    if not target:
        return (f"错误：工具 {function_name} 不存在（可能是工具表已刷新）。"
                f"可用工具数 {len(mapping)}。")

    service_name, command_name = target

    # 解析参数
    try:
        args = json.loads(arguments) if arguments else {}
    except Exception as exc:
        return f"错误：参数不是合法 JSON（{exc}）。收到的原始内容：{arguments[:200]!r}"
    if not isinstance(args, dict):
        return f"错误：参数必须是 JSON 对象，收到的是 {type(args).__name__}。"

    # 本地派发接口需要 tool_name 键
    payload = {"tool_name": command_name, **args}

    try:
        from servers.mcpserver.mcp_manager import get_mcp_manager

        manager = get_mcp_manager()
        if manager is None:
            return "错误：MCP 管理器不可用（MCP 服务可能未启动）。"

        result = await manager.unified_call(service_name, command_name, payload)

        # unified_call 失败时返回结构化 dict 或字符串，统一转成文本
        if result is None:
            return f"错误：工具 {command_name} 没有返回结果。"
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as exc:
        logger.error(f"[tool_schemas] 执行工具 {function_name} 失败: {exc}")
        return f"错误：调用 {command_name} 时发生异常：{type(exc).__name__}: {exc}"
