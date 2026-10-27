from PyQt5.QtWidgets import QLabel
from core.system.response_util import extract_message
from ui.utils.message_renderer import MessageRenderer
from ui.utils.simple_http_client import SimpleHttpClient, SimpleBatchClient
from core.system.config import config, AI_NAME, logger
from PyQt5.QtCore import QThread, QCoreApplication, Qt, QTimer, QMetaObject, QObject, pyqtSignal
import time
from typing import Dict, Optional




def _plain_stream_html(text: str) -> str:
    """流式阶段用的纯文本 HTML。

    为什么流式阶段不做 Markdown：模型吐字是逐片段的，`**`、`###`、``` 这些
    标记经常处于未闭合状态；每帧都重新解析会让同一段文字在"粗体/普通"、
    "标题/正文"之间反复跳，布局跟着重排 —— 肉眼就是文字在上下抖。

    所以流式期间只做 **转义 + 保留换行**，字体字号与最终渲染保持一致，
    收尾时再整体走一次 Markdown。
    """
    import html as _html

    try:
        from ui.styles.tokens import get_theme

        t = get_theme()
        color = t.text
        family = t.font_cn or "Microsoft YaHei UI"
    except Exception:
        color, family = "#EAEAEA", "Microsoft YaHei UI"

    body = _html.escape(text).replace("\n", "<br>")
    return (
        f'<div style="color:{color}; font-family:{family}; '
        f'font-size:13pt; line-height:1.4;">{body}</div>'
    )

from ui.pages.chat.mixins_emotion import EmotionMixin
from ui.pages.chat.mixins_list import MessageListMixin
from ui.pages.chat.mixins_stream import StreamMixin

class ChatTool(MessageListMixin, StreamMixin, EmotionMixin, QObject):
    """聊天主控制器：发送编排、工具调用回调、取消与客户端管理。

    消息列表 / 流式打字机 / Live2D 表情 已按职责拆到同包的 mixin：
        MessageListMixin  消息增删改、滚动、历史
        StreamMixin       分片接收、打字机、收尾渲染
        EmotionMixin      Live2D 表情联动
    用 mixin 是为了这一轮不改调用方（window.chat_tool.xxx 全部不变）。
    """

    #: 工具调用产生的 AI 回复。工作线程不能直接碰 UI，
    #: 通过信号切回主线程处理（见 _handle_tool_ai_response_safe）。
    tool_ai_response_received = pyqtSignal(str)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.current_response = ""  # 当前响应缓冲
        self.scroll_timer = QTimer(window)
        # 外部依赖
        self.chat_layout = window.chat_layout
        self.chat_scroll_area = window.chat_scroll_area
        self.progress_widget = window.progress_widget
        self.user_name = config.ui.user_name
        self.ai_name = AI_NAME
        self.streaming_mode = config.system.stream_mode

        # 消息管理
        self._messages: Dict[str, Dict] = {}  # 消息存储：ID -> 消息信息
        self.message_counter = 0  # 消息ID计数器

        # 流式处理状态
        self.current_message_id: Optional[str] = None  # 当前处理的消息ID
        self.current_response = ""  # 当前响应内容
        self.last_update_time = 0  # 上次UI更新时间（用于节流）

        # 打字机效果相关
        # ---- 流式打字机：恒定节奏，无随机抖动（固定宽距）----
        #: 恒定帧间隔（ms）。16ms ≈ 60fps，文字推进看起来是连续的
        self.STREAM_TICK_MS = 16
        #: 基线每帧推进字数（中英一致，不再按 ASCII 加压）
        self.STREAM_CHARS_BASE = 1
        #: 落后超过 N 字开始加速：每多 N 字多推 1 字
        self.STREAM_CATCHUP_EVERY = 16
        #: 单帧最多推进字数，防止积压时大段瞬移
        self.STREAM_CATCHUP_MAX = 16

        self.stream_typewriter_buffer = ""
        self.stream_typewriter_index = 0
        self.stream_typewriter_timer: Optional[QTimer] = None
        self.non_stream_timer: Optional[QTimer] = None
        self.non_stream_text = ""
        self.non_stream_index = 0
        self.non_stream_message_id = None

        self.current_ai_voice_message_id = None
        # HTTP客户端管理
        self.http_client = None

        # 工具调用状态
        self.in_tool_call_mode = False

        # 连接信号
        self.tool_ai_response_received.connect(self._handle_tool_ai_response_safe)

    def adjust_input_height(self):
        window = self.window
        doc = window.input.document()
        h = int(doc.size().height()) + 10
        window.input.setFixedHeight(min(max(60, h), 150))  # 增加最小高度，与字体大小匹配
        window.input_wrap.setFixedHeight(window.input.height())

    def on_send(self):
        # 1. 获取并验证用户输入
        user_input = self.window.input.toPlainText().strip()
        if not user_input:
            return

        # 2. 清理所有历史状态（合并关联的清理逻辑）
        self._cleanup_all_states()

        # 3. 显示用户消息并清空输入框
        self.add_user_message(config.ui.user_name, user_input)
        self.window.input.clear()

        # 4. 根据模式分发请求
        # 注：原先这里会根据 `game.self_game_enabled` 走"博弈论"非流式分支，
        # 但服务端的博弈流程已随 game/ 模块移除、请求侧 use_self_game 恒为 false，
        # 那个开关现在改为控制"后台意图分析"的启停，与请求路径无关。
        # 因此这里只保留流式/非流式两种模式。
        if self.streaming_mode:
            self._send_stream_request(user_input)
        else:
            self._send_non_stream_request(user_input)

    def _cleanup_all_states(self):
        """合并：清理打字机、消息ID、运行中任务等所有状态"""
        # 清理非流式打字机
        if self.non_stream_timer and self.non_stream_timer.isActive():
            self.non_stream_timer.stop()
            self.non_stream_timer.deleteLater()
            if self.non_stream_text and self.non_stream_message_id:
                self.update_last_message(self.non_stream_text)
        # 重置非流式状态变量
        self.non_stream_timer = self.non_stream_text = self.non_stream_index = self.non_stream_message_id = None

        # 清理流式打字机
        if self.stream_typewriter_timer and self.stream_typewriter_timer.isActive():
            self.stream_typewriter_timer.stop()
            self.stream_typewriter_timer.deleteLater()
        self.stream_typewriter_timer = None  # 重置流式状态

        # 清理消息ID和响应缓冲
        self.current_message_id = self.current_ai_voice_message_id = None
        self.current_response = ""

        # 终止运行中的HTTP客户端
        if self.http_client and self.http_client.isRunning():
            self.cancel_current_task()
            self.http_client.deleteLater()
            self.http_client = None

    def _send_self_game_request(self, user_input):
        """博弈论模式（非流式）请求"""
        api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat"
        data = self._build_request_data(user_input, stream=False, use_self_game=True)

        self.http_client = SimpleBatchClient(api_url, data)
        self._bind_batch_client_signals(self.http_client, "博弈论")
        self.progress_widget.set_thinking_mode()
        self.http_client.start()

    def _send_stream_request(self, user_input):
        """普通流式请求"""
        api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat/stream"
        data = self._build_request_data(user_input, stream=True, use_self_game=False)

        self.http_client = SimpleHttpClient(api_url, data)
        self._bind_stream_client_signals(self.http_client)
        self.progress_widget.set_thinking_mode()
        self.http_client.start()

    def _send_non_stream_request(self, user_input):
        """普通非流式请求"""
        api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat"
        data = self._build_request_data(user_input, stream=False, use_self_game=False)

        self.http_client = SimpleBatchClient(api_url, data)
        self._bind_batch_client_signals(self.http_client, "非流式")
        self.progress_widget.set_thinking_mode()
        self.http_client.start()

    def _build_request_data(self, user_input, stream, use_self_game):
        """构建请求数据（复用逻辑）"""
        data = {
            "message": user_input,
            "stream": stream,
            "use_self_game": use_self_game,
            "session_id": self._get_current_session_id()
        }
        from core.system.config import config as _cfg
        if _cfg.system.voice_enabled and _cfg.voice_realtime.voice_mode in ["hybrid", "end2end"]:
            data["return_audio"] = True
        return data

    def _bind_batch_client_signals(self, client, error_prefix):
        """绑定批量HTTP客户端的信号"""
        client.status_changed.connect(lambda st: self.progress_widget.status_label.setText(st))
        client.error_occurred.connect(lambda err: (
            self.progress_widget.stop_loading(),
            self.add_user_message("系统", f"❌ {error_prefix}调用错误: {err}")
        ))
        client.response_received.connect(lambda text: (
            self.progress_widget.stop_loading(),
            self.start_non_stream_typewriter(text)
        ))

    def _bind_stream_client_signals(self, client):
        """绑定流式HTTP客户端的信号"""
        client.status_changed.connect(lambda st: self.progress_widget.status_label.setText(st))
        client.error_occurred.connect(lambda err: (
            self.progress_widget.stop_loading(),
            self.add_user_message("系统", f"❌ 流式调用错误: {err}")
        ))
        client.chunk_received.connect(self._handle_stream_chunk)
        client.response_complete.connect(self.finalize_streaming_response)

    def _handle_stream_chunk(self, text):
        """处理流式响应片段（文本已经由HTTP客户端解码）"""
        if text.startswith(('session_id: ', 'audio_url: ')):
            return
        self.append_response_chunk(text)

    def handle_tool_call(self, notification: str):
        """处理工具调用通知"""
        # 标记进入工具调用模式
        self.in_tool_call_mode = True

        # 创建专门的工具调用内容对话框
        parent_widget = self.chat_layout.parentWidget()
        tool_call_dialog = MessageRenderer.create_tool_call_content_message(notification, parent_widget)

        # 设置嵌套对话框内容
        nested_title = "工具调用详情"
        nested_content = f"""
工具名称: {notification}
状态: 正在执行...
时间: {time.strftime('%H:%M:%S')}
        """.strip()
        tool_call_dialog.set_nested_content(nested_title, nested_content)

        # 生成消息ID
        self.message_counter += 1
        message_id = f"tool_call_{self.message_counter}"

        # 存储工具调用消息信息
        self._messages[message_id] = {
            'name': '工具调用',
            'content': notification,
            'full_content': notification,
            'dialog_widget': tool_call_dialog,
            'is_tool_call': True
        }

        # 添加到布局
        self._remove_layout_stretch()
        self.chat_layout.addWidget(tool_call_dialog)
        self.chat_layout.addStretch()

        # 滚动到底部
        self.smart_scroll_to_bottom()

        # 在状态栏显示工具调用状态
        self.progress_widget.status_label.setText(f"🔧 {notification}")
        logger.debug(f"工具调用: {notification}")

    def handle_tool_result(self, result: str):
        """处理工具执行结果"""
        # 查找最近的工具调用对话框并更新
        tool_call_updated = False
        if self._messages:
            for message_id, message_info in reversed(list(self._messages.items())):
                if message_id.startswith('tool_call_'):
                    dialog_widget = message_info.get('dialog_widget')
                    if dialog_widget:
                        # 更新工具调用对话框显示结果
                        MessageRenderer.update_message_content(dialog_widget, f"✅ {result}")

                        # 更新嵌套对话框内容
                        if dialog_widget.set_nested_content:
                            nested_title = "工具调用结果"
                            nested_content = f"""
工具名称: {message_info.get('content', '未知工具')}
状态: 执行完成 ✅
时间: {time.strftime('%H:%M:%S')}
结果: {result[:200]}{'...' if len(result) > 200 else ''}
                            """.strip()
                            dialog_widget.set_nested_content(nested_title, nested_content)
                    tool_call_updated = True
                    break

        # 工具调用完成，退出工具调用模式
        self.in_tool_call_mode = False

        # 在状态栏显示工具执行结果
        self.progress_widget.status_label.setText(f"✅ {result[:50]}...")
        logger.debug(f"工具结果: {result}")

        # 如果更新了工具调用对话框，强制刷新UI显示
        if tool_call_updated:
            # 确保UI刷新显示最新的工具结果
            self.smart_scroll_to_bottom()
            # 触发UI重绘
            self.window.update()

    def handle_tool_completed_with_ai_response(self, ai_response: str):
        """处理工具执行完成后的AI回复（线程安全入口）"""
        # 通过信号机制确保在主线程中执行
        self.tool_ai_response_received.emit(ai_response)

    def _handle_tool_ai_response_safe(self, ai_response: str):
        """线程安全地处理工具执行完成后的AI回复"""
        try:
            logger.info(f"[UI] 收到工具完成后的AI回复，内容长度: {len(ai_response)}")
            logger.info(f"[UI] 当前线程: {QThread.currentThread()}")

            # 停止加载状态
            self.progress_widget.stop_loading()

            # 添加AI回复到聊天界面
            if ai_response and ai_response.strip():
                # 直接显示完整的AI回复，不使用打字机效果
                logger.info(f"[UI] 直接显示完整AI回复")
                self.add_ai_message(ai_response)
                logger.info(f"[UI] AI回复已直接添加到聊天界面")

                # 按回复情绪自动切换 Live2D 表情
                self._apply_reply_emotion(ai_response)

                # 保存对话历史到API服务器
                self._save_tool_conversation_to_history(ai_response)
            else:
                logger.warning(f"[UI] 收到空的AI回复")

        except Exception as e:
            logger.error(f"[UI] 处理工具完成后的AI回复失败: {e}")
            self.add_system_message(f"❌ 显示工具结果失败: {str(e)}")

    def _save_tool_conversation_to_history(self, ai_response: str):
        """保存工具对话历史到API服务器"""
        try:
            import httpx
            import asyncio

            # 获取当前会话ID
            session_id = self._get_current_session_id()
            if not session_id:
                logger.warning("[UI] 无法获取会话ID，跳过历史记录保存")
                return

            # 构建保存请求
            save_data = {
                "session_id": session_id,
                "user_message": "[工具执行结果]",  # 占位用户消息
                "assistant_response": ai_response
            }

            api_url = f"http://{config.api_server.host}:{config.api_server.port}/save_tool_conversation"

            # 异步发送保存请求
            async def _save_async():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(api_url, json=save_data)
                    if response.status_code == 200:
                        logger.info(f"[UI] 工具对话历史已保存到API服务器")
                    else:
                        logger.error(f"[UI] 保存工具对话历史失败: {response.status_code}")

            # 在事件循环中运行异步任务
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_save_async())
            else:
                loop.run_until_complete(_save_async())

        except Exception as e:
            logger.error(f"[UI] 保存工具对话历史失败: {e}")

    def _get_current_session_id(self) -> str:
        """获取当前会话ID"""
        try:
            # 从窗口对象获取会话ID
            if hasattr(self.window, 'session_id') and self.window.session_id:
                return self.window.session_id

            # 如果窗口没有会话ID，尝试从HTTP客户端响应中获取
            if hasattr(self, 'http_client') and self.http_client:
                # 检查HTTP客户端是否有会话ID
                if hasattr(self.http_client, 'last_session_id') and self.http_client.last_session_id:
                    # 保存到窗口对象以便后续使用
                    self.window.session_id = self.http_client.last_session_id
                    return self.http_client.last_session_id

            # 如果都没有，生成一个新的会话ID
            import uuid
            new_session_id = str(uuid.uuid4())
            # 保存到窗口对象
            self.window.session_id = new_session_id
            return new_session_id

        except Exception as e:
            logger.warning(f"[UI] 获取会话ID失败: {e}")
            # 生成一个默认会话ID
            import uuid
            return str(uuid.uuid4())

    def cancel_current_task(self):
        """取消当前任务"""
        # 停止所有打字机效果
        self._stop_stream_typewriter()

        if self.non_stream_timer and self.non_stream_timer.isActive():
            self.non_stream_timer.stop()
            self.non_stream_timer.deleteLater()
            self.non_stream_timer = None

            # 清理非流式打字机变量
            self.non_stream_text = None
            self.non_stream_index = None
            self.non_stream_message_id = None

        # 处理HTTP客户端
        if self.http_client and self.http_client.isRunning():
            # 立即设置取消标志
            self.http_client.cancel()

            # 非阻塞方式处理线程清理
            self.progress_widget.stop_loading()
            self.add_system_message("🚫 操作已取消")

            # 清空当前响应缓冲
            self.current_response = ""
            self.current_message_id = None

            # 使用QTimer延迟处理线程清理，避免UI卡顿
            QTimer.singleShot(50, self._cleanup_http_client)
        else:
            self.progress_widget.stop_loading()

    def _cleanup_http_client(self):
        """清理HTTP客户端资源"""
        if self.http_client:
            self.http_client.quit()
            if not self.http_client.wait(500):  # 只等待500ms
                self.http_client.terminate()
                self.http_client.wait(200)  # 再等待200ms
            self.http_client.deleteLater()
            self.http_client = None

    def messages(self) -> Dict[str, Dict]:
        """获取所有消息"""
        return self._messages.copy()  # 返回副本，防止外部修改



from ..utils.lazy import lazy


@lazy
def chat():
    return ChatTool(config.window)
