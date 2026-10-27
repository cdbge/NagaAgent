#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消息列表：新增 / 更新 / 滚动 / 历史加载。

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


def _plain_stream_html(text: str) -> str:
    """纯文本 → 供 QLabel 用的 HTML（从 tool_chat 复制过来）。

    放在这里而不是从 ui.controller.tool_chat 导入，是为了避免
    tool_chat → mixins_list → tool_chat 的循环导入。
    """
    from ui.controller.tool_chat import _plain_stream_html as _f

    return _f(text)


class MessageListMixin:
    """消息列表：新增 / 更新 / 滚动 / 历史加载。"""

    def _force_relayout(self):
        """强制滚动区重新计算一次高度。

        为什么必须三步：
          invalidate()   丢掉布局缓存的尺寸 —— 新消息入列时它会拿上一条
                         的旧高度定位，导致两条消息叠在一起；
          adjustSize()   让滚动内容按新的 sizeHint 长高；
          activate()     立刻执行排版，而不是等下一帧。
        实测：只用 activate() 时两条消息相隔 15px（气泡高 91px，重叠 76px）；
        加上 invalidate() 后恢复正确的 101px 间距。
        """
        try:
            layout = self.chat_layout
            layout.invalidate()
            content = getattr(self.window, "chat_content", None)
            if content is not None:
                content.adjustSize()
            layout.activate()
            # 立刻排一次还不够：新控件此时可能还没完成 polish，
            # 尺寸仍是旧的。等事件循环跑一拍再排一次才是终态。
            QTimer.singleShot(0, self._force_relayout)
        except Exception as exc:
            logger.debug(f"[聊天] 重排失败: {exc}")
    def _normalize_chat_layout(self):
        """布局归一化：清掉重复 widget 与多余的 stretch。

        重叠的根因是布局里同一个 widget 被加了两次，或末尾累积了多个
        stretch 把后面的消息挤到同一位置。这里统一收一次。
        """
        layout = self.chat_layout
        seen = set()
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is None:
                continue
            if id(w) in seen:
                layout.removeWidget(w)
                w.hide()
                w.setParent(None)
                w.deleteLater()
            else:
                seen.add(id(w))
        # 只保留最后一个 stretch
        stretch_idx = [i for i in range(layout.count())
                       if layout.itemAt(i) is not None
                       and layout.itemAt(i).widget() is None]
        for i in reversed(stretch_idx[:-1]):
            layout.removeItem(layout.itemAt(i))
        self._force_relayout()
    def add_user_message(self, name, content, is_streaming=False):
        window = self.window
        """添加用户消息"""
        msg = extract_message(content)
        content_html = str(msg).replace('\n', '\n\n')#.replace('\n', '<br>')

        # 生成消息ID
        if not self.message_counter:
            self.message_counter = 0
        self.message_counter += 1
        message_id = f"msg_{self.message_counter}"

        # 消息存储由 __init__ 建立，这里**不得清空**。
        # 原代码是 `if self._messages: self._messages = {}` —— 条件写反了，
        # 效果是「只要有消息就把整张表清空」，于是：
        #   * 存在表里的 tool_call_* 卡片会被下一条用户消息抹掉，
        #     handle_tool_result 反向查找时找不到目标，工具结果无法回填；
        #   * clear_chat_history 只能清掉最后一条。
        # 注：这里只做「确保存在」，不做任何重置。
        if self._messages is None:
            self._messages = {}

        # 存储消息信息
        self._messages[message_id] = {
            'name': name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': None
        }

        # 使用消息渲染器创建对话框
        if name == "系统":
            message_dialog = MessageRenderer.create_system_message(name, content_html, window.chat_content)
        else:
            message_dialog = MessageRenderer.create_user_message(name, content_html, window.chat_content)

        # 存储对话框引用
        self._messages[message_id]['dialog_widget'] = message_dialog

        # 先移除stretch
        stretch_found = False
        stretch_index = -1
        for i in reversed(range(window.chat_layout.count())):
            item = window.chat_layout.itemAt(i)
            if item and not item.widget():  # 找到stretch
                window.chat_layout.removeItem(item)
                stretch_found = True
                stretch_index = i
                break

        # 添加消息
        # 先让控件算好尺寸再入列 —— 否则布局拿旧尺寸定位，
        # 新消息会压到上一条上（实测相隔 15px，气泡高 91px）。
        try:
            message_dialog.ensurePolished()
            message_dialog.adjustSize()
        except Exception:
            pass
        window.chat_layout.addWidget(message_dialog)
        self._force_relayout()

        # 重新添加stretch到最后
        window.chat_layout.addStretch()

        # 归一化布局，避免 widget 重复入列造成重叠
        self._normalize_chat_layout()

        # 滚动到底部（要在动效前，否则残影位置算在可视区外）
        self.smart_scroll_to_bottom()

        # 飞入动效：用户消息从输入框升到落点
        if not is_streaming:
            try:
                message_dialog.play_arrival(window.input)
            except Exception as exc:
                logger.debug(f"[动效] 用户消息飞入跳过: {exc}")

        return message_id

    def add_system_message(self, content: str) -> str:
        """添加系统消息到聊天界面"""
        msg = extract_message(content)
        content_html = str(msg)  # .replace('\\n', '\n').replace('\n', '<br>')

        # 生成消息ID
        self.message_counter += 1
        message_id = f"msg_{self.message_counter}"

        # 创建系统消息对话框
        parent_widget = self.chat_layout.parentWidget()
        message_dialog = MessageRenderer.create_system_message(
            "系统", content_html, parent_widget
        )

        # 存储消息信息
        self._messages[message_id] = {
            'name': "系统",
            'content': content_html,
            'full_content': content,
            'dialog_widget': message_dialog,
            'is_ai': False,
            'is_system': True
        }

        # 添加到布局
        self._remove_layout_stretch()
        self.chat_layout.addWidget(message_dialog)
        self.chat_layout.addStretch()

        # 滚动到底部
        self.smart_scroll_to_bottom()
        return message_id

    def add_ai_message(self, content: str = "") -> str:
        """添加AI消息到聊天界面（流式处理时初始化为空消息）"""
        # 对于AI回复，直接使用原始内容，不经过extract_message处理
        # 因为AI回复通常是纯文本或Markdown格式，不是JSON格式
        content_html = content

        logger.info(f"[UI] 添加AI消息，内容长度: {len(content_html)}")

        # 生成消息ID
        self.message_counter += 1
        message_id = f"msg_{self.message_counter}"

        # 创建AI消息对话框
        parent_widget = self.chat_layout.parentWidget()
        message_dialog = MessageRenderer.create_assistant_message(
            self.ai_name, content_html, parent_widget
        )

        # 存储消息信息
        self._messages[message_id] = {
            'name': self.ai_name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': message_dialog,
            'is_ai': True
        }

        # 添加到布局
        self._remove_layout_stretch()
        self.chat_layout.addWidget(message_dialog)
        self.chat_layout.addStretch()

        return message_id

    def update_last_message(self, new_text, streaming=False):
        """更新最后一条消息的内容。

        Args:
            new_text: 目前已知的全文
            streaming: True 时按**纯文本**渲染 ——
                流式阶段每帧跑 Markdown 会让未闭合语法反复改变布局，
                表现就是文字不停上下跳；收尾时再一次性渲染 Markdown。
        """
        msg = extract_message(new_text)
        if streaming:
            content_html = _plain_stream_html(str(msg))
        else:
            # 必须走 markdown_to_html：它会注入主题 CSS。
            # 直接裸调 markdown() 出来的 HTML 没有任何颜色，
            # QTextBrowser 会退回默认黑色字（切主题时才被重绘修正）。
            from ui.utils.markdown_html import markdown_to_html

            content_html = markdown_to_html(str(msg))

        # 优先使用当前消息ID（流式更新时设置的）
        message_id = None
        if self.current_message_id:
            message_id = self.current_message_id
        elif self.current_ai_voice_message_id:
            message_id = self.current_ai_voice_message_id
        elif self._messages:
            message_id = max(
                self._messages.keys(),
                key=lambda x: int(x.split('_')[-1]) if '_' in x else 0)

        # 更新消息内容
        if message_id and message_id in self._messages:
            message_info = self._messages[message_id]

            message_info['content'] = content_html
            message_info['full_content'] = new_text

            dialog = message_info.get('dialog_widget')
            if dialog is not None:
                try:
                    from ui.utils.message_renderer import MessageRenderer

                    MessageRenderer.update_message_content(
                        dialog, new_text, html=content_html)
                except Exception:
                    content_label = dialog.findChild(QLabel)
                    if content_label:
                        content_label.setText(content_html)
                        content_label.setTextFormat(1)
                        content_label.setWordWrap(True)
            elif 'widget' in message_info:
                content_label = message_info['widget'].findChild(QLabel)
                if content_label:
                    content_label.setText(content_html)
                    content_label.setTextFormat(1)
                    content_label.setWordWrap(True)

        # 只在内容高度真的变化时才滚动（避免每帧反复 setValue 造成抖动）
        self._scroll_if_height_changed()

    def _scroll_if_height_changed(self):
        """只在内容高度变化时才滚到底。

        流式时每帧都调一次滚动，即使这一帧没新增行，
        滚动条也会被反复 setValue —— 表现为画面轻微抖动。
        """
        try:
            info = self._messages.get(self.current_message_id or "") or {}
            dlg = info.get('dialog_widget')
            h = dlg.sizeHint().height() if dlg is not None else -1
            if h == getattr(self, '_last_scroll_height', None):
                return
            self._last_scroll_height = h
        except Exception:
            pass
        self.smart_scroll_to_bottom()

    def clear_chat_history(self):
        """清除所有聊天历史"""
        # 清除UI组件
        for msg_id, msg_info in self._messages.items():
            if msg_info['dialog_widget']:
                msg_info['dialog_widget'].deleteLater()

        # 清除布局
        # 注意：只 deleteLater 不会立刻消失 —— 在下一次事件循环处理前，
        # 旧气泡仍覆盖在界面上。如果紧接着又插入新消息，就会出现
        # 「新消息和上一条重叠」（两个 dialog 画在同一处）。
        # 先 setParent(None) 让它立刻脱离视图，再 deleteLater 回收。
        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        # 重置状态
        self._messages.clear()
        self.message_counter = 0
        self.current_message_id = None
        self.current_response = ""

        # 恢复stretch
        self.chat_layout.addStretch()

    def load_persistent_history(self, max_messages: int = 20):
        """从持久化存储加载历史对话"""
        try:
            # 调用MessageRenderer加载历史
            ui_messages = MessageRenderer.load_persistent_context_to_ui(
                parent_widget=self.chat_layout.parentWidget(),
                max_messages=max_messages
            )

            if not ui_messages:
                logger.info("未加载到历史对话")
                return

            # 清空现有布局
            self._remove_layout_stretch()
            while self.chat_layout.count() > 0:
                item = self.chat_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()

            # 加载历史消息到UI和存储
            for message_id, message_info, dialog in ui_messages:
                self.chat_layout.addWidget(dialog)
                self._messages[message_id] = message_info
                self.message_counter = max(self.message_counter, int(message_id.split('_')[-1]))

            # 恢复stretch并滚动到底部
            self.chat_layout.addStretch()
            self.smart_scroll_to_bottom()
            logger.info(f"加载完成 {len(ui_messages)} 条历史对话")

        except Exception as e:
            logger.error(f"加载历史对话失败: {str(e)}")
            self.add_system_message(f"❌ 加载历史对话失败: {str(e)}")

    def smart_scroll_to_bottom(self):
        """智能滚动到底部（如果用户正在查看历史消息，则不滚动）"""
        # 如果不在 Qt 主线程，重新投递
        if QThread.currentThread() != QCoreApplication.instance().thread():
            logger.debug(
                f"不在qt线程。当前线程：{QThread.currentThread()} QT线程：{QCoreApplication.instance().thread()} ")
            QMetaObject.invokeMethod(self, "smart_scroll_to_bottom", Qt.QueuedConnection)
            return

        scrollbar = self.chat_scroll_area.verticalScrollBar()
        is_at_bottom = (scrollbar.value() >= (scrollbar.maximum() - 500))  # 修改距离阈值从1000改为500
        logger.debug(f"移动到末尾的距离检测：{is_at_bottom} 数值：{scrollbar.maximum() - scrollbar.value()} ")
        if is_at_bottom:
            def to_bottom():
                scrollbar.setValue(scrollbar.maximum())

            self.scroll_timer.singleShot(10, to_bottom)

    def _remove_layout_stretch(self):
        """移除布局中最后一个stretch"""
        for i in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(i)
            if item and not item.widget():  # 识别stretch/spacer
                self.chat_layout.removeItem(item)
                break
