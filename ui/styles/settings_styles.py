"""
设置界面样式配置文件
将设置界面的样式从主代码中解耦出来，统一管理
"""

import sys
from pathlib import Path

# 确保仓库根在 sys.path 上：本模块末尾要读 config.ui.font_family，
# 而 config 模块按 `core.system.config` 导入。
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 系统提示词卡片样式
SYSTEM_PROMPT_CARD_STYLE = """
QWidget {
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 10px;
    margin: 2px;
}
QWidget:hover {
    background: rgba(255, 255, 255, 15);
    border: 1px solid rgba(255, 255, 255, 40);
}
"""

# 系统提示词编辑器样式
SYSTEM_PROMPT_EDITOR_STYLE = """
QTextEdit {
    background: rgba(17,17,17,180);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 6px;
    padding: 8px 12px;
    font: 10pt 'Lucida Console';
    line-height: 1.4;
}
QTextEdit:focus {
    border: 1px solid rgba(100, 200, 255, 100);
}
"""

# 系统提示词标题样式
SYSTEM_PROMPT_TITLE_STYLE = """
QLabel {
    color: #fff;
    font: 12pt 'Lucida Console';
    font-weight: bold;
    background: transparent;
    border: none;
}
"""

# 系统提示词描述样式
SYSTEM_PROMPT_DESC_STYLE = """
QLabel {
    color: rgba(255, 255, 255, 120);
    font: 9pt 'Lucida Console';
    background: transparent;
    border: none;
}
"""

# 设置卡片样式
SETTING_CARD_STYLE = """
SettingCard {
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 10px;
    margin: 2px;
}
SettingCard:hover {
    background: rgba(255, 255, 255, 15);
    border: 1px solid rgba(255, 255, 255, 40);
}
"""

# 输入框样式
INPUT_STYLE = """
QLineEdit {
    background: rgba(17,17,17,180);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 6px;
    padding: 6px 10px;
    font: 10pt 'Lucida Console';
}
QLineEdit:focus {
    border: 1px solid rgba(100, 200, 255, 100);
}
"""

# 下拉框样式
COMBO_STYLE = """
QComboBox {
    background: rgba(17,17,17,180);
    color: #F0F2F7;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 6px;
    padding: 6px 10px;
    font: 10pt 'Lucida Console';
}
QComboBox:hover {
    border: 1px solid rgba(255, 255, 255, 80);
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 26px;
}
/* 下拉箭头：不用系统原生箭头 —— 它在深色底上呈暗色、几乎看不见，
   而 QSS 又无法像网页 CSS 那样用 border 画三角形，因此改用白色箭头图片。
   __ARROW__ 会在模块末尾替换为绝对路径（QSS 的相对 url 不可靠）。 */
QComboBox::down-arrow {
    image: url(__ARROW__);
    width: 12px;
    height: 12px;
    margin-right: 7px;
}
QComboBox::down-arrow:disabled {
    image: url(__ARROW_DIM__);
}
/* 下拉弹出的列表必须单独样式化。
   否则 QComboBox 上的浅色 color 会被列表项继承，而列表背景走系统默认
   （Windows 浅色主题下为白色）—— 结果是浅字浅底、文字几乎看不见。 */
QComboBox QAbstractItemView {
    background: rgba(30, 30, 30, 252);
    color: #F0F2F7;
    border: 1px solid rgba(255, 255, 255, 70);
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: rgba(100, 200, 255, 150);
    selection-color: #FFFFFF;
}
QComboBox QAbstractItemView::item {
    padding: 5px 8px;
    min-height: 22px;
    color: #F0F2F7;
}
QComboBox QAbstractItemView::item:hover {
    background: rgba(255, 255, 255, 0.14);
}
QComboBox QAbstractItemView::item:selected {
    background: rgba(100, 200, 255, 150);
    color: #FFFFFF;
}
"""

# 复选框样式
CHECKBOX_STYLE = """
QCheckBox {
    color: #fff;
    font: 10pt 'Lucida Console';
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 50);
    background: rgba(17,17,17,180);
}
QCheckBox::indicator:checked {
    background: rgba(100, 200, 255, 150);
    border: 1px solid rgba(100, 200, 255, 200);
}
"""

# 滑块样式
SLIDER_STYLE = """
QSlider::groove:horizontal {
    border: 1px solid rgba(255, 255, 255, 30);
    height: 6px;
    background: rgba(17,17,17,180);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: rgba(100, 200, 255, 150);
    border: 1px solid rgba(100, 200, 255, 200);
    width: 16px;
    border-radius: 8px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: rgba(120, 220, 255, 180);
}
"""

# 数字输入框样式
SPIN_STYLE = """
QSpinBox, QDoubleSpinBox {
    background: rgba(17,17,17,180);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 6px;
    padding: 6px 10px;
    font: 10pt 'Lucida Console';
}
QSpinBox:focus {
    border: 1px solid rgba(100, 200, 255, 100);
}
"""



# 滚动区域样式
SCROLL_AREA_STYLE = """
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: rgba(255, 255, 255, 20);
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 60);
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 80);
}
"""

# 状态标签样式
STATUS_LABEL_STYLE = """
QLabel {
    color: rgba(255, 255, 255, 120);
    font: 10pt 'Lucida Console';
    background: transparent;
    border: none;
}
"""

# 保存按钮样式
SAVE_BUTTON_STYLE = """
QPushButton {
    background: rgba(100, 200, 100, 150);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 8px;
    padding: 6px 12px;
    font: 11pt 'Lucida Console';
    font-weight: bold;
}
QPushButton:hover {
    border: 1px solid rgba(255, 255, 255, 80);
    background: rgba(120, 220, 120, 180);
}
QPushButton:pressed {
    background: rgba(80, 180, 80, 200);
}
"""

# 重置按钮样式
RESET_BUTTON_STYLE = """
QPushButton {
    background: rgba(100, 100, 100, 150);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 8px;
    padding: 6px 12px;
    font: 11pt 'Lucida Console';
}
QPushButton:hover {
    border: 1px solid rgba(255, 255, 255, 80);
    background: rgba(120, 120, 120, 180);
}
QPushButton:pressed {
    background: rgba(80, 80, 80, 200);
}
"""

# 设置卡片样式
SETTING_CARD_BASE_STYLE = """
SettingCard {
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 10px;
    margin: 2px;
}
SettingCard:hover {
    background: rgba(255, 255, 255, 15);
    border: 1px solid rgba(255, 255, 255, 40);
}
"""

# 设置卡片标题样式
SETTING_CARD_TITLE_STYLE = """
QLabel {
    color: #fff;
    font: 12pt 'Lucida Console';
    font-weight: bold;
    background: transparent;
    border: none;
}
"""

# 设置卡片描述样式
SETTING_CARD_DESC_STYLE = """
QLabel {
    color: rgba(255, 255, 255, 120);
    font: 9pt 'Lucida Console';
    background: transparent;
    border: none;
}
"""

# 设置组头部容器样式
SETTING_GROUP_HEADER_CONTAINER_STYLE = """
QWidget {
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 30);
    margin-bottom: 2px;
}
"""

# 设置组头部按钮样式
SETTING_GROUP_HEADER_BUTTON_STYLE = """
QPushButton {
    color: #fff;
    font: 16pt 'Lucida Console';
    font-weight: bold;
    background: transparent;
    border: none;
    padding: 10px 0;
    text-align: left;
}
QPushButton:hover {
    color: #e8f6ff;
}
"""

# 设置组右侧标签样式
SETTING_GROUP_RIGHT_LABEL_STYLE = """
QLabel {
    color: rgba(255,255,255,180);
    font: 10pt 'Lucida Console';
    background: transparent;
}
"""

# 滚动内容样式
SCROLL_CONTENT_STYLE = """
QWidget {
    background: transparent;
}
"""


# 语音模式禁用状态样式
VOICE_MODE_DISABLED_STYLE = """
QComboBox:disabled {
    background: rgba(50, 50, 50, 150);
    color: rgba(255, 255, 255, 100);
}
"""

# 测试窗口样式
TEST_WINDOW_STYLE = """
QWidget {
    background: rgba(25, 25, 25, 220);
    color: white;
}
"""

# 标签样式
LABEL_STYLE = """
QLabel {
    color: #fff;
    font: 10pt 'Lucida Console';
}
"""

# 对话框标题样式
DIALOG_HEADER_TITLE_STYLE = """
QLabel {
    color: #fff;
    font: 14pt 'Lucida Console';
    font-weight: bold;
    background: transparent;
    border: none;
}
"""

# 对话框提示文本样式
DIALOG_HINT_LABEL_STYLE = """
QLabel {
    color: rgba(255, 255, 255, 160);
    font: 10pt 'Lucida Console';
    background: transparent;
    border: none;
}
"""

# 对话框 Tab 样式
DIALOG_TAB_BAR_STYLE = """
QTabWidget::pane {
    background: transparent;
    border: none;
}
QTabBar::tab {
    background: rgba(255, 255, 255, 8);
    color: rgba(255, 255, 255, 180);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 18px;
    padding: 8px 22px;
    font: 11pt 'Lucida Console';
    margin: 0px 6px;
}
QTabBar::tab:selected {
    background: rgba(100, 200, 255, 120);
    color: #fff;
    border: 1px solid rgba(120, 220, 255, 200);
}
QTabBar::tab:hover {
    background: rgba(255, 255, 255, 18);
    color: #fff;
}
"""

# 对话框搜索容器样式
DIALOG_SEARCH_CONTAINER_STYLE = """
QWidget#Live2DSearchContainer {
    background: rgba(255, 255, 255, 6);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 24px;
    padding: 4px 12px;
}
"""

# 动作卡片样式
ACTION_CARD_WIDGET_STYLE = """
QWidget#Live2DActionCard {
    background: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 16px;
    padding: 10px;
}
QWidget#Live2DActionCard:hover {
    background: rgba(255, 255, 255, 18);
    border: 1px solid rgba(120, 220, 255, 160);
}
QWidget#Live2DActionCard[selected="true"] {
    background: rgba(120, 220, 255, 80);
    border: 1px solid rgba(120, 220, 255, 220);
}
QWidget#Live2DActionCard QLabel {
    color: #fff;
}
QLabel#Live2DActionIcon {
    font: 26pt 'Segoe UI Emoji';
}
QLabel#Live2DActionName {
    font: 10pt 'Lucida Console';
    font-weight: bold;
}
QLabel#Live2DActionType {
    color: rgba(200, 230, 255, 220);
    font: 9pt 'Lucida Console';
}
"""


# ---------------------------------------------------------------------------
# 字体族统一为配置值
#
# 本文件原先有 21 处硬编码 'Lucida Console'。它是纯西文等宽字体、**不含中文字形**，
# 设置页里的中文只能走系统回退字体，导致同一行里中英文观感不一致。
# 这里在模块加载时统一替换为 config.ui.font_family（默认 Microsoft YaHei）。
#
# 只替换字体族、不动各自字号 —— 各元素的字号本就有意区分层级（9/10/11/12/16pt）。
# ---------------------------------------------------------------------------
def _resolve_font_family() -> str:
    try:
        from core.system.config import config as _cfg

        fam = (getattr(_cfg.ui, "font_family", "") or "").strip()
        return fam or "Microsoft YaHei"
    except Exception:
        return "Microsoft YaHei"


FONT_FAMILY = _resolve_font_family()

for _name in [n for n in list(globals()) if n.isupper()]:
    _val = globals().get(_name)
    if isinstance(_val, str) and "Lucida Console" in _val:
        globals()[_name] = _val.replace("Lucida Console", FONT_FAMILY)

del _name, _val


# ---------------------------------------------------------------------------
# 下拉箭头图片路径
#
# QSS 的 url() 相对路径以**当前工作目录**为基准，而本项目的进程 cwd 不保证是
# 仓库根（此前已修过几处同类问题），因此这里用绝对路径。
# 图片由 scripts/gen_ui_icons.py 生成，可复现。
# ---------------------------------------------------------------------------
def _icon_url(filename: str) -> str:
    try:
        root = Path(__file__).resolve().parent.parent.parent
        p = root / "ui" / "img" / "icons" / filename
        if p.is_file():
            return p.as_posix()
        # 找不到就退回一个不存在的占位，Qt 会忽略该 image 声明而不是报错
        return p.as_posix()
    except Exception:
        return ""


_ARROW_WHITE = _icon_url("combo_arrow_white.png")
_ARROW_DIM = _icon_url("combo_arrow_dim.png")

if "__ARROW__" in COMBO_STYLE:
    COMBO_STYLE = (COMBO_STYLE
                   .replace("__ARROW_DIM__", _ARROW_DIM)
                   .replace("__ARROW__", _ARROW_WHITE))
