#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图路由：在调用主模型前，先挑出「这轮可能用得上哪些工具」。

它解决什么问题
==============

原生 function calling 让模型自己决定调用哪些工具，但**工具定义本身要占用
prompt**。每个工具约 80–150 token，工具一多就很可观：

    18 个工具  ≈ 1.8k token   —— 可以接受，直接全给
    100 个工具 ≈ 10k token    —— 每轮都在为「可能用不到的工具」付费

本模块先用一次极轻量的分类调用判断用户这句话大概需要哪几类工具，
再把工具表缩小后交给主模型。

为什么默认关闭
==============

它**会额外增加一次模型调用**，正好抵消 function calling 省下的那次往返：

* 工具少（当前 18 个）时全量注入更划算 —— 省下的 token 抵不过多一次的延迟；
* 工具多（经验阈值 40 个以上）时才值得。

因此默认 ``api.intent_router_enabled = False``，且有硬性门槛
``SHORTLIST_MIN_TOOLS``：低于该数量直接跳过，无论开关怎么设。

与上游实现的差异
================

原实现用 ``gpt-4.1-nano`` + ``litellm`` + 厂商云网关。本项目只有 DeepSeek 的
访问权，因此：

* 路由模型取 ``config.api.model``；
* 分类调用走本项目 ``LLMService.get_response``；
* 只保留「挑工具」这一个职责 —— 不参与「要不要调工具」的判断，
  那是主模型在 function calling 里顺带完成的事。

失败策略：任何异常都返回 **None**，调用方回退到全量注入。路由是优化，
不能成为对话失败的原因。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "SHORTLIST_MIN_TOOLS",
    "is_enabled",
    "shortlist_tools",
]

# 工具数低于这个值就完全不启用路由（全量注入更划算）
SHORTLIST_MIN_TOOLS = 40

# 分类模型最多输出多少 token（只回一组名字，很短）
_MAX_ROUTER_TOKENS = 200


def is_enabled(tool_count: int) -> bool:
    """判断当前是否值得做工具路由。"""
    try:
        from core.system.config import config

        flag = bool(getattr(config.api, "intent_router_enabled", False))
    except Exception:
        flag = False
    return flag and tool_count >= SHORTLIST_MIN_TOOLS


def _build_router_prompt(user_text: str, tools: Sequence[Dict]) -> str:
    """构造分类提示词：给模型看工具名 + 一句话说明，要求它选一组。"""
    lines = []
    for t in tools:
        fn = t.get("function") or {}
        name = fn.get("name", "")
        desc = (fn.get("description") or "").split("：")[0][:60]
        lines.append(f"- {name}：{desc}")

    return (
        "你是工具路由器。根据用户消息，挑出**最可能用到**的工具名。\n"
        "只输出工具名，一行一个，不要编号、不要解释、不要其它内容。\n"
        "如果这句话不需要任何工具（闲聊、常识问答），只输出：NONE\n\n"
        f"=== 用户消息 ===\n{user_text}\n\n"
        f"=== 可用工具 ===\n" + "\n".join(lines)
    )


async def shortlist_tools(
    user_text: str,
    tools: List[Dict],
    min_keep: int = 3,
    max_keep: int = 15,
) -> Optional[List[Dict]]:
    """挑出与用户消息相关的工具子集。

    Args:
        user_text: 用户最新一条消息
        tools: 全量工具定义
        min_keep / max_keep: 保底与上限，防止模型选出空集或几乎全选

    Returns:
        过滤后的工具列表；**无需路由时返回 None**，调用方应保持全量。
    """
    if not user_text or not tools:
        return None

    if not is_enabled(len(tools)):
        return None

    try:
        from servers.apiserver.llm_service import get_llm_service

        llm = get_llm_service()
        raw = await llm.get_response(_build_router_prompt(user_text, tools), temperature=0.0)
    except Exception as exc:
        logger.warning(f"[IntentRouter] 路由调用失败，回退全量注入: {exc}")
        return None

    if not raw:
        return None

    answer = raw.strip()

    # 模型判定不需要工具：直接返回空列表（由调用方决定是否禁用工具）
    if re.search(r"\bNONE\b", answer, re.IGNORECASE) and not re.search(
            r"mcp__", answer):
        logger.info("[IntentRouter] 判定本句无需工具")
        return []

    # 提取回答里出现的工具名（只认实际存在的，防止模型编造）
    known = {t["function"]["name"] for t in tools if t.get("function")}
    picked = []
    for token in re.findall(r"[A-Za-z0-9_]+", answer):
        if token in known and token not in picked:
            picked.append(token)

    if not picked:
        logger.warning(f"[IntentRouter] 没解析出有效工具名，回退全量。原始返回: {answer[:120]!r}")
        return None

    # 上限保护：模型有时会把几乎所有工具都列出来
    picked = picked[:max_keep]

    # 保底：至少 min_keep 个（用原顺序补齐），避免漏掉真正需要的
    if len(picked) < min_keep:
        for t in tools:
            name = t["function"]["name"]
            if name not in picked:
                picked.append(name)
            if len(picked) >= min_keep:
                break

    selected = [t for t in tools if t["function"]["name"] in picked]
    logger.info(
        f"[IntentRouter] 工具路由: {len(tools)} → {len(selected)} "
        f"({', '.join(picked[:6])}{'…' if len(picked) > 6 else ''})"
    )
    return selected
