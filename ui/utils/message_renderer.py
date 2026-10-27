# message_renderer.py # 独立的消息渲染器
import sys, os, re;

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from typing import List
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QSizePolicy, QPushButton, QHBoxLayout, QTextBrowser  # 统一入口 #
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve  # 统一入口 #
from PyQt5.QtGui import QFont, QColor  # 统一入口 #
from core.system.config import config,logger

# 简化的Markdown渲染函数
def simple_markdown_to_html(text: str) -> str:
    """将Markdown转换为简单的HTML格式"""
    if not text:
        return ""

    # 处理标题
    text = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)

    # 处理粗体
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)

    # 处理斜体
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)

    # 处理代码块 - 先处理多行代码块
    text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', text, flags=re.DOTALL)
    # 处理行内代码
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)

    # 处理列表 - 简化版本
    text = re.sub(r'^\* (.*?)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # 处理换行
    text = text.replace('\n', '<br>')

    return text

# 标记Markdown组件不可用

# 使用统一配置系统
BG_ALPHA = config.ui.bg_alpha
ANIMATION_DURATION = config.ui.animation_duration

# ---- 字体体系 ----------------------------------------------------------
# 全聊天区的字号都由 config.ui.font_size 派生，改一处即整屏生效。
# 原先 'Lucida Console' 与 16/14/12/10pt 散落在本文件 8 处、主窗口 2 处、
# 设置控制器 1 处，既无法调整也无法统一。
FONT_FAMILY = config.ui.font_family
FONT_SIZE = config.ui.font_size

#: 相对基准字号的偏移 -> 语义
#:   0  正文/用户名       -2  次级标题（工具名等）
#:  -4  小字（时间戳）    -6  极小字（标签、徽标）
_FONT_OFFSETS = {"16pt": 0, "14pt": -2, "12pt": -4, "10pt": -6}
_FONT_TOKEN_RE = re.compile(r"\b(?:16|14|12|10)pt\b")


def _pt(offset: int = 0) -> int:
    """按基准字号取一个不小于 8pt 的字号。"""
    return max(8, int(FONT_SIZE) + offset)


def _fs(qss: str) -> str:
    """把 QSS 里硬编码的字号与字体族替换成当前配置值。

    用字符串替换而不是 f-string —— QSS 里大量 ``{ }`` 是 CSS 语法，
    改 f-string 需逐个转义，机械改写容易出错。

    必须用 ``re.sub`` 一次性替换：若按 "16pt"->"12pt" 的顺序逐个
    ``str.replace``，刚写入的 "12pt" 会被后续 "12pt"->"8pt" 规则二次命中，
    导致基准 12 时正文被压成 8pt（级联替换 bug）。
    """
    qss = _FONT_TOKEN_RE.sub(
        lambda m: f"{_pt(_FONT_OFFSETS[m.group(0)])}pt", qss)
    return qss.replace("'Lucida Console'", f"'{FONT_FAMILY}'")


#: 控件属性名：记录未经缩放的原始 QSS
_BASE_QSS_PROP = "_naga_base_qss"


def _apply_style(widget, qss: str) -> None:
    """设置样式表，并记住**原始** QSS 以便改字号后整体重刷。

    若直接在已缩放的 QSS 上再次 _fs()，16pt 会先变 20pt、再被当成固定值，
    反复调整后字号就乱了；记住原始值才能每次都从基准重新派生。
    """
    try:
        widget.setProperty(_BASE_QSS_PROP, qss)
    except Exception:
        pass
    widget.setStyleSheet(_fs(qss))


def restyle_all(root) -> int:
    """按当前字号重刷 root 及其子控件里所有记住过原始 QSS 的控件。

    返回重刷数量。改字号后调用它，已渲染的历史消息也会跟着变。
    """
    count = 0
    try:
        base = root.property(_BASE_QSS_PROP)
        if base:
            root.setStyleSheet(_fs(base))
            count += 1
        for w in root.findChildren(QWidget):
            b = w.property(_BASE_QSS_PROP)
            if b:
                w.setStyleSheet(_fs(b))
                count += 1
    except Exception as exc:
        logger.debug(f"重刷消息样式失败: {exc}")
    return count


def refresh_style_constants():
    global BG_ALPHA, ANIMATION_DURATION, FONT_FAMILY, FONT_SIZE
    BG_ALPHA = config.ui.bg_alpha
    ANIMATION_DURATION = config.ui.animation_duration
    FONT_FAMILY = config.ui.font_family
    FONT_SIZE = config.ui.font_size



class MessageDialog(QFrame):
    """消息卡片。

    两种形态：

    * **用户消息** —— 右对齐的窄气泡，强调色淡底，页眉只留名称与时刻
    * **AI 消息**  —— 左对齐的宽卡片，面板底，带档案编号 / 名称 / 时刻

    固定卡片样式：宽度上限、内边距、圆角、描边全部由主题令牌决定，
    不随内容长短变化 —— 否则会出现"一句话一个小方块、一段话一张大卡片"。

    内容用 `ui/utils/markdown_html.py` 渲染 Markdown（标题/列表/表格/代码块）。
    """

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"

    #: 固定尺寸参数（与内容无关）
    MAX_WIDTH_RATIO = 0.76     # 气泡最大宽度占可用宽度的比例
    MIN_WIDTH = 140
    PADDING_H = 14
    PADDING_V = 10
    HEADER_SPACING = 4

    _seq_counter = 0

    @classmethod
    def _next_seq(cls):
        cls._seq_counter += 1
        return cls._seq_counter

    def __init__(self, name, content, parent=None, role=None):
        super().__init__(parent)
        self.name = name
        self.content = content
        self._role = role or self.ROLE_ASSISTANT
        self._seq = MessageDialog._next_seq()
        self._md_cache = None
        self.setObjectName("MessageDialogRoot")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setup_ui()
        self.apply_theme_style()

    # ------------------------------------------------------------------ 构建
    def _is_user(self):
        return self._role == self.ROLE_USER

    def setup_ui(self):
        """搭建「对齐容器 + 固定卡片 + 页眉 + 内容」。"""
        from ui.styles.tokens import font_stack, get_theme

        t = get_theme()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 3)
        outer.setSpacing(0)

        # 卡片本体
        self.card = QFrame(self)
        self.card.setObjectName("MessageCard")
        # 用 QSS 画背景的 QWidget 子类必须开 WA_StyledBackground，
        # 否则背景由父级继承绘制，控件长高后新区域可能留白（切页才补上）。
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(self.PADDING_H, self.PADDING_V,
                                    self.PADDING_H, self.PADDING_V)
        card_lay.setSpacing(self.HEADER_SPACING)

        # 页眉：编号 + 名称 + 时刻（用户气泡里放右侧，AI 卡片里放左侧）
        header = QWidget(self.card)
        header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        self.num_label = QLabel(self.card)
        self.ts_label = QLabel(self.card)
        self.name_label = QLabel(self.card)

        if self._is_user():
            # 用户气泡：名称右对齐、靠后
            hl.addStretch(1)
            hl.addWidget(self.ts_label)
            hl.addWidget(self.name_label)
        else:
            # AI 卡片：编号在最前，时刻最右
            self.num_label.setText(f"#{self._seq:03d}")
            hl.addWidget(self.num_label)
            hl.addWidget(self.name_label)
            hl.addStretch(1)
            hl.addWidget(self.ts_label)

        self.ts_label.setText(
            __import__("datetime").datetime.now().strftime("%H:%M:%S"))
        self.name_label.setText(self.name)
        card_lay.addWidget(header)

        # 内容：用 QTextBrowser 而非 QLabel —— 表格 + 自动换行时
        # QLabel 的高度计算不可靠（末行会被裁），QTextDocument 才准。
        self.content_view = QTextBrowser(self.card)
        self.content_view.setOpenExternalLinks(True)
        self.content_view.setFrameShape(QFrame.NoFrame)
        self.content_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_view.setSizePolicy(QSizePolicy.Expanding,
                                        QSizePolicy.Fixed)
        self.content_view.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }")
        self.content_view.document().setDocumentMargin(0)
        # 兼容旧字段名：外部有代码引用 content_label
        self.content_label = self.content_view
        card_lay.addWidget(self.content_view)

        # 左右对齐：用户靠右（自然宽度），AI 靠左（铺满到上限）
        if self._is_user():
            self.card.setSizePolicy(QSizePolicy.Preferred,
                                    QSizePolicy.Preferred)
            outer.addStretch(1)
            outer.addWidget(self.card)
        else:
            self.card.setSizePolicy(QSizePolicy.Expanding,
                                    QSizePolicy.Preferred)
            outer.addWidget(self.card)

        # 首次填充内容
        self._render_content()

        # 压印入场（飞入动效由调用方用 play_arrival 覆盖）
        try:
            from PyQt5.QtCore import QTimer

            from ui.styles.motion import animate_press

            QTimer.singleShot(0, lambda: animate_press(self))
        except Exception:
            pass

    # ------------------------------------------------------------------ 内容
    def _render_content(self):
        """把 self.content 按 Markdown 渲染进 content_label。"""
        try:
            from ui.styles.tokens import get_theme
            from ui.utils.markdown_html import markdown_to_html

            t = get_theme()
            html = markdown_to_html(str(self.content or ""), t)
            self._md_cache = html
            self.content_view.setHtml(html)
            self._fit_content_height()
        except Exception as exc:
            logger.warning(f"[MessageDialog] 渲染失败，退化为纯文本: {exc}")
            try:
                import html as _html

                self.content_label.setText(
                    _html.escape(str(self.content or "")).replace("\n", "<br>"))
            except Exception:
                pass

    def update_content(self, new_content, html=None):
        """更新内容。

        Args:
            new_content: 原文（保存下来供主题切换时重渲染）
            html: 已经渲染好的 HTML。流式阶段传纯文本 HTML 走这里，
                  避免再被 Markdown 解析一遍（流式文本里含未闭合语法）。
        """
        self.content = new_content
        if html is not None:
            try:
                self.content_view.setHtml(html)
                self._fit_content_height()
            except Exception as exc:
                logger.debug(f"[MessageDialog] HTML 直传失败: {exc}")
        else:
            self._render_content()
        self.adjustSize()

    def _card_qss(self, t):
        """固定卡片样式：与内容长短无关。"""
        if self._is_user():
            bg = t.bubble_user or t.accent_soft
            border = t.accent
        elif self._role == self.ROLE_SYSTEM:
            bg = t.panel_2
            border = t.divider
        else:
            bg = t.bubble_ai or t.panel
            border = t.border
        return (
            f"QFrame#MessageCard {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: {t.radius_md}px;"
            f"}}"
        )

    def apply_theme_style(self):
        """按当前主题重绘整个卡片（切换主题时对已存在的消息调用）。"""
        try:
            from ui.styles.tokens import font_stack, get_theme

            t = get_theme()
            self.setStyleSheet(self._card_qss(t))

            mono = font_stack(t, "mono")
            cn = font_stack(t, "cn")
            en = font_stack(t, "en")

            self.num_label.setStyleSheet(
                f"color: {t.text_mute}; font-family: {mono};"
                f"font-size: 8pt; background: transparent;")
            self.ts_label.setStyleSheet(
                f"color: {t.text_mute}; font-family: {mono};"
                f"font-size: 7.5pt; background: transparent;")
            self.name_label.setStyleSheet(
                f"color: {t.accent}; font-family: {en};"
                f"font-size: 9.5pt; font-weight: 700; background: transparent;")
            # 内容区：HTML 自带颜色，这里只管字体族与背景
            self.content_view.setStyleSheet(
                f"QTextBrowser {{ background: transparent; border: none;"
                f"  font-family: {cn};"
                f"  font-size: {max(9, int(FONT_SIZE) - 1)}pt; }}")

            # 链接色跟随主题
            pal = self.content_view.palette()
            pal.setColor(pal.Link, QColor(t.accent))
            self.content_view.setPalette(pal)

            # 内容需重渲染：Markdown 里内嵌了主题色
            self._render_content()
            self._update_max_width()
            self.update()
        except Exception as exc:
            logger.debug(f"[主题] 卡片重绘失败: {exc}")

    # ------------------------------------------------------------------ 尺寸
    def _update_max_width(self):
        """固定卡片宽度。

        为什么必须**定宽**：流式输出时如果宽度 = min(内容宽, 上限)，
        内容一多卡片就横向撑开，整行文字跟着重排 —— 肉眼就是「跳」。
        定宽之后文本在固定宽度内换行，只有高度增长，视觉是平滑的。

        用户气泡保持内容自适应（消息短、不流式，定宽会显得空）。
        """
        try:
            parent = self.parentWidget()
            avail = parent.width() if parent is not None else self.width()
            if avail <= 0:
                return
            ratio = self.MAX_WIDTH_RATIO if self._is_user() else 0.94
            w = max(self.MIN_WIDTH, int(avail * ratio))
            # 不要超过自身可用宽度（首次布局时父宽可能还没定）
            w = min(w, max(self.MIN_WIDTH, self.width() or avail))
            if self._is_user():
                self.card.setMaximumWidth(w)
            else:
                # 定宽：AI 回复块始终占满 94%，只有高度随内容增长
                self.card.setFixedWidth(w)
        except Exception:
            pass

    def _fit_content_height(self):
        """按文档实际高度固定内容区高度（滚动条禁用，避免双滚动）。"""
        try:
            doc = self.content_view.document()
            width = max(80, self.content_view.viewport().width())
            doc.setTextWidth(width)
            h = doc.size().height()
            self.content_view.setFixedHeight(int(h) + 2)
        except Exception:
            pass

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_max_width()
        self._fit_content_height()

    def get_preferred_height(self):
        """卡片期望高度（供滚动区估算）。"""
        try:
            return max(48, self.card.sizeHint().height() + 6)
        except Exception:
            return 60

    # ------------------------------------------------------------------ 动效
    def play_arrival(self, input_widget=None):
        """消息直接显示。

        原先这里跑「输入栏 → 气泡」的形变动画（Material Container Transform
        思路：残影迁移 + 双形态交叉淡化）。实测引入不稳定，已按要求移除。
        保留方法名只是为了不打断调用方。
        """
        try:
            self.setVisible(True)
        except Exception:
            pass


class ToolCallDialog(QFrame):
    """工具调用检测提示对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式，与其他对话框保持一致
        self.setStyleSheet(f"""
            ToolCallDialog {{
                background: rgba(17,17,17,{int(BG_ALPHA * 255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """)

        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # 工具调用提示标签
        self.tool_call_label = QLabel("工具调用检测中...")
        _apply_style(self.tool_call_label, """
            QLabel {
                color: #8B8882;
                font-size: 11pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        layout.addWidget(self.tool_call_label)

        # 设置大小策略
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def update_message(self, message):
        """更新工具调用消息"""
        self.tool_call_label.setText(message)
        self.adjustSize()


class ToolCallContentDialog(QFrame):
    """工具调用内容对话框 - 没有用户名，但保持相同UI风格，支持展开嵌套对话框"""

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.content = content
        self.is_expanded = False  # 展开状态标志
        self.nested_dialog = None  # 嵌套对话框
        self.setup_ui()

    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式，与MessageDialog保持一致
        self.setStyleSheet(f"""
            ToolCallContentDialog {{
                background: rgba(17,17,17,{int(BG_ALPHA * 255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """)

        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # 创建水平布局用于内容和展开按钮
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # 内容容器 - 没有用户名标签
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)

        content_widget_layout = QVBoxLayout(self.content_widget)
        content_widget_layout.setContentsMargins(0, 0, 0, 0)
        content_widget_layout.setSpacing(0)

        # 内容文本 - 使用工具调用特有的颜色
        self.content_label = QLabel(self.content)
        self.content_label.setWordWrap(True)  # 允许文本换行
        self.content_label.setTextFormat(Qt.RichText)  # 支持HTML格式
        _apply_style(self.content_label, """
            QLabel {
                color: #8B8882;
                font-size: 13pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.4;
            }
        """)
        content_widget_layout.addWidget(self.content_label)

        content_layout.addWidget(self.content_widget, 1)  # 内容占据大部分空间

        # 展开按钮
        self.expand_button = QPushButton("▶")
        self.expand_button.setFixedSize(24, 24)
        _apply_style(self.expand_button, """
            QPushButton {
                background: rgba(100, 100, 100, 100);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
                color: #8B8882;
                font-size: 9pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(120, 120, 120, 150);
                border: 1px solid rgba(255, 255, 255, 50);
            }
            QPushButton:pressed {
                background: rgba(80, 80, 80, 200);
            }
        """)
        self.expand_button.clicked.connect(self.toggle_expand)
        content_layout.addWidget(self.expand_button)

        layout.addLayout(content_layout)

        # 嵌套对话框容器（初始隐藏）
        self.nested_container = QWidget()
        self.nested_container.setStyleSheet("""
            QWidget {
                background: rgba(25, 25, 25, 150);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 5px;
                margin-top: 5px;
            }
        """)
        self.nested_container.setMaximumHeight(0)  # 初始高度为0
        self.nested_container.hide()

        nested_layout = QVBoxLayout(self.nested_container)
        nested_layout.setContentsMargins(10, 10, 10, 10)
        nested_layout.setSpacing(5)

        # 嵌套对话框标题
        self.nested_title = QLabel("工具调用详情")
        _apply_style(self.nested_title, """
            QLabel {
                color: #aaa;
                font-size: 10pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        nested_layout.addWidget(self.nested_title)

        # 嵌套对话框内容
        self.nested_content = QLabel("这里显示工具调用的详细信息...")
        self.nested_content.setWordWrap(True)
        _apply_style(self.nested_content, """
            QLabel {
                color: #8B8882;
                font-size: 14pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.3;
            }
        """)
        nested_layout.addWidget(self.nested_content)

        layout.addWidget(self.nested_container)

        # 设置大小策略，允许垂直扩展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def toggle_expand(self):
        """切换展开/收缩状态"""
        if self.is_expanded:
            self.collapse_nested()
        else:
            self.expand_nested()

    def expand_nested(self):
        """展开嵌套对话框"""
        if self.is_expanded:
            return

        self.is_expanded = True
        self.expand_button.setText("▼")  # 改变按钮图标

        # 显示嵌套容器
        self.nested_container.show()

        # 创建高度动画
        self.height_animation = QPropertyAnimation(self.nested_container, b"maximumHeight")
        self.height_animation.setDuration(ANIMATION_DURATION)
        self.height_animation.setStartValue(0)
        self.height_animation.setEndValue(200)  # 展开后的高度
        self.height_animation.setEasingCurve(QEasingCurve.OutCubic)

        # 动画完成后调整主对话框高度
        self.height_animation.finished.connect(self.adjust_main_dialog_height)
        self.height_animation.start()

    def collapse_nested(self):
        """收缩嵌套对话框"""
        if not self.is_expanded:
            return

        self.is_expanded = False
        self.expand_button.setText("▶")  # 改变按钮图标

        # 创建高度动画
        self.height_animation = QPropertyAnimation(self.nested_container, b"maximumHeight")
        self.height_animation.setDuration(ANIMATION_DURATION)
        self.height_animation.setStartValue(200)
        self.height_animation.setEndValue(0)
        self.height_animation.setEasingCurve(QEasingCurve.OutCubic)

        # 动画完成后隐藏容器并调整主对话框高度
        self.height_animation.finished.connect(self.hide_nested_container)
        self.height_animation.start()

    def hide_nested_container(self):
        """隐藏嵌套容器"""
        self.nested_container.hide()
        self.adjust_main_dialog_height()

    def adjust_main_dialog_height(self):
        """调整主对话框高度"""
        # 强制重新计算大小
        self.adjustSize()
        # 通知父容器重新布局
        if self.parent():
            self.parent().updateGeometry()

    def set_nested_content(self, title, content):
        """设置嵌套对话框内容"""
        self.nested_title.setText(title)
        self.nested_content.setText(content)

    def update_content(self, new_content):
        """更新工具调用内容"""
        self.content = new_content
        self.content_label.setText(new_content)
        # 强制重新计算大小
        self.content_label.adjustSize()
        self.adjustSize()

    def get_preferred_height(self):
        """获取对话框的推荐高度"""
        # 计算文本高度
        font = QFont(FONT_FAMILY, int(FONT_SIZE))
        metrics = self.content_label.fontMetrics()

        # 获取文本宽度和可用宽度
        text_width = metrics.horizontalAdvance(self.content)
        available_width = self.width() - 40  # 减去padding和margin

        if available_width <= 0:
            available_width = 400  # 默认宽度

        # 计算需要的行数
        lines = max(1, (text_width + available_width - 1) // available_width)

        # 计算内容高度 - 没有用户名，所以不需要name_height
        content_height = lines * metrics.lineSpacing()

        # 基础高度 = padding + 内容 + padding
        base_height = 20 + content_height + 20

        # 如果展开，加上嵌套对话框的高度
        if self.is_expanded:
            base_height += 220  # 嵌套对话框高度 + 间距

        return max(60, base_height)  # 最小高度60px（因为没有用户名）


class MessageRenderer:
    """消息渲染器管理器"""

    @staticmethod
    def create_user_message(name, content, parent):
        """创建用户消息：右对齐气泡。"""
        return MessageDialog(name, content, parent, role=MessageDialog.ROLE_USER)

    @staticmethod
    def create_assistant_message(name, content, parent):
        """创建助手消息：左对齐卡片（带档案编号）。"""
        return MessageDialog(name, content, parent, role=MessageDialog.ROLE_ASSISTANT)

    @staticmethod
    def create_tool_call_message(parent):
        """创建工具调用检测消息对话框"""
        return ToolCallDialog(parent)

    @staticmethod
    def create_tool_call_content_message(content, parent):
        """创建工具调用内容对话框 - 没有用户名"""
        return ToolCallContentDialog(content, parent)

    @staticmethod
    def create_system_message(name, content, parent):
        """创建系统消息：居中弱化卡片。"""
        return MessageDialog(name, content, parent, role=MessageDialog.ROLE_SYSTEM)

    @staticmethod
    def create_history_message(name, content, parent):
        """创建历史消息（用于加载持久化上下文）。"""
        return MessageDialog(name, content, parent, role=MessageDialog.ROLE_ASSISTANT)

    @staticmethod
    def batch_create_history_messages(history_messages, parent_widget):
        """
        批量创建历史消息对话框

        Args:
            history_messages: 历史消息列表，格式为[{"role": "user/assistant", "content": "内容"}]
            parent_widget: 父级容器widget

        Returns:
            List: 创建的消息对话框列表
        """
        dialogs = []

        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                # 从配置获取用户名
                try:
                    from core.system.config import config
                    user_name = config.ui.user_name
                except ImportError:
                    user_name = "用户"
                dialog = MessageRenderer.create_user_message(user_name, content, parent_widget)
            elif role == "assistant":
                # 从配置获取AI名称
                try:
                    from core.system.config import config
                    ai_name = config.system.ai_name
                except ImportError:
                    ai_name = "娜迦"
                dialog = MessageRenderer.create_assistant_message(ai_name, content, parent_widget)
            else:
                # 其他角色使用系统消息样式
                dialog = MessageRenderer.create_system_message(role, content, parent_widget)

            dialogs.append(dialog)

        return dialogs

    @staticmethod
    def load_persistent_context_to_ui(parent_widget, max_messages: int = None) -> List[tuple]:
        """
        将持久化上下文加载到前端UI

        Args:
            parent_widget: 父级容器widget
            max_messages: 最大消息数量限制

        Returns:
            List[tuple]: 返回(消息ID, 消息信息, 对话框组件)的元组列表
        """
        try:
            # 导入消息管理器
            from core.system.message_manager import message_manager

            # 计算最大消息数量
            if max_messages is None:
                try:
                    from core.system.config import config
                    max_messages = config.api.max_history_rounds * 2
                except ImportError:
                    max_messages = 20  # 默认值

            # 加载历史对话
            recent_messages = message_manager.load_recent_context(
                days=message_manager.context_load_days,
                max_messages=max_messages
            )

            if not recent_messages:
                print("[记录] 未找到历史对话记录，跳过前端UI加载")
                return []

            # 批量创建历史消息对话框
            history_dialogs = MessageRenderer.batch_create_history_messages(
                recent_messages, parent_widget
            )

            # 构建返回结果
            ui_messages = []
            for i, (msg, dialog) in enumerate(zip(recent_messages, history_dialogs)):
                message_id = f"history_{i}"
                message_info = {
                    'name': msg.get('role', 'user'),
                    'content': msg.get('content', ''),
                    'full_content': msg.get('content', ''),
                    'dialog_widget': dialog
                }
                ui_messages.append((message_id, message_info, dialog))

            print(f"[OK] 前端UI已加载 {len(ui_messages)} 条历史对话")
            return ui_messages

        except Exception as e:
            print(f"[FAIL] 前端加载持久化上下文失败: {e}")
            return []

    @staticmethod
    def update_message_content(dialog, new_content, html=None):
        """更新消息内容。html 非空时直接使用，不再走 Markdown。"""
        if hasattr(dialog, 'update_content'):
            dialog.update_content(new_content, html=html)
        elif hasattr(dialog, 'update_message'):
            dialog.update_message(new_content)

    @staticmethod
    def get_message_height(dialog):
        """获取消息对话框高度"""
        if hasattr(dialog, 'get_preferred_height'):
            return dialog.get_preferred_height()
        return dialog.sizeHint().height()
