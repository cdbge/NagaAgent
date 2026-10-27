#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agentic tool loop：让模型在对话中自己发起工具调用，拿结果，继续推理。

为什么需要它
============

原来的链路是「两次模型往返」：

    用户消息 → [LLM #1 意图分析] → 代码解析出要调哪个工具
             → 调用工具 → [LLM #2 结合结果回答]

第一次调用**只为了判断意图**，它产出的东西除了"该调哪个工具"之外全部丢弃。
原生 function calling 把这一步并进了正常生成：模型一边理解问题，一边决定
要不要调工具、调哪个、参数是什么。省掉的就是那次纯判断的往返。

循环结构
========

::

    round 1: 带着 tools 调模型
             ├─ 没有 tool_calls → 结束，把内容发给前端
             └─ 有 tool_calls   → 执行 → 结果以 role="tool" 塞回 messages
                                  → round 2
    round 2: 再调一次模型（它现在能看到工具结果）……

最多 ``max_rounds`` 轮。最后一轮**不传 tools**，强制模型给出结论而不是继续
无限调工具。

输出格式
========

与 `llm_service.stream_chat_with_context` **完全一致**：``data: <base64>\n\n``。
这样前端（``ui/utils/simple_http_client.py``）无需任何改动 —— 它只负责把
base64 解出来往气泡里追加。工具调用过程只写服务端日志，不混进正文。

安全性
======

* 单个工具失败不中断循环：失败信息作为 ``role="tool"`` 的结果交给模型，
  由它决定重试 / 换工具 / 直接用已有信息回答。
* 连续多轮「所有工具都失败」时提前收尾，避免把 ``max_rounds`` 跑满。
* 任何异常都转成可读文本，不向上抛 —— 对话不能因为工具挂了就断。
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from .tool_schemas import build_tool_schemas, execute_tool_call

logger = logging.getLogger(__name__)

__all__ = ["run_agentic_loop", "MAX_ROUNDS"]

# 兜底轮数：一轮 = 一次模型调用 + 一批工具执行。
# 5 轮足够处理「先搜索再解析再总结」这类多步任务，再多基本是模型在绕圈。
# 实际值由 config.json 的 handoff.max_loop_stream 决定，这里的常量只在配置不可用时生效。
MAX_ROUNDS = 5


def _resolve_max_rounds(explicit: int | None) -> int:
    """取循环上限：显式参数 > config.handoff.max_loop_stream > 常量。"""
    if explicit is not None:
        return max(1, int(explicit))
    try:
        from core.system.config import config

        value = int(getattr(config.handoff, "max_loop_stream", MAX_ROUNDS))
        return max(1, min(value, 20))
    except Exception:
        return MAX_ROUNDS

# 连续多少轮「工具全失败」就提前收尾
_MAX_CONSECUTIVE_FAILURES = 2


def _sse(text: str) -> str:
    """把一段文本编码成前端认识的 SSE 分片。"""
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"data: {b64}\n\n"


def _assistant_tool_message(content: str, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 assistant 的 tool_calls 消息（OpenAI 规范要求原样回传）。"""
    return {
        "role": "assistant",
        # 有 tool_calls 时 content 可以为 None，但保留模型的前置说明更好
        "content": content or None,
        "tool_calls": [
            {
                "id": call["id"] or f"call_{i}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"] or "{}",
                },
            }
            for i, call in enumerate(tool_calls)
        ],
    }


async def run_agentic_loop(
    messages: List[Dict[str, Any]],
    session_id: str = "",
    max_rounds: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
):
    """执行 agentic 循环，产出 SSE 分片（与旧流式接口格式一致）。

    Args:
        messages: 完整消息列表（含 system prompt），本函数会**原地追加**
                  assistant/tool 消息，因此调用方传入的列表会被修改
        session_id: 仅用于日志
        max_rounds: 最大轮数；None 时读 `config.handoff.max_loop_stream`
        tools: 工具定义；为 None 时自动从 MCP manifest 构建

    Yields:
        ``data: <base64>`` 形式的 SSE 文本分片
    """
    from .llm_service import get_llm_service

    if tools is None:
        try:
            tools = build_tool_schemas()
        except Exception as exc:
            logger.warning(f"[AgenticLoop] 工具表构建失败，降级为普通对话: {exc}")
            tools = []

    llm = get_llm_service()
    consecutive_failures = 0
    max_rounds = _resolve_max_rounds(max_rounds)

    for round_num in range(1, max_rounds + 1):
        # 每轮开始前检查上下文长度：工具结果会显著膨胀上下文，尤其多轮之后。
        # 压缩掉早期轮次可以避免 API 因超长报错。压缩失败时保留原文 ——
        # 优化不能变成新的故障源。
        try:
            from .context_compressor import compress_context

            result = await compress_context(messages)
            if result.compressed:
                messages[:] = result.messages
                logger.info(f"[AgenticLoop] 第 {round_num} 轮前已压缩上下文")
        except Exception as exc:
            logger.debug(f"[AgenticLoop] 上下文压缩跳过: {exc}")

        # 最后一轮不传工具：强制模型总结而不是继续调
        round_tools = tools if (tools and round_num <= max_rounds) else None
        if round_num == max_rounds:
            round_tools = None

        round_text = ""
        tool_calls: List[Dict[str, Any]] = []
        finish_reason = "stop"
        error_text = ""

        try:
            async for kind, payload in llm.stream_with_tools(
                messages, tools=round_tools, temperature=0.7
            ):
                if kind == "content":
                    round_text += payload
                    yield _sse(payload)          # 正文实时转发给前端
                elif kind == "reasoning":
                    pass                          # 思考过程不进正文
                elif kind == "tool_calls":
                    tool_calls = payload
                elif kind == "finish":
                    finish_reason = payload
                elif kind == "error":
                    error_text = payload
        except Exception as exc:
            logger.error(f"[AgenticLoop] 第 {round_num} 轮异常: {exc}")
            error_text = f"模型调用出错: {type(exc).__name__}: {exc}"

        if error_text:
            logger.warning(f"[AgenticLoop] 第 {round_num} 轮错误: {error_text}")
            yield _sse(f"\n\n[错误] {error_text}")
            return

        logger.info(
            f"[AgenticLoop] 会话 {session_id} 第 {round_num} 轮完成: "
            f"content={len(round_text)}字, tools={len(tool_calls)}, finish={finish_reason}"
        )

        # 没有工具调用 -> 这就是最终回答，收尾
        if not tool_calls:
            if finish_reason == "length":
                yield _sse(
                    "\n\n[提示] 回复达到 max_tokens 上限被截断。"
                    "注意思考模式的推理 token 也计入 max_tokens。"
                )
            return

        # ---- 执行工具 ----
        messages.append(_assistant_tool_message(round_text, tool_calls))

        round_all_failed = True
        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("arguments", "") or "{}"
            logger.info(f"[AgenticLoop] 执行工具 {name} 参数 {args[:200]}")

            try:
                result = await execute_tool_call(name, args)
            except Exception as exc:
                result = f"错误：工具执行异常 {type(exc).__name__}: {exc}"

            # 判定失败（用于提前收尾）
            is_failure = (
                result.startswith("错误")
                or "调用失败" in result[:40]
                or "未注册" in result[:80]
            )
            if not is_failure:
                round_all_failed = False

            logger.info(
                f"[AgenticLoop] 工具 {name} 返回 {len(result)} 字符"
                f"{'（判定为失败）' if is_failure else ''}"
            )

            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "content": result[:8000],        # 防止超长结果把上下文撑爆
            })

        if round_all_failed:
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    f"[AgenticLoop] 连续 {consecutive_failures} 轮工具全部失败，提前收尾"
                )
                yield _sse("\n\n[提示] 工具连续调用失败，改为直接回答。")
                # 最后再问一次，不给工具
                try:
                    async for kind, payload in llm.stream_with_tools(
                        messages, tools=None, temperature=0.7
                    ):
                        if kind == "content":
                            yield _sse(payload)
                except Exception as exc:
                    logger.error(f"[AgenticLoop] 收尾轮失败: {exc}")
                return
        else:
            consecutive_failures = 0

    # 跑满轮数仍未收敛
    logger.warning(f"[AgenticLoop] 会话 {session_id} 达到最大轮数 {max_rounds}")
    yield _sse("\n\n[提示] 工具调用轮数已达上限，以上为当前结果。")
