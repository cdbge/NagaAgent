#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AI 回复的情绪映射到 Live2D 表情与动作。

设计意图
--------
Live2D 的能力本来就在（`animator.EmotionAnimator` 提供中性/喜悦/悲伤/生气/惊讶
五个语义情绪，`widget.trigger_expression` 可触发模型自带表情），但**没有任何地方
从 AI 的回复文本推导情绪** —— 表情只能靠人手点。本模块补上这条链路：

    回复文本  ->  detect_emotion()  ->  语义情绪 + 强度
              ->  bind_emotion_to_live2d()  ->  set_emotion() + trigger_expression()

模型自带的表情名与语义情绪的对应关系放在 EXPRESSION_MAP 里。
如果换了模型（表情名不同），只需改这张表；代码会自动跳过模型没有的表情。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# ---- 语义情绪（对应 animator.EmotionAnimator.emotions 的键）----
NEUTRAL = "neutral"
HAPPY = "happy"
SAD = "sad"
ANGRY = "angry"
SURPRISED = "surprised"

# 语义情绪 -> Live2D 模型表情名（按优先级排列，取第一个模型真实存在的）
#
# 内置模型「重音テト」的可用表情：
#   Blush / chibi / Cry / Dark Eye / Dark Face / Dizzy / Exp eye / Love /
#   Star Eye / SV Utau ALT / Sweat / 【SV】Baguette / 【SV】Mic / 【Utau】Mic /
#   Remove Water Mark
EXPRESSION_MAP: Dict[str, Tuple[str, ...]] = {
    HAPPY: ("Love", "Star Eye", "Blush"),
    SAD: ("Cry", "Sweat"),
    ANGRY: ("Dark Face", "Dark Eye"),
    SURPRISED: ("Dizzy", "Exp eye"),
    NEUTRAL: (),
}

# 情绪 -> 动作（可选）。模型只有 Idle / Sleep 两个动作组。
MOTION_MAP: Dict[str, Tuple[str, int]] = {
    # 目前不自动触发动作：Idle 已在跑，Sleep 会睡着，都不适合"回复后"触发
}

# ---- 关键词表（从强到弱排列，命中即计数）----
_PATTERNS: Dict[str, Tuple[str, ...]] = {
    HAPPY: (
        "哈哈", "嘿嘿", "嘻嘻", "太好了", "真棒", "好棒", "厉害", "漂亮", "漂亮极了",
        "开心", "高兴", "愉快", "喜欢", "爱了", "赞", "优秀", "完美", "恭喜",
        "欢迎", "没问题", "当然可以", "乐意", "很荣幸", "😊", "😄", "🎉", "❤",
    ),
    SAD: (
        "抱歉", "对不起", "遗憾", "可惜", "难过", "伤心", "失落", "唉", "可惜了",
        "无能为力", "做不到", "无法", "失败", "糟糕", "不太行", "抱歉做不到",
        "😢", "😭",
    ),
    ANGRY: (
        "生气", "愤怒", "讨厌", "烦人", "够了", "不要再", "警告", "不许", "别这样",
        "离谱", "过分", "😠", "😡",
    ),
    SURPRISED: (
        "哇", "咦", "诶", "没想到", "竟然", "居然", "原来如此", "天哪", "不会吧",
        "真的吗", "竟然会", "太神奇", "震惊", "意外", "😮", "😲",
    ),
}

# 中文标点与语气加权
_STRONG_END = ("！", "!", "～", "~", "…", "……")
_QUESTION = ("？", "?")


def detect_emotion(text: str) -> Tuple[str, float]:
    """从回复文本推断情绪，返回 (语义情绪, 强度 0.1~1.0)。

    朴素但可解释的规则法：统计各类关键词命中次数，标点与语气做加权，
    取分最高者；全部为 0 时返回中性。
    """
    if not text:
        return NEUTRAL, 0.0

    # 只看正文，去掉 Markdown 标记与代码块，避免代码里的英文词干扰
    plain = re.sub(r"```.*?```", " ", text, flags=re.S)
    plain = re.sub(r"`[^`]*`", " ", plain)
    plain = re.sub(r"https?://\S+", " ", plain)

    scores: Dict[str, float] = {k: 0.0 for k in _PATTERNS}

    for emotion, words in _PATTERNS.items():
        for w in words:
            if w in plain:
                # 长词更有指向性，给更高权重
                scores[emotion] += 1.0 + min(len(w), 4) * 0.25

    # 语气加权
    if any(p in plain for p in _STRONG_END):
        for k in scores:
            scores[k] += 0.2
    if "！" in plain[:12] or "!" in plain[:12]:
        scores[HAPPY] += 0.3

    best = max(scores, key=lambda k: scores[k])
    top = scores[best]
    if top <= 0:
        return NEUTRAL, 0.0

    total = sum(scores.values()) or 1.0
    confidence = top / total           # 该情绪占全部命中的比例
    intensity = min(1.0, 0.35 + confidence * 0.5 + min(top, 4.0) * 0.05)
    return best, round(intensity, 2)


def pick_expression(emotion: str, available: Optional[Any] = None) -> Optional[str]:
    """在候选表情里挑一个模型真实拥有的。

    available 可以是名字集合/列表；为 None 时不做可用性过滤，直接返回首选。
    """
    candidates = EXPRESSION_MAP.get(emotion, ())
    if not candidates:
        return None
    if available is None:
        return candidates[0]
    if isinstance(available, str):
        available = {available}
    avail = set(available)
    for name in candidates:
        if name in avail:
            return name
    return None


def bind_emotion_to_live2d(
    widget: Any,
    text: str,
    *,
    available_expressions: Optional[Any] = None,
    logger: Any = None,
) -> Tuple[str, float]:
    """把回复文本的情绪应用到 Live2D。

    返回 (情绪, 强度)。失败只记日志，绝不影响对话主流程。
    """
    emotion, intensity = detect_emotion(text)
    if emotion == NEUTRAL or intensity <= 0:
        return emotion, intensity

    try:
        if widget is None or not getattr(widget, "is_model_loaded", lambda: False)():
            return emotion, intensity

        # 1) 语义情绪（驱动面部参数）
        try:
            widget.set_emotion(emotion, intensity)
        except Exception:
            pass

        # 2) 模型自带表情（视觉上更明显）
        expr = pick_expression(emotion, available_expressions)
        if expr:
            try:
                widget.trigger_expression(expr)
            except Exception:
                pass

        if logger:
            logger.debug(f"[Live2D] 情绪绑定: {emotion} (强度 {intensity}) 表情={expr or '无'}")
    except Exception as exc:  # 任何异常都不该影响对话
        if logger:
            logger.debug(f"[Live2D] 情绪绑定失败: {exc}")

    return emotion, intensity


# 情绪 -> 默认返回的中文名（供 UI 提示用）
EMOTION_LABELS: Dict[str, str] = {
    NEUTRAL: "平静",
    HAPPY: "喜悦",
    SAD: "低落",
    ANGRY: "不悦",
    SURPRISED: "惊讶",
}
