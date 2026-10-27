#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文压缩：把过长的对话历史折叠成结构化摘要。

两种场景
========

1. **启动压缩** —— 新会话开始时，把上一个会话的历史压成摘要，注入
   system prompt 的 ``<compress>`` 块里。这样「昨天聊到哪了」不需要用户重述。
2. **运行时压缩** —— agentic loop 每轮开始前检查总 token 数，超过阈值就把
   早期轮次折叠成摘要，只保留最近若干轮原文。防止上下文无限增长导致
   API 报错。

压缩后的格式
============

::

    以下是上次对话的压缩记录：
    <compress>
    {摘要文本}
    </compress>

保留策略
========

按 **loop**（一轮 = 1 条 user 消息 + 其后所有 assistant/tool 消息）为单位
从末尾往前取，同时受两个上限约束：最多 ``MAX_KEEP_LOOPS`` 轮、最多
``MAX_KEEP_TOKENS`` token。前一条 loop 若会把保留区撑爆就停手 ——
**不切碎单轮对话**，否则模型会看到「问一半、答一半」。

与上游实现的差异
================

原实现依赖 ``litellm`` + ``naga_auth``（走厂商自己的云网关）。本项目直连
DeepSeek，因此：

* token 计数改用 ``tiktoken``（未安装时退回字符估算）；
* 摘要生成改用本项目 ``LLMService.get_response``，不再引第三方客户端；
* 压缩模型取 ``config.api.model``（原先写死 ``gpt-4.1-nano``）。

摘要提示词见 ``core/system/prompts/context_compress_prompt.txt``。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "TOKEN_THRESHOLD",
    "CompressResult",
    "count_tokens",
    "compress_context",
    "compress_for_startup",
    "build_compress_block",
]

# ── 常量 ──
# 运行时压缩阈值。DeepSeek 上下文窗口很大，但 prompt 越长越贵也越慢，
# 10 万 token 大约相当于上百轮对话，超过就该折叠了。
TOKEN_THRESHOLD = 100_000
MAX_KEEP_LOOPS = 10          # 保留区最多保留的 loop 数
MAX_KEEP_TOKENS = 10_000     # 保留区 token 上限

COMPRESS_MARKER = "以下是上次对话的压缩记录："
_SUMMARY_MAX_CHARS = 5000
_MSG_MAX_CHARS = 3000        # 单条消息在摘要输入里的截断长度


@dataclass
class CompressResult:
    """压缩结果。"""

    messages: List[Dict]                        # 压缩后（或原始）的消息列表
    sse_events: List[str] = field(default_factory=list)  # 供前端显示的进度事件
    compressed: bool = False                    # 是否实际执行了压缩


# ---------------------------------------------------------------------------
# token 计数
# ---------------------------------------------------------------------------
_ENCODER = None


def _get_encoder():
    """惰性拿一个 tiktoken 编码器（拿不到就返回 None）。"""
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER or None
    try:
        import tiktoken

        # cl100k_base 是 GPT-4/3.5 的编码，对 DeepSeek 只是近似，
        # 但用来判断「是否超过阈值」足够 —— 我们不需要精确账单级数字。
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        logger.debug(f"[压缩] tiktoken 不可用，改用字符估算: {exc}")
        _ENCODER = False
    return _ENCODER or None


def _msg_text(msg: Dict) -> str:
    """提取消息的纯文本（兼容多模态 content 是列表的情况）。"""
    content = msg.get("content", "")
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content or "")


def count_tokens(messages: List[Dict]) -> int:
    """估算消息列表的 token 数。

    优先用 tiktoken 精确算；不可用时按「中文字符约 1 token、其它约 1/4 token」
    粗估 —— 中文场景下 ``字符数 * 1.2`` 会明显高估，反而不如分开算。
    """
    enc = _get_encoder()
    if enc is not None:
        try:
            total = 0
            for msg in messages:
                total += len(enc.encode(_msg_text(msg))) + 4   # 每条消息的固定开销
            return total
        except Exception as exc:
            logger.debug(f"[压缩] tiktoken 计数失败，退回估算: {exc}")

    total = 0.0
    for msg in messages:
        text = _msg_text(msg)
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        total += cjk * 1.0 + other * 0.25 + 4
    return int(total)


# ---------------------------------------------------------------------------
# loop 切分
# ---------------------------------------------------------------------------
def _split_into_loops(messages: List[Dict], start_idx: int) -> List[List[Dict]]:
    """按 loop 切分消息。

    一个 loop = 一条 user 消息 + 其后所有非 user 消息（assistant / tool / …），
    直到下一条 user 消息为止。开头没有 user 的连续消息自成一组。
    """
    loops: List[List[Dict]] = []
    current: List[Dict] = []
    for msg in messages[start_idx:]:
        if msg.get("role") == "user":
            if current:
                loops.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        loops.append(current)
    return loops


def _select_recent_loops(
    loops: List[List[Dict]],
) -> Tuple[List[List[Dict]], List[List[Dict]]]:
    """从末尾往前选保留区，返回 ``(early_loops, recent_loops)``。"""
    if not loops:
        return [], []

    kept: List[List[Dict]] = []
    kept_tokens = 0
    for loop in reversed(loops):
        if len(kept) >= MAX_KEEP_LOOPS:
            break
        loop_tokens = count_tokens(loop)
        if kept and kept_tokens + loop_tokens > MAX_KEEP_TOKENS:
            break
        kept.insert(0, loop)
        kept_tokens += loop_tokens

    # 至少保留最后一轮（当前用户消息所在的 loop）
    if not kept:
        kept = [loops[-1]]

    split = len(loops) - len(kept)
    return loops[:split], loops[split:]


# ---------------------------------------------------------------------------
# 摘要生成
# ---------------------------------------------------------------------------
def _load_summarize_prompt() -> str:
    """读取压缩提示词。"""
    try:
        from core.system.config import get_prompt

        prompt = get_prompt("context_compress_prompt")
        if prompt:
            return prompt
    except Exception as exc:
        logger.warning(f"[压缩] 读取压缩提示词失败，使用内置默认: {exc}")

    return (
        "你是对话状态压缩器。把下面的对话压缩成结构化记录，"
        "保留：用户意图、关键决策、已完成工作、问题与修复、待办、下一步。"
        "用中文，直接输出内容，不要开场白。"
    )


def _format_messages_for_summary(messages: List[Dict]) -> str:
    """把消息列表拼成摘要输入文本。"""
    labels = {"user": "用户", "assistant": "助手", "system": "系统", "tool": "工具结果"}
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = _msg_text(msg)
        if len(content) > _MSG_MAX_CHARS:
            content = content[:_MSG_MAX_CHARS] + "…[截断]"
        lines.append(f"【{labels.get(role, role)}】{content}")
    return "\n\n".join(lines)


async def _generate_summary(conversation_text: str) -> Optional[str]:
    """调用本项目 LLM 生成摘要。失败返回 None（调用方保留原文）。"""
    if not conversation_text.strip():
        return None

    try:
        from servers.apiserver.llm_service import get_llm_service

        llm = get_llm_service()
        prompt = f"{_load_summarize_prompt()}\n\n=== 对话内容 ===\n{conversation_text}"
        summary = await llm.get_response(prompt, temperature=0.3)
        if not summary or not summary.strip():
            logger.warning("[压缩] 模型返回空摘要")
            return None
        summary = summary.strip()
        if len(summary) > _SUMMARY_MAX_CHARS:
            summary = summary[:_SUMMARY_MAX_CHARS] + "…[摘要截断]"
        logger.info(f"[压缩] 摘要生成成功，{len(summary)} 字")
        return summary
    except Exception as exc:
        logger.error(f"[压缩] 摘要生成失败: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# 压缩块
# ---------------------------------------------------------------------------
def build_compress_block(summary: str) -> str:
    """构建注入 system prompt 的 ``<compress>`` 文本块。"""
    return f"\n\n{COMPRESS_MARKER}\n<compress>\n{summary}\n</compress>"


def _write_summary_into_system(system_content: str, summary: str) -> str:
    """把摘要写进 system prompt：已有 ``<compress>`` 块则替换，否则追加。"""
    if "<compress>" in system_content and "</compress>" in system_content:
        replaced = re.sub(
            r"以下是上次对话的压缩记录：\s*<compress>[\s\S]*?</compress>",
            f"{COMPRESS_MARKER}\n<compress>\n{summary}\n</compress>",
            system_content,
        )
        # 正则没匹配上（格式变过）就退回追加，避免覆盖错误位置
        if "<compress>" in replaced:
            return replaced
    return system_content + build_compress_block(summary)


# ---------------------------------------------------------------------------
# 启动压缩
# ---------------------------------------------------------------------------
async def compress_for_startup(
    prev_messages: List[Dict],
    previous_compress: str = "",
) -> Optional[str]:
    """把上一个会话的消息 + 更早的压缩记录合并成新摘要。

    Args:
        prev_messages: 上一个会话的原始消息
        previous_compress: 上一个会话继承下来的压缩记录（可为空）

    Returns:
        摘要文本；没有可压缩内容或失败时返回 None
    """
    if not prev_messages and not previous_compress:
        return None

    parts = []
    if previous_compress:
        parts.append(f"=== 更早对话的压缩记录 ===\n{previous_compress}")
    if prev_messages:
        parts.append(
            "=== 最近一次对话的内容 ===\n" + _format_messages_for_summary(prev_messages)
        )

    summary = await _generate_summary("\n\n".join(parts))
    if summary:
        logger.info(
            f"[启动压缩] {len(prev_messages)} 条消息"
            f"{' + 旧摘要' if previous_compress else ''} → {len(summary)} 字"
        )
    return summary


# ---------------------------------------------------------------------------
# 运行时压缩
# ---------------------------------------------------------------------------
def _sse(chunk_type: str, **kwargs) -> str:
    """格式化一条 SSE 事件（base64 之外的旁路事件，当前未推给前端）。"""
    return f"data: {json.dumps({'type': chunk_type, **kwargs}, ensure_ascii=False)}\n\n"


async def compress_context(messages: List[Dict]) -> CompressResult:
    """超阈值时压缩早期轮次，返回新的消息列表。

    每轮开始前调用；未超阈值时原样返回，开销只有一次 token 计数。
    任何失败都返回**原始消息** —— 压缩是优化，不能因此让对话失败。
    """
    if not messages:
        return CompressResult(messages=messages)

    total_tokens = count_tokens(messages)
    if total_tokens <= TOKEN_THRESHOLD:
        return CompressResult(messages=messages)

    events = [_sse("compress_start",
                   text=f"上下文过长（{total_tokens:,} tokens），正在压缩历史消息…")]

    # 分离 system prompt（压缩摘要要写回这里）
    system_msg = messages[0] if messages[0].get("role") == "system" else None
    start_idx = 1 if system_msg else 0

    all_loops = _split_into_loops(messages, start_idx)
    early_loops, recent_loops = _select_recent_loops(all_loops)

    if not early_loops:
        return CompressResult(
            messages=messages,
            sse_events=events + [_sse("compress_end", text="无需压缩")],
        )

    early_messages = [m for loop in early_loops for m in loop]
    recent_messages = [m for loop in recent_loops for m in loop]

    events.append(_sse(
        "compress_progress",
        text=f"压缩 {len(early_loops)} 轮，保留最近 {len(recent_loops)} 轮…"))

    summary = await _generate_summary(_format_messages_for_summary(early_messages))
    if not summary:
        logger.warning("[压缩] 摘要失败，保留原始上下文")
        return CompressResult(
            messages=messages,
            sse_events=events + [_sse("compress_end", text="压缩失败，保留原始上下文")],
        )

    compressed: List[Dict] = []
    if system_msg:
        compressed.append({
            "role": "system",
            "content": _write_summary_into_system(
                str(system_msg.get("content") or ""), summary),
        })
    else:
        compressed.append({
            "role": "system",
            "content": f"{COMPRESS_MARKER}\n<compress>\n{summary}\n</compress>",
        })
    compressed.extend(recent_messages)

    compressed_tokens = count_tokens(compressed)
    saved = total_tokens - compressed_tokens

    events.append(_sse(
        "compress_end",
        text=f"压缩完成：{total_tokens:,} → {compressed_tokens:,}（节省 {saved:,}）"))

    logger.info(
        f"[压缩] {total_tokens} → {compressed_tokens} tokens（节省 {saved}），"
        f"压缩 {len(early_loops)} 轮 / 保留 {len(recent_loops)} 轮"
    )

    return CompressResult(messages=compressed, sse_events=events, compressed=True)
