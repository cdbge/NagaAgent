import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from .styles.button_factory import ButtonFactory
from PyQt5.QtWidgets import QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFrame
from PyQt5.QtCore import Qt, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen
import os
from core.system.config import config, logger, get_chat_font
from ui.utils.ui_style_hot_reload import register_window as register_ui_style_window
from ui.components.title_bar import TitleBar
from .components.widget_progress import EnhancedProgressWidget
from .components.widget_live2d_side import Live2DSideWidget
from .components.widget_sidebar import SidebarWidget
from .components.widget_mindmap import MindMapWidget
from .components.widget_intent_analysis import IntentAnalysisWidget
from .controller import *

# 使用统一配置系统
def get_ui_config():
    """获取UI配置，确保使用最新的配置值"""
    return {
        'BG_ALPHA': config.ui.bg_alpha,
        'WINDOW_BG_ALPHA': config.ui.window_bg_alpha,
        'USER_NAME': config.ui.user_name,
        'MAC_BTN_SIZE': config.ui.mac_btn_size,
        'MAC_BTN_MARGIN': config.ui.mac_btn_margin,
        'MAC_BTN_GAP': config.ui.mac_btn_gap,
        'ANIMATION_DURATION': config.ui.animation_duration
    }


def refresh_ui_constants():
    global BG_ALPHA, WINDOW_BG_ALPHA, USER_NAME, MAC_BTN_SIZE, MAC_BTN_MARGIN, MAC_BTN_GAP, ANIMATION_DURATION
    ui_config = get_ui_config()
    BG_ALPHA = ui_config['BG_ALPHA']
    WINDOW_BG_ALPHA = ui_config['WINDOW_BG_ALPHA']
    USER_NAME = ui_config['USER_NAME']
    MAC_BTN_SIZE = ui_config['MAC_BTN_SIZE']
    MAC_BTN_MARGIN = ui_config['MAC_BTN_MARGIN']
    MAC_BTN_GAP = ui_config['MAC_BTN_GAP']
    ANIMATION_DURATION = ui_config['ANIMATION_DURATION']


refresh_ui_constants()

class ChatWindow(QWidget):
    # 服务端控制事件的中转信号。
    # 事件总线回调在**服务线程**执行，不能直接改 UI；emit 后由 Qt 排队投递回 GUI 线程。
    control_voice = pyqtSignal(bool)
    control_live2d = pyqtSignal(bool)
    control_emotion = pyqtSignal(str, float)

    def __init__(self):
        super().__init__()
        config.window=self
        self._init_windows()
        self._init_Layout()
        self._init_buttons()
        self._init_side()
        self._init_end()
        register_ui_style_window(self)
        self._subscribe_events()

    def _subscribe_events(self):
        """订阅服务端事件（服务端不 import ui，只发主题）。

        `tool.ai_response`     工具执行完毕后服务端要求界面显示 AI 回复
        `control.voice`        运行时开关语音
        `control.live2d`       运行时显示/隐藏形象
        `control.live2d_emotion` 模型指定表情

        订阅回调在服务线程执行，统一用 signal `emit` 转交 GUI 线程。
        """
        from core.system.event_bus import event_bus
        from ui.controller import chat as _chat

        self.control_voice.connect(self._on_control_voice)
        self.control_live2d.connect(self._on_control_live2d)
        self.control_emotion.connect(self._on_control_emotion)

        self._event_unsubscribers = [
            event_bus.subscribe(
                "tool.ai_response",
                lambda text: _chat.tool_ai_response_received.emit(text)),
            event_bus.subscribe(
                "control.voice",
                lambda enabled: self.control_voice.emit(bool(enabled))),
            event_bus.subscribe(
                "control.live2d",
                lambda enabled: self.control_live2d.emit(bool(enabled))),
            event_bus.subscribe(
                "control.live2d_emotion",
                lambda emotion, intensity=1.0: self.control_emotion.emit(
                    str(emotion), float(intensity))),
        ]

    # -- 控制事件处理（GUI 线程）------------------------------------------
    def _on_control_voice(self, enabled: bool):
        """运行时开关语音：只切开关，不写配置文件。"""
        try:
            from core.system.config import config as _cfg

            _cfg.system.voice_enabled = bool(enabled)
            logger.info(f"[控制] 语音{'开启' if enabled else '暂停'}")
        except Exception as exc:
            logger.warning(f"[控制] 切换语音失败: {exc}")

    def _on_control_live2d(self, enabled: bool):
        """运行时显示/隐藏 Live2D 形象。"""
        try:
            if getattr(self, "side", None) is not None:
                self.side.setVisible(bool(enabled))
            logger.info(f"[控制] Live2D {'显示' if enabled else '隐藏'}")
        except Exception as exc:
            logger.warning(f"[控制] 切换 Live2D 失败: {exc}")

    def _on_control_emotion(self, emotion: str, intensity: float):
        """模型指定表情，转给 Live2D 侧栏。"""
        try:
            side = getattr(self, "side", None)
            widget = getattr(side, "live2d_widget", None) if side else None
            if widget is not None and hasattr(widget, "set_emotion"):
                widget.set_emotion(emotion, intensity)
                logger.info(f"[控制] 表情 → {emotion} ({intensity:.1f})")
        except Exception as exc:
            logger.warning(f"[控制] 设置表情失败: {exc}")

    def _init_windows(self):
        # 设置为屏幕大小的80%
        desktop = QDesktopWidget()
        self.screen_rect = desktop.screenGeometry()
        self.window_width = int(self.screen_rect.width() * 0.8)
        self.window_height = int(self.screen_rect.height() * 0.8)
        self._offset = None
        # 获取屏幕大小并自适应
        self.resize(self.window_width, self.window_height)
        
        # 窗口居中显示
        x = (self.screen_rect.width() - self.window_width) // 2
        y = (self.screen_rect.height() - self.window_height) // 2
        self.move(x, y)
        
        # 移除置顶标志，保留无边框
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 添加窗口背景和拖动支持
        self.setStyleSheet("ChatWindow { background: transparent; }")
        self.titlebar = TitleBar('NAGA AGENT', self)
        self.titlebar.setGeometry(0, 0, self.width(), 44)
    
      
    def _init_Layout(self):
        # 字体统一来自 config.ui（get_chat_font），不再在此硬编码
        # —— 否则调整字号要改多处，且用户无法配置。
        fontfam, fontsize = get_chat_font()
        
        # 创建主分割器，替换原来的HBoxLayout
        self.main_splitter = QSplitter(Qt.Horizontal, config.window)
        self.main_splitter.setStyleSheet("""
            QSplitter {
                background: transparent;
            }
            QSplitter::handle {
                background: rgba(255, 255, 255, 30);
                width: 2px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background: rgba(255, 255, 255, 60);
                width: 3px;
            }
        """)

        # 左侧侧边栏容器
        self.sidebar = SidebarWidget()
        self.sidebar_width = 80
        self.sidebar.setMinimumWidth(self.sidebar_width)
        self.sidebar.setMaximumWidth(self.sidebar_width)  # 固定宽度
        self.main_splitter.addWidget(self.sidebar)

        # 聊天区域容器
        self.chat_area=QWidget()
        self.chat_area.setMinimumWidth(400)
        self.vlay=QVBoxLayout(self.chat_area)
        self.vlay.setContentsMargins(0,0,0,0)
        self.vlay.setSpacing(10)

        self.chat_stack = QStackedWidget(self.chat_area)
        self.chat_stack.setStyleSheet("""
            QStackedWidget {
                background: transparent;
                border: none;
            }
        """)
        self.chat_page = QWidget()
        self.chat_page.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建滚动区域来容纳消息对话框
        self.chat_scroll_area = QScrollArea(self.chat_page)
        self.chat_scroll_area.setWidgetResizable(True)
        # 滚动条常驻：避免「内容变长 -> 条出现 -> 可用宽少 6px -> 整列重排」
        # 造成的横向抖动（对应 Web 端的 scrollbar-gutter: stable）。
        # 本主题下滚动条背景透明、只在可滚动时显示 handle，所以常驻不可见。
        self.chat_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        # 内容长高时自动贴底。用 rangeChanged 而不是定时器 ——
        # 切页/新消息时布局何时算完不确定，定时器容易抓到旧的 maximum。
        self._stick_to_bottom = True
        _chat_bar = self.chat_scroll_area.verticalScrollBar()
        _chat_bar.rangeChanged.connect(self._on_chat_scroll_range_changed)
        _chat_bar.valueChanged.connect(self._on_chat_scroll_value_changed)
        self.chat_scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
                outline: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 30);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 80);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 120);
            }
        """)
        
        # 创建滚动内容容器
        self.chat_content = QWidget()
        self.chat_content.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建垂直布局来排列消息对话框
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch()  # 添加弹性空间，让消息从顶部开始
        self.chat_scroll_area.setWidget(self.chat_content)
        
        # 创建聊天页面布局
        self.chat_page_layout = QVBoxLayout(self.chat_page)
        self.chat_page_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_page_layout.addWidget(self.chat_scroll_area)

        self.chat_stack.addWidget(self.chat_page) # index 0 聊天页
        # 设置页改用声明式实现（ui/pages/settings/）。
        # 旧 SettingWidget 及其依赖已删除，设置页只剩这一套实现。
        from ui.pages.settings.container import SettingsContainer

        self.settings_page = SettingsContainer()
        self.chat_stack.addWidget(self.settings_page) # index 1 设置页
        # index 2 原为空的 QWidget（博弈页）；现改为后台意图分析的观测面板。
        # 「博弈论」是这套机制的历史叫法：分析对话 -> 发现任务 -> 经 MCP 分发工具。
        self.game_page = IntentAnalysisWidget()
        self.chat_stack.addWidget(self.game_page) # index 2 博弈页（意图分析）
        self.mindmap_page = MindMapWidget()
        self.chat_stack.addWidget(self.mindmap_page) # index 3 心智云图页
        self.vlay.addWidget(self.chat_stack, 1)

        # 侧边栏顺序（见 widget_sidebar.items_config）：
        #   0 对话 / 1 心智云图 / 2 博弈图
        # 而 chat_stack 的顺序是：0 聊天 / 1 设置 / 2 博弈 / 3 心智云图。
        # 两者顺序不同，必须显式对应 —— 原先把「心智云图」和「博弈图」写反了，
        # 点「心智云图」实际切到空的博弈页，所以看起来"显示不了"。
        self.sidebar[0] = lambda: self.chat_stack.setCurrentIndex(0)   # 对话
        self.sidebar[1] = self._goto_mindmap                            # 心智云图
        self.sidebar[2] = lambda: self.chat_stack.setCurrentIndex(2)    # 博弈（意图分析）

        # 添加进度显示组件
        self.progress_widget = EnhancedProgressWidget(self.chat_area)
        self.vlay.addWidget(self.progress_widget)
        # 连接进度组件信号
        self.progress_widget.cancel_requested.connect(chat.cancel_current_task)
        
        self.input_wrap=QWidget(self.chat_area)
        self.input_wrap.setFixedHeight(60)  # 增加输入框包装器的高度，与字体大小匹配
        self.hlay=QHBoxLayout(self.input_wrap)
        self.hlay.setContentsMargins(0,0,0,0)
        self.hlay.setSpacing(8)
        self.prompt=QLabel('>',self.input_wrap)
        self.prompt.setStyleSheet(f"color:#fff;font:{fontsize}pt '{fontfam}';background:transparent;")
        self.hlay.addWidget(self.prompt)
        self.input = QTextEdit(self.input_wrap)
        self.input.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(17,17,17,{int(config.ui.bg_alpha*255)});
                color: #fff;
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 50);
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
        """)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.hlay.addWidget(self.input)

    # ------------------------------------------------------------------
    # 聊天字体大小
    # ------------------------------------------------------------------
    def apply_chat_font(self, size=None, family=None, persist=False) -> int:
        """实时应用聊天区字体，返回受影响的气泡数量。

        - 输入框 / 提示符立即重绘
        - 已渲染的历史消息通过 message_renderer.restyle_all 一起重刷
          （渲染器保存了未缩放的原始 QSS，因此可反复调整而不会越缩越小）
        - persist=True 时写回 config.json
        """
        try:
            if size is not None:
                config.ui.font_size = max(10, min(32, int(size)))
            if family:
                config.ui.font_family = family

            fontfam, fontsize = get_chat_font()

            # 输入框 + 提示符
            alpha_px = int(BG_ALPHA * 255)
            self.input.setStyleSheet(f"""
                QTextEdit {{
                    background: rgba(17,17,17,{alpha_px});
                    color: #fff;
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 50);
                    font: {fontsize}pt '{fontfam}';
                    padding: 8px;
                }}
            """)
            self.prompt.setStyleSheet(
                f"color:#fff;font:{fontsize}pt '{fontfam}';background:transparent;")
            self.input_wrap.setFixedHeight(max(60, fontsize * 3 + 12))

            # 已渲染的气泡
            from ui.utils import message_renderer as mr
            mr.refresh_style_constants()
            restyled = mr.restyle_all(self.chat_layout.parentWidget() or self.chat_area)

            if persist:
                try:
                    from core.system.config_manager import update_config
                    update_config({"ui": {"font_size": int(fontsize),
                                          "font_family": fontfam}})
                except Exception as exc:

                    logger.warning(f"字体设置写回失败（本次仍已生效）: {exc}")

            logger.info(f"聊天字体已应用: {fontsize}pt '{fontfam}'，重刷 {restyled} 个控件")
            return restyled
        except Exception as exc:
            logger.error(f"应用聊天字体失败: {exc}")
            return 0

    def _open_font_size_panel(self):
        """在字体按钮旁弹出小面板，拖动即时生效。"""
        try:
            from PyQt5.QtWidgets import QSlider, QPushButton
        except Exception as exc:
            logger.error(f"无法打开字体面板: {exc}")
            return

        # 已打开则先关掉，避免叠加
        old = getattr(self, "_font_panel", None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
            self._font_panel = None
            return

        panel = QFrame(self, Qt.Popup)
        panel.setObjectName("fontPanel")
        panel.setStyleSheet("""
            QFrame#fontPanel {
                background: rgba(28,28,28,240);
                border: 1px solid rgba(255,255,255,60);
                border-radius: 10px;
            }
            QLabel { color: #F0F2F7; font-size: 12px; }
            QLabel#fsValue { color: #7BD65C; font-weight: 600; }
            QPushButton {
                background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 6px; padding: 4px 10px;
                color: #F0F2F7; font-size: 12px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.20); }
            QSlider::groove:horizontal {
                height: 4px; background: rgba(255,255,255,0.20); border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px; margin: -6px 0; border-radius: 7px;
                background: #64C8FF;
            }
        """)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.addWidget(QLabel("字体大小"))
        head.addStretch()
        value_lbl = QLabel()
        value_lbl.setObjectName("fsValue")
        head.addWidget(value_lbl)
        lay.addLayout(head)

        slider = QSlider(Qt.Horizontal, panel)
        slider.setRange(10, 32)
        slider.setSingleStep(1)
        slider.setPageStep(2)
        slider.setFixedWidth(220)
        slider.setValue(int(get_chat_font()[1]))
        lay.addWidget(slider)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for name, size in (("小", 12), ("中", 16), ("大", 20), ("特大", 24)):
            b = QPushButton(name, panel)
            b.clicked.connect(lambda _=False, s=size: (slider.setValue(s),
                                                       self.apply_chat_font(s, persist=True)))
            presets.addWidget(b)
        lay.addLayout(presets)

        def on_change(v: int):
            value_lbl.setText(f"{v} pt")
            self.apply_chat_font(v)          # 拖动即时预览，不写盘

        def on_release():
            self.apply_chat_font(slider.value(), persist=True)

        slider.valueChanged.connect(on_change)
        slider.sliderReleased.connect(on_release)
        on_change(slider.value())

        panel.adjustSize()
        # 贴在按钮正上方
        pos = self.font_size_btn.mapToGlobal(self.font_size_btn.rect().topLeft())
        panel.move(pos.x() - panel.width() // 2 + self.font_size_btn.width() // 2,
                   pos.y() - panel.height() - 8)
        panel.show()
        self._font_panel = panel

    def _goto_mindmap(self):
        """切到心智云图页。
        页面内没有任何按钮（纯画布），因此这里负责按需刷新：
        数据文件比图谱新才重新生成，否则直接加载现有图谱。
        """
        self.chat_stack.setCurrentIndex(3)
        try:
            self.mindmap_page.ensure_fresh()
        except Exception:
            pass

    def _init_buttons(self):
        # 初始化消息存储
        self._messages = {}
        self._message_counter = 0

        self.input.textChanged.connect(chat.adjust_input_height)
        self.input.installEventFilter(self)
        
        # 添加文档上传按钮
        self.upload_btn = ButtonFactory.create_action_button("upload", self.input_wrap)
        self.hlay.addWidget(self.upload_btn)
        # 连接文档上传按钮
        self.upload_btn.clicked.connect(document.upload_document)
        
        # 添加心智云图按钮
        self.mind_map_btn = ButtonFactory.create_action_button("mind_map", self.input_wrap)
        self.hlay.addWidget(self.mind_map_btn)
        # 连接心智云图按钮
        self.mind_map_btn.clicked.connect(mindmap.open_mind_map)

        # 添加字体大小按钮（弹小面板，即时生效）
        self.font_size_btn = ButtonFactory.create_action_button("font_size", self.input_wrap)
        self.hlay.addWidget(self.font_size_btn)
        self.font_size_btn.clicked.connect(self._open_font_size_panel)

        # 添加博弈论启动/关闭按钮
        self.self_game_btn = ButtonFactory.create_action_button("self_game", self.input_wrap)
        self.self_game_btn.setToolTip("启动/关闭博弈论流程")
        self.hlay.addWidget(self.self_game_btn)
        # 连接博弈论按钮
        self.self_game_btn.clicked.connect(game.toggle_self_game)

        # 添加实时语音按钮
        self.voice_realtime_btn = ButtonFactory.create_action_button("voice_realtime", self.input_wrap)
        self.voice_realtime_btn.setToolTip("启动/关闭实时语音对话")
        self.hlay.addWidget(self.voice_realtime_btn)
        # 连接实时语音按钮
        self.voice_realtime_btn.clicked.connect(voice.toggle_voice_realtime)

        
    def _init_side(self):
        self.vlay.addWidget(self.input_wrap,0)
        # 将聊天区域添加到分割器
        self.main_splitter.addWidget(self.chat_area)
        
        # 侧栏（Live2D/图片显示区域）- 使用Live2D侧栏Widget
        self.side = Live2DSideWidget()
        self.collapsed_width = 480  # 收缩状态宽度
        self.expanded_width = 800  # 展开状态宽度
        self.side.setMinimumWidth(self.collapsed_width)  # 设置最小宽度为收缩状态
        self.side.setMaximumWidth(self.collapsed_width)  # 初始状态为收缩
        
        # 悬停只提亮描边，**不动背景透明度**。
        # 原来这里把 bg_alpha 砍半，叠加 Live2D 的 WA_TranslucentBackground，
        # 鼠标一放上去整块就变透明、能看见桌面（穿帮）。
        def _enter(e):
            self.side.set_border_alpha(110)
        self.side.enterEvent = _enter

        def _leave(e):
            self.side.set_border_alpha(50)
        self.side.leaveEvent = _leave
        
        # 设置鼠标指针，提示可点击
        self.side.setCursor(Qt.PointingHandCursor)

        # 创建包装函数，在编辑模式下不触发toggle_full_img
        original_toggle = side.toggle_full_img
        def wrapped_mouse_press(e):
            # 如果在编辑模式下，调用侧边栏自己的mousePressEvent
            if hasattr(self.side, 'edit_mode') and self.side.edit_mode:
                Live2DSideWidget.mousePressEvent(self.side, e)
            else:
                original_toggle(e)

        self.side.mousePressEvent = wrapped_mouse_press # 侧栏点击切换聊天/设置
        
        # 设置默认图片
        default_image = os.path.join(os.path.dirname(__file__), 'img/standby.png')
        if os.path.exists(default_image):
            self.side.set_fallback_image(default_image)
        
        # 连接Live2D侧栏的信号
        self.side.model_loaded.connect(live2d.on_live2d_model_loaded)
        self.side.error_occurred.connect(live2d.on_live2d_error)
        
        # 将侧栏添加到分割器
        self.main_splitter.addWidget(self.side)
        
        # 设置分割器的初始比例 - 侧栏收缩状态
        self.main_splitter.setSizes([self.sidebar_width, self.window_width - self.sidebar_width - self.collapsed_width - 20, self.collapsed_width])  # 大部分给聊天区域
        
        # 创建包含分割器的主布局
        self.main=QVBoxLayout(self)
        # 上边距 = 标题栏 44 + 留白
        self.main.setContentsMargins(10, 54, 10, 10)
        self.main.setSpacing(0)
        # 档案式骨架：顶栏 + 内容 + 页脚
        self._build_archive_chrome()
        self.main.addWidget(self.archive_header)
        self.main.addWidget(self.main_splitter, 1)
        self.main.addWidget(self.archive_footer)
        self.setLayout(self.main)

        # 初始化Live2D
        self.side.initialize_live2d()

    def _build_archive_chrome(self):
        """构建档案式骨架：顶栏 + 页脚，并把编号导航接到页面栈。

        设计来源：莱茵生命档案册的顶栏/页脚版式（见 docs/UI重构计划书.md）。
        侧边栏图标列改为顶栏编号导航后，原 `SidebarWidget` 隐藏不再参与布局。
        """
        from ui.components.archive import ArchiveFooter, ArchiveHeader

        # 编号导航：00 对话 / 01 云图 / 02 博弈 / 03 设置
        # chat_stack 索引是 0 聊天 / 1 设置 / 2 博弈 / 3 心智云图，
        # 与"编号顺序"不同，这里显式映射，避免以后改动互相踩。
        self._nav_to_stack = {0: 0, 1: 3, 2: 2, 3: 1}

        self.archive_header = ArchiveHeader(self)
        self.archive_footer = ArchiveFooter(self)
        self.archive_header.pageSelected.connect(self._on_nav_selected)
        # 主题按钮：从按钮位置辐射展开（径向揭示）
        self.archive_header.themeCycleRequested.connect(self._on_theme_cycle)
        # 网格叠加按钮（P3 装置层会用到，这里先接好信号）
        self.archive_footer.gridToggled.connect(self._on_grid_toggled)
        self._grid_overlay = False

        # 旧侧边栏退场
        try:
            self.sidebar.setVisible(False)
            self.sidebar.setFixedWidth(0)
            self.main_splitter.setSizes([0, self.window_width - self.collapsed_width, self.collapsed_width])
        except Exception:
            pass

    # 主题循环顺序：少前（深） <-> 莱茵（纸）
    _THEME_CYCLE = ("gfl", "rhine")

    def _on_theme_cycle(self):
        """点击顶栏主题按钮：循环切换，并从按钮位置辐射展开。"""
        from core.system.config import config as _cfg
        from ui.styles.tokens import THEMES

        cur = str(getattr(_cfg.ui, "theme", "gfl") or "gfl").lower()
        try:
            idx = self._THEME_CYCLE.index(cur)
        except ValueError:
            idx = 0
        nxt = self._THEME_CYCLE[(idx + 1) % len(self._THEME_CYCLE)]
        if nxt not in THEMES:
            return

        # 揭示圆心 = 主题按钮中心（换算到窗口坐标）
        origin = None
        try:
            btn = self.archive_header.theme_btn
            c = btn.mapTo(self, btn.rect().center())
            origin = c
        except Exception:
            origin = self.rect().center()

        def _apply():
            _cfg.ui.theme = nxt
            self.apply_ui_style()
            # 持久化（写 config.json，下次启动仍生效）
            try:
                from core.system.config_manager import update_config

                update_config({"ui": {"theme": nxt}})
                # update_config 会触发配置重载，可能读到落盘前的旧文件，
                # 把主题又改回去（表现为点按钮没反应）。这里再压一次。
                _cfg.ui.theme = nxt
                self.apply_ui_style()
            except Exception as exc:
                logger.debug(f"[主题] 持久化失败: {exc}")

        try:
            from ui.components.archive.reveal import play_radial_reveal
            from ui.styles.tokens import get_theme

            edge = get_theme(nxt).accent
            play_radial_reveal(self, _apply, origin, edge_color=edge)
        except Exception as exc:
            logger.warning(f"[主题] 揭示失败，直接切换: {exc}")
            _apply()

    def _on_nav_selected(self, number: int):
        """顶栏编号导航 → 页面栈。

        设置页（编号 03）与「点击 Live2D」共用 enter_settings，
        两条路径对页面栈和导航高亮的处理保持一致。
        """
        if number == 3:
            self.enter_settings(source="nav")
            return
        idx = getattr(self, "_nav_to_stack", {}).get(number)
        if idx is None:
            return
        try:
            self.chat_stack.setCurrentIndex(idx)
            self.archive_header.set_current(number)
            if idx == 0:
                self._scroll_chat_to_bottom()
        except Exception as exc:
            logger.debug(f"[骨架] 切换页面失败: {exc}")

    # ---- 设置页统一入口 ----------------------------------------------

    def _scroll_chat_to_bottom(self):
        """把聊天区滚到底，并保持"贴底"状态。

        为什么之前不生效：切页瞬间布局还没算完，`maximum()` 是旧值，
        定时器再早也是滚到旧的最大值。现在改成两件事：

        1. 记一个 `_stick_to_bottom` 标志，内容长高时由 `rangeChanged` 自动贴底；
        2. 用户手动往上滚就取消贴底，滚回底部再恢复。
        """
        self._stick_to_bottom = True
        try:
            bar = self.chat_scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception:
            pass

    def _on_chat_scroll_range_changed(self, _minimum, maximum):
        """内容高度变化：如果用户没往上翻，就跟着贴到底。"""
        try:
            if getattr(self, "_stick_to_bottom", True):
                self.chat_scroll_area.verticalScrollBar().setValue(maximum)
        except Exception:
            pass

    def _on_chat_scroll_value_changed(self, value):
        """用户手动滚动：离底较远时取消贴底。"""
        try:
            bar = self.chat_scroll_area.verticalScrollBar()
            self._stick_to_bottom = (bar.maximum() - value) < 120
        except Exception:
            pass

    def enter_settings(self, source: str = "nav"):
        """进入设置页的**唯一**入口。

        两条路径都走这里，保证导航高亮、输入框显隐、侧栏样式一致：

        * 顶栏编号导航 `03 设置`
        * 点击右侧 Live2D 立绘
        """
        try:
            self.chat_stack.setCurrentIndex(1)
            if hasattr(self, "archive_header"):
                self.archive_header.set_current(3)
            if source == "live2d":
                try:
                    self.input_wrap.hide()
                except Exception:
                    pass
            self._restyle_side_panel()
        except Exception as exc:
            logger.debug(f"[设置] 进入失败: {exc}")

    def leave_settings(self):
        """离开设置页回到聊天（供 Live2D 再次点击收回）。"""
        try:
            self.chat_stack.setCurrentIndex(0)
            self._scroll_chat_to_bottom()
            if hasattr(self, "archive_header"):
                self.archive_header.set_current(0)
            try:
                self.input_wrap.show()
            except Exception:
                pass
            self._restyle_side_panel()
        except Exception as exc:
            logger.debug(f"[设置] 离开失败: {exc}")

    def _restyle_side_panel(self):
        """侧栏按主题重绘。

        原实现写死 `rgba(17,17,17,...) + border-radius:15px` ——
        深色主题下看不出问题，切到纸色主题就变成一块深色圆角方块。
        """
        try:
            from ui.styles.tokens import get_theme, rgba

            t = get_theme()
            side = getattr(self, "side", None)
            if side is None:
                return
            if not side.objectName():
                side.setObjectName("Live2DSide")
            if t.is_light:
                bg = t.panel_2
                border = t.border
            else:
                bg = rgba(t.panel, int(255 * 0.85))
                border = rgba(t.border, 110)
            side.setStyleSheet(
                "QWidget#Live2DSide {"
                f"  background: {bg};"
                f"  border: 1px solid {border};"
                f"  border-radius: {t.radius_lg}px;"
                "}"
            )
        except Exception as exc:
            logger.debug(f"[设置] 侧栏样式失败: {exc}")

    def _on_grid_toggled(self, on: bool):
        """网格叠加开关（P3 实现具体绘制，这里先记录状态）。"""
        self._grid_overlay = bool(on)
        self.update()

    def _install_archive_chrome(self):  # pragma: no cover - 兼容旧调用
        pass

    def _init_end(self):
        self.resizeEvent(None)  # 强制自适应一次，修复图片初始尺寸
        # 加载历史记录（替换原_self_load_persistent_context_to_ui）
        chat.load_persistent_history(
            max_messages=config.api.max_history_rounds * 2
        )

    def apply_alpha_only(self, full=False):
        """只更新透明度相关的部分（拖动滑块时用）。

        full=False 时跳过消息气泡重绘 —— 那一步要遍历所有可视气泡、
        每个都重设样式表，实测 40ms/帧，是拖动卡顿的元凶。
        拖动过程只动窗口底与侧栏（<1ms），松手后再走 full。

        全量 apply_ui_style 要重建 QSS、重排控件，每帧跑会卡；
        拖动透明度时其实只有窗口底、侧栏、输入区在变，这里只碰这几处。
        """
        try:
            from ui.styles.tokens import get_theme, rgba

            global BG_ALPHA, WINDOW_BG_ALPHA
            # 一个「界面不透明度」同时驱动窗口底与气泡底，
            # 不再让用户分别调两个看不懂的透明度。
            WINDOW_BG_ALPHA = int(config.ui.window_bg_alpha)
            BG_ALPHA = max(0.0, min(1.0, WINDOW_BG_ALPHA / 255.0))

            t = get_theme()
            # 不碰 setStyleSheet：底色由 paintEvent 用最新全局值直接画，
            # 一次 update() 就够，实测 < 2ms。
            if hasattr(self, "side") and hasattr(self.side, "set_background_alpha"):
                self.side.set_background_alpha(
                    255 if t.is_light else int(BG_ALPHA * 255))

            # 消息气泡的背景透明度就是由 BG_ALPHA 控制的，
            # 只重刷可视区内的那几条（通常 5~10 条），不要全量。
            if full:
                try:
                    from ui.utils.message_renderer import MessageDialog

                    for _dlg in self.findChildren(MessageDialog):
                        if _dlg.isVisible():
                            _dlg.apply_theme_style()
                except Exception:
                    pass

            self.update()
        except Exception as exc:
            logger.debug(f"[主题] 快速透明度刷新失败: {exc}")
    def apply_ui_style(self, light=False):
        """按当前主题刷新窗口外观。

        Args:
            light: True 时跳过代价高的部分（消息气泡 / 设置页重绘），
                   仅供拖动滑块时的即时预览使用 —— 全量刷新每帧跑不动。

        所有色值来自 `ui/styles/tokens.py` 的主题实例，这里只做组装 ——
        换肤不需要改这个函数，改 `THEMES` 即可。
        """
        refresh_ui_constants()
        # 把 config 里的透明度同步到模块级全局 ——
        # 设置页改的是 config.ui.bg_alpha，而这里读的是全局 BG_ALPHA，
        # 不同步的话拖滑块完全没有效果。
        global BG_ALPHA, WINDOW_BG_ALPHA
        try:
            WINDOW_BG_ALPHA = int(config.ui.window_bg_alpha)
            BG_ALPHA = max(0.0, min(1.0, WINDOW_BG_ALPHA / 255.0))
        except Exception:
            pass
        from ui.styles.tokens import get_theme, rgba

        t = get_theme()

        # 窗口底色/圆角/描边统一由 paintEvent 绘制（见 paintEvent）。
        # 这里不再写 background/border —— 否则每次改透明度都要 setStyleSheet，
        # 触发整窗子控件样式重算，实测 55ms/次，拖动会卡。
        self.setStyleSheet(f"""
            ChatWindow {{
                background: transparent;
                border: none;
            }}
            /* 滚动条：细直角，主题色。原来的浅灰圆角条太出戏 */
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {t.border};
                min-height: 28px;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {t.accent};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px; border: none; background: transparent;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background: transparent; height: 6px; border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: {t.border}; min-width: 28px; border-radius: 0px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {t.accent}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px; border: none; background: transparent;
            }}
        """)

        alpha_px = int(BG_ALPHA * 255)
        fontfam, fontsize = get_chat_font()
        input_bg = t.panel if t.is_light else rgba(t.panel, alpha_px)
        self.input.setStyleSheet(f"""
            QTextEdit {{
                background: {input_bg};
                color: {t.text};
                border-radius: {t.radius_md}px;
                border: 1px solid {t.border};
                selection-background-color: {t.accent_soft};
                selection-color: {t.text};
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
            QTextEdit:focus {{
                border: 1px solid {t.accent};
            }}
        """)
        # 输入框高度随字号走，否则大字号会被裁掉
        if hasattr(self, "input_wrap"):
            self.input_wrap.setFixedHeight(max(60, fontsize * 3 + 12))
            # 输入框字体必须在这里统一设置：
            # 原先只有 apply_chat_font 会设，而它只在用户改字号时才调用，
            # 启动时没人调 → QTextEdit 用 Qt 默认字体（回退到宋体），
            # 于是输入框里的字和界面其它地方不是一套。
            try:
                from PyQt5.QtGui import QFont

                _fam = (getattr(config.ui, "font_family", "") or fontfam
                        or getattr(t, "font_cn", "Microsoft YaHei UI"))
                _font = QFont()
                # 回退链：用户选的字体可能没有中文字形（如 Lucida Console），
                # 单族名会让每个汉字都掉到宋体回退上，和界面其它文字不一致。
                _stack = [_fam, getattr(t, "font_cn", ""),
                          "Microsoft YaHei UI", "Microsoft YaHei"]
                _stack = [x for i, x in enumerate(_stack) if x and x not in _stack[:i]]
                if hasattr(_font, "setFamilies"):
                    _font.setFamilies(_stack)
                else:
                    _font.setFamily(_stack[0])
                _font.setPointSize(int(fontsize))
                _font.setStyleHint(QFont.SansSerif)
                self.input.setFont(_font)
                self.input.document().setDefaultFont(_font)
            except Exception as exc:
                logger.debug(f"[字体] 输入框字体设置失败: {exc}")
        if hasattr(self, "prompt"):
            self.prompt.setStyleSheet(
                f"color:{t.text_mute};font:{fontsize}pt '{fontfam}';"
                f"background:transparent;")

        if hasattr(self.side, 'set_background_alpha'):
            # 纸色主题用满不透明，深色主题才叠透明度
            _side_alpha = 255 if t.is_light else int(BG_ALPHA * 255)
            self.side.set_background_alpha(_side_alpha)
        if hasattr(self.side, 'set_border_alpha'):
            self.side.set_border_alpha(50)

        try:
            from ui.utils import message_renderer as mr
            mr.refresh_style_constants()
        except Exception:
            pass

        if hasattr(self.titlebar, 'update_style'):
            self.titlebar.update_style()

        # 侧边栏是 QPainter 手绘的，只能通过重绘让新令牌生效
        if hasattr(self, "sidebar") and hasattr(self.sidebar, "update"):
            self.sidebar.update()

        # 刷新档案骨架（顶栏 / 页脚）
        try:
            status = f"MODEL {config.api.model.upper()} · MODE {config.ui.theme.upper()}"
            if hasattr(self, "archive_header"):
                self.archive_header.refresh_style(status)
            if hasattr(self, "archive_footer"):
                self.archive_footer.refresh_style()
            if hasattr(self, "archive_header"):
                self.archive_header.set_current(
                    next((k for k, v in getattr(self, "_nav_to_stack", {}).items()
                           if v == self.chat_stack.currentIndex()), 0))
        except Exception as exc:
            logger.debug(f"[骨架] 刷新失败: {exc}")

        # 注：此处原先有一句
        #   from ui.controller.tool_chat import apply_config
        # 但 tool_chat 里根本没有 apply_config，导入必然抛 ImportError，
        # 又被 except Exception: pass 吞掉，是一段永远不生效的死代码。
        # 聊天区样式刷新已由上面的 message_renderer.refresh_style_constants() 负责。


        # 已有消息气泡跟随主题重绘（否则切换主题后旧消息仍是旧配色）
        if not light:
            try:
                from ui.utils.message_renderer import MessageDialog

                for _dlg in self.findChildren(MessageDialog):
                    _dlg.apply_theme_style()
            except Exception as exc:
                logger.debug(f"[主题] 刷新消息气泡失败: {exc}")

        # 侧栏与设置页跟随主题（纸色主题下侧栏不能是深色圆角块）
        self._restyle_side_panel()
        try:
            if hasattr(self, "settings_page"):
                self.settings_page.apply_theme_style()
        except Exception as exc:
            logger.debug(f"[主题] 设置页重绘失败: {exc}")

        self.update()



#==========MouseEvents==========
    # 添加整个窗口的拖动支持
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._offset and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._offset = None
        event.accept()

    def paintEvent(self, event):
        """绘制窗口背景 + 取景框 + 边缘装置。

        全部取色自当前主题令牌，换肤无需改这里。
        """
        from ui.styles.tokens import get_theme

        t = get_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 主窗口背景
        bg = QColor(t.bg)
        if not t.is_light:
            bg.setAlpha(int(WINDOW_BG_ALPHA))
        painter.setBrush(QBrush(bg))
        pen = QPen(QColor(t.border))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1),
                                t.radius_lg, t.radius_lg)

        # 取景框四角
        try:
            from ui.components.archive import draw_viewfinder

            # 右上角由窗口按钮组自己的包裹框画，这里跳过避免双线
            draw_viewfinder(painter, self.rect().adjusted(7, 7, -8, -8),
                            t.border_strong, arm=16, width=1.1,
                            skip=("tr",))
        except Exception:
            pass

        # 边缘装置
        try:
            self._paint_chat_texture(painter, t)
            self._paint_rails(painter, t)
        except Exception:
            pass

        painter.end()

    def _paint_chat_texture(self, painter: QPainter, t):
        """聊天区背景纹理：少前网格 / 莱茵横线稿纸。

        都不抢内容：线的颜色用主题分割色再压一半透明度，
        远看是纸纹/网格，近看不会干扰阅读。
        """
        try:
            from PyQt5.QtGui import QColor, QPen

            area = self.chat_scroll_area.geometry()
            if area.width() < 40 or area.height() < 40:
                return
            painter.save()
            painter.setClipRect(area)
            if t.is_light:
                # 莱茵：横线稿纸，每 28px 一条
                c = QColor(t.divider)
                c.setAlpha(70)
                pen = QPen(c)
                pen.setWidth(1)
                painter.setPen(pen)
                y = area.top() + 28
                while y < area.bottom():
                    painter.drawLine(area.left(), y, area.right(), y)
                    y += 28
            else:
                # 少前：方格网，每 32px 一格
                c = QColor(t.divider)
                c.setAlpha(38)
                pen = QPen(c)
                pen.setWidth(1)
                painter.setPen(pen)
                x = area.left() + 32
                while x < area.right():
                    painter.drawLine(x, area.top(), x, area.bottom())
                    x += 32
                y = area.top() + 32
                while y < area.bottom():
                    painter.drawLine(area.left(), y, area.right(), y)
                    y += 32
            painter.restore()
        except Exception:
            pass
    def _paint_rails(self, painter: QPainter, t):
        """左右边缘装置：莱茵装订孔 / 少前网格刻度。"""
        top = 54 + 92   # 标题栏(44+留白) + 顶栏(92) 之下
        bottom = self.height() - 32 - 10
        height = max(0, bottom - top)
        if height < 40:
            return

        if t.is_light:
            # 装订孔：一列灰圆点
            hole_r, gap = 3, 46
            color = QColor(t.border)
            color.setAlpha(200)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            for x in (14, self.width() - 15):
                y = top + gap
                while y < bottom - gap:
                    painter.drawEllipse(QPoint(x, y), hole_r, hole_r)
                    y += gap
            painter.setBrush(Qt.NoBrush)
        else:
            # 网格刻度：短竖线，每 5 格加长
            pen = QPen(QColor(t.divider))
            pen.setWidth(1)
            painter.setPen(pen)
            for x in (10, self.width() - 11):
                y, i = top, 0
                while y < bottom:
                    ln = 9 if i % 5 == 0 else 4
                    painter.drawLine(x, y, x + ln, y)
                    y += 12
                    i += 1
        
    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        
        # 其他初始化代码...
        self.setFocus()
        self.input.setFocus()
        # 图片初始化现在由Live2DSideWidget处理
        self._img_inited = True
        
    def resizeEvent(self, e):
        if getattr(self, '_animating', False):  # 动画期间跳过所有重绘操作，避免卡顿
            return
        # 图片调整现在由Live2DSideWidget内部处理
        super().resizeEvent(e)
    
    def closeEvent(self, event):
        """退出前统一收口资源清理。

        原先 ChatWindow **没有** closeEvent，于是：
          * Live2DSideWidget.cleanup() 定义了却从不被调用
            -> Live2D 的 60FPS 渲染定时器与 GL 资源不释放；
          * 心智云图的 QWebEngineView 渲染进程成为孤儿；
          * 正在跑的流式请求与进度动画没有取消。

        每一项都单独 try：任何一项清理失败都不能阻塞退出。
        """
        logger.info("ChatWindow 关闭，开始清理资源...")

        def _safe(name, fn):
            try:
                fn()
            except Exception as exc:
                logger.warning(f"退出清理[{name}]失败（忽略）: {exc}")

        # 1) 取消在跑的对话/流式请求
        _safe("取消当前任务", chat.cancel_current_task)

        # 1b) 退订事件总线，避免服务线程继续投递到已销毁的窗口
        for unsub in getattr(self, "_event_unsubscribers", []):
            _safe("退订事件", unsub)

        # 2) 进度动画
        pw = getattr(self, "progress_widget", None)
        if pw is not None:
            _safe("停止进度动画", pw.stop_loading)

        # 3) 心智云图（QWebEngineView + 右键菜单）
        mp = getattr(self, "mindmap_page", None)
        if mp is not None and hasattr(mp, "cleanup"):
            _safe("释放心智云图", mp.cleanup)

        # 4) 意图分析页（轮询线程）
        gp = getattr(self, "game_page", None)
        if gp is not None and hasattr(gp, "_stop_threads"):
            _safe("停止意图分析轮询", gp._stop_threads)

        # 5) Live2D（60FPS 渲染定时器 + GL 资源）
        side = getattr(self, "side", None)
        if side is not None and hasattr(side, "cleanup"):
            _safe("释放 Live2D 资源", side.cleanup)

        logger.info("ChatWindow 资源清理完成")
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        """事件过滤器：处理输入框的键盘事件，实现回车发送、Shift+回车换行"""
        # 仅处理输入框（self.input）的事件
        if obj != self.input:
            return super().eventFilter(obj, event)

        # 仅处理「键盘按下」事件
        if event.type() == QEvent.KeyPress:
            # 捕获两种回车按键：主键盘回车（Key_Return）、小键盘回车（Key_Enter）
            is_enter_key = event.key() in (Qt.Key_Return, Qt.Key_Enter)
            # 判断是否按住了Shift键
            is_shift_pressed = event.modifiers() & Qt.ShiftModifier

            if is_enter_key:
                if not is_shift_pressed:
                    # 纯回车：发送消息，阻止默认换行
                    chat.on_send()
                    return True  # 返回True表示事件已处理，不传递给输入框
                else:
                    # Shift+回车：放行事件，让输入框正常换行
                    return False  # 返回False表示事件继续传递

        # 其他事件（如普通输入）：正常放行
        return super().eventFilter(obj, event)
    
    
#====================
