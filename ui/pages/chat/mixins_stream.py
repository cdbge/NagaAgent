#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流式接收：分片累积 / 打字机 / 收尾渲染。

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


class StreamMixin:
    """流式接收：分片累积 / 打字机 / 收尾渲染。"""

    def append_response_chunk(self, chunk: str):
        """追加响应片段（流式模式）- 实时显示到消息框"""
        # 检查是否为工具调用相关标记
        if any(marker in chunk for marker in ["[TOOL_CALL]", "[TOOL_START]", "[TOOL_RESULT]", "[TOOL_ERROR]"]):
            return

        logger.debug(f"收到chunk：{chunk}")

        # 检查是否在工具调用过程中
        if self.in_tool_call_mode:
            # 工具调用模式结束，创建新的消息框
            self.in_tool_call_mode = False
            self.current_message_id = None

        # 喂给打字机缓冲区 —— 显示节奏由 UI 决定，不再跟着网络 chunk 抖
        if not self.current_message_id:
            self.current_message_id = self.add_ai_message(chunk)
            self.current_response = chunk
        else:
            self.current_response += chunk

        self.stream_typewriter_buffer = self.current_response or ""
        self._start_stream_typewriter()

    def finalize_streaming_response(self):
        """完成流式响应处理：刷新剩余字符，并用 Markdown 渲染最终结果。"""
        # 1) 停表 + 把剩余字符一次性补完（避免收尾时还在一个字一个字动）
        self._stop_stream_typewriter()
        if self.current_response:
            self.stream_typewriter_buffer = self.current_response
            self.stream_typewriter_index = len(self.current_response)

        final_message = None
        if self.current_response:
            # 2) 对累积的完整响应做消息提取
            final_message = extract_message(self.current_response)

            # 3) 收尾：这一次才走完整 Markdown（标题/列表/表格/代码块）
            if self.current_message_id:
                self.update_last_message(final_message, streaming=False)

        # 重置状态
        self.current_response = None
        self.current_message_id = None
        self.last_update_time = 0
        self.stream_typewriter_buffer = ""
        self.stream_typewriter_index = 0

        # 停止加载状态
        self.progress_widget.stop_loading()

        # 按回复情绪自动切换 Live2D 表情（用提取后的完整正文判断）
        if final_message:
            self._apply_reply_emotion(final_message)

    def _start_stream_typewriter(self):
        """启动流式聊天的打字机效果"""
        if self.stream_typewriter_timer and self.stream_typewriter_timer.isActive():
            return

        self.stream_typewriter_timer = QTimer()
        self.stream_typewriter_timer.timeout.connect(self._stream_typewriter_tick)
        self.stream_typewriter_timer.start(self.STREAM_TICK_MS)  # 恒定 16ms/帧

    def _stream_typewriter_tick(self):
        """流式打字机：恒定帧间隔 + 恒定步进（固定宽距，无随机）。"""
        buf = self.stream_typewriter_buffer or ""
        idx = self.stream_typewriter_index
        if idx >= len(buf):
            # 已显示完，等新数据；停表由收尾逻辑负责
            return

        # 落后越多推进越多，但规则是确定的（无随机数）
        backlog = len(buf) - idx
        step = (
            self.STREAM_CHARS_BASE
            + max(0, backlog - self.STREAM_CATCHUP_EVERY)
            // self.STREAM_CATCHUP_EVERY
        )
        step = max(1, min(step, self.STREAM_CATCHUP_MAX, backlog))

        self.stream_typewriter_index = idx + step
        self.update_last_message(
            buf[: self.stream_typewriter_index], streaming=True)

    def _stop_stream_typewriter(self):
        """停止流式打字机效果"""
        if self.stream_typewriter_timer and self.stream_typewriter_timer.isActive():
            self.stream_typewriter_timer.stop()
            self.stream_typewriter_timer.deleteLater()
            self.stream_typewriter_timer = None

    def start_non_stream_typewriter(self, full_text: str):
        """为非流式响应启动打字机效果"""
        # 创建空消息
        message_id = self.add_ai_message("")
        self.non_stream_message_id = message_id
        self.current_message_id = message_id  # 让update_last_message能找到这个消息

        # 初始化打字机变量
        self.non_stream_text = full_text
        self.non_stream_index = 0

        if not self.non_stream_timer:
            self.non_stream_timer = QTimer()
            self.non_stream_timer.timeout.connect(self._non_stream_typewriter_tick)

        # 启动定时器
        self.non_stream_timer.start(100)  # 100ms一个字符

    def _non_stream_typewriter_tick(self):
        """非流式响应的打字机效果tick"""
        if self.non_stream_index >= len(self.non_stream_text):
            # 所有字符都显示完了，停止定时器并清理
            self.non_stream_timer.stop()
            self.non_stream_timer.deleteLater()
            self.non_stream_timer = None

            # 清理临时变量
            self.non_stream_text = None
            self.non_stream_index = None
            self.non_stream_message_id = None
            self.current_message_id = None
            return

        # 每次显示1-3个字符
        next_char = self.non_stream_text[self.non_stream_index]
        chars_to_add = 1

        # 如果是英文字符或空格，可以一次显示多个
        if next_char and ord(next_char) < 128:  # ASCII字符
            chars_to_add = min(3, len(self.non_stream_text) - self.non_stream_index)

        self.non_stream_index += chars_to_add
        displayed_text = self.non_stream_text[:self.non_stream_index]

        # 更新消息显示
        self.update_last_message(displayed_text)
