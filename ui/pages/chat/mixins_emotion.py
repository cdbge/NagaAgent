#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live2D 表情联动。

从 ui/controller/tool_chat.py 按职责拆出，用 mixin 保持调用方式不变：
方法体与拆分前逐字相同，只依赖 self.window 与 self.<状态>。
"""

from PyQt5.QtWidgets import QLabel
from core.system.response_util import extract_message
from ui.utils.message_renderer import MessageRenderer
from ui.utils.simple_http_client import SimpleHttpClient, SimpleBatchClient
from core.system.config import config, AI_NAME, logger
from PyQt5.QtCore import QThread, QCoreApplication, Qt, QTimer, QMetaObject, QObject, pyqtSignal
import time
from typing import Dict, Optional


class EmotionMixin:
    """Live2D 表情联动。"""

    def _live2d_widget(self):
        """安全获取 Live2D widget（未启用/未加载时返回 None）。"""
        try:
            side = getattr(self.window, "side", None)
            return getattr(side, "live2d_widget", None) if side else None
        except Exception:
            return None

    def _apply_reply_emotion(self, text: str):
        """按 AI 回复的情绪自动切换 Live2D 表情。

        接入点：流式回复结束（finalize_streaming_response）与工具结果后的回复
        （_handle_tool_ai_response_safe）。

        任何异常都在这里吞掉并只记日志 —— 表情是锦上添花，绝不能影响对话。
        """
        try:
            if not getattr(config.live2d, "auto_emotion", True):
                return
            widget = self._live2d_widget()
            if not widget or not widget.is_model_loaded():
                return

            # 取模型真实拥有的表情名，便于按名称回退
            available = None
            try:
                renderer = getattr(widget, "renderer", None)
                available = getattr(renderer, "loaded_expressions", None)
            except Exception:
                available = None

            from ui.live2d.emotion_binding import bind_emotion_to_live2d

            emotion, intensity = bind_emotion_to_live2d(
                widget, text, available_expressions=available, logger=logger
            )
            if emotion != "neutral" and intensity >= getattr(config.live2d, "emotion_min_intensity", 0.35):
                logger.debug(f"[Live2D] 回复情绪: {emotion} ({intensity})")
        except Exception as e:
            logger.debug(f"[Live2D] 情绪绑定跳过: {e}")
