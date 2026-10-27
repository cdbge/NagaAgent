#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按主题生成界面 QSS。

为什么单独一个模块
==================

原先把样式写成 `settings_styles.py` 里的 95 处硬编码色值常量，
换主题时一整套界面不跟着变（纸色主题下出现深色卡片、深色弹窗）。
这里把"样式"改成"函数"：入参是主题实例，出参是 QSS 字符串。

约定
====

* **直角优先**：莱茵（纸）`radius_*` 是 0~2，少前是 2~4，深空才是 20。
  这里全部用 `t.radius_*`，不写死数字。
* **浅色主题不叠透明度**：纸色叠 alpha 会发灰。
* **强调色只用于一个层级**：主按钮/选中态/标题，其它用 `text_mute`。
"""

from __future__ import annotations

__all__ = [
    "dialog_style",
    "label_style",
    "title_style",
    "hint_style",
    "card_style",
    "card_title_style",
    "input_style",
    "combo_style",
    "button_primary",
    "button_secondary",
    "scrollbar_style",
    "scroll_area_style",
    "tab_bar_style",
    "action_card_style",
    "search_container_style",
    "group_header_style",
    "spin_style",
    "checkbox_style",
    "slider_style",
]


#: 三角形图标缓存：{颜色: 文件路径}
_ARROW_CACHE = {}
_ARROW_DIR = None


def _arrow_png(color: str, direction: str = "down", size: int = 10) -> str:
    """生成（并缓存）一枚实心三角 PNG，返回绝对路径。

    Args:
        color: `#RRGGBB`
        direction: "down" / "up"
        size: 三角宽（像素），高约为宽的一半

    QSS 里 `image: url(path)` 需要真实文件；Qt 无法用纯 CSS 画出
    `QComboBox::down-arrow` 的箭头。
    """
    global _ARROW_DIR
    key = f"{color}-{direction}-{size}"
    if key in _ARROW_CACHE:
        return _ARROW_CACHE[key]
    try:
        import tempfile

        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QImage, QPainter, QPolygon
        from PyQt5.QtCore import QPoint

        if _ARROW_DIR is None:
            _ARROW_DIR = tempfile.mkdtemp(prefix="naga_arrows_")

        w, h = size, max(4, size // 2)
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        if direction == "down":
            poly = QPolygon([QPoint(0, 0), QPoint(w, 0), QPoint(w // 2, h)])
        else:
            poly = QPolygon([QPoint(0, h), QPoint(w, h), QPoint(w // 2, 0)])
        p.drawPolygon(poly)
        p.end()

        _safe_key = key.replace("#", "")
        path = f"{_ARROW_DIR}/arrow_{_safe_key}.png".replace("\\", "/")
        img.save(path, "PNG")
        _ARROW_CACHE[key] = path
        return path
    except Exception:
        return ""


def _mono(t, size: float = 8) -> str:
    return f"font-family: {t.font_mono or 'Consolas'}; font-size: {size}pt;"


def _cn(t, size: float = 10, weight: int = 400) -> str:
    return (f"font-family: {t.font_cn or 'Microsoft YaHei UI'}; "
            f"font-size: {size}pt; font-weight: {weight};")


# ---------------------------------------------------------------- 弹窗/页面
def dialog_style(t) -> str:
    """对话框主体：底色 + 描边 + 圆角。"""
    bg = t.panel if t.is_light else f"rgba({_rgb(t.panel)}, 0.96)"
    return f"""
    QDialog {{
        background: {bg};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_lg}px;
    }}
    QWidget {{
        color: {t.text};
    }}
    """


def label_style(t) -> str:
    return f"""
    QLabel {{
        color: {t.text};
        {_cn(t, 10)}
        background: transparent;
    }}
    """


def title_style(t) -> str:
    """区块标题：大字距 + 强调色。"""
    return f"""
    QLabel {{
        color: {t.accent};
        {_cn(t, 12, 600)}
        letter-spacing: {t.label_tracking};
        background: transparent;
    }}
    """


def hint_style(t) -> str:
    """说明文字：弱化色 + 等宽（档案感）。"""
    return f"""
    QLabel {{
        color: {t.text_mute};
        {_mono(t, 8)}
        background: transparent;
    }}
    """


# ---------------------------------------------------------------- 卡片
def card_style(t) -> str:
    """设置分组卡片。"""
    bg = t.panel_2 if t.is_light else t.panel
    return f"""
    QFrame#SettingCard {{
        background: {bg};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_md}px;
    }}
    QFrame#SettingCard:hover {{
        border: {t.border_width}px solid {t.accent};
    }}
    """


def group_header_style(t) -> str:
    """分组标题行：编号 + 名称 + 展开箭头。"""
    return f"""
    QPushButton#GroupHeader {{
        color: {t.text};
        {_cn(t, 11, 600)}
        background: transparent;
        border: none;
        border-bottom: {t.border_width}px solid {t.divider};
        text-align: left;
        padding: 8px 2px;
    }}
    QPushButton#GroupHeader:hover {{
        color: {t.accent};
    }}
    """


def card_title_style(t) -> str:
    return f"""
    QLabel {{
        color: {t.text};
        {_cn(t, 10, 600)}
        background: transparent;
    }}
    """


# ---------------------------------------------------------------- 输入控件
def input_style(t) -> str:
    bg = t.panel_3 if t.is_light else t.panel_2
    return f"""
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background: {bg};
        color: {t.text};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 5px 8px;
        selection-background-color: {t.accent};
        selection-color: {t.text_inv};
        {_cn(t, 9)}
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: {t.border_width}px solid {t.accent};
    }}
    """


def combo_style(t) -> str:
    bg = t.panel_3 if t.is_light else t.panel_2
    down = _arrow_png(t.text_dim, "down")
    return f"""
    QComboBox {{
        background: {bg};
        color: {t.text};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 4px 8px;
        {_cn(t, 9)}
    }}
    QComboBox:hover {{
        border: {t.border_width}px solid {t.accent};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: url("{down}");
        width: 10px;
        height: 5px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {t.panel};
        color: {t.text};
        border: {t.border_width}px solid {t.border};
        selection-background-color: {t.accent};
        selection-color: {t.text_inv};
        outline: none;
    }}
    """


# ---------------------------------------------------------------- 按钮
def button_primary(t) -> str:
    return f"""
    QPushButton {{
        background: {t.accent};
        color: {t.text_inv};
        border: none;
        border-radius: {t.radius_sm}px;
        padding: 6px 16px;
        {_cn(t, 9, 600)}
    }}
    QPushButton:hover {{
        background: {t.accent_deep};
    }}
    QPushButton:pressed {{
        background: {t.accent_deep};
    }}
    QPushButton:disabled {{
        background: {t.panel_2};
        color: {t.text_mute};
    }}
    """


def button_secondary(t) -> str:
    return f"""
    QPushButton {{
        background: transparent;
        color: {t.text_dim};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 6px 16px;
        {_cn(t, 9)}
    }}
    QPushButton:hover {{
        color: {t.accent};
        border: {t.border_width}px solid {t.accent};
    }}
    """


# ---------------------------------------------------------------- 滚动/标签
def scrollbar_style(t) -> str:
    return f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
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
        height: 0; border: none; background: transparent;
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
    """


def scroll_area_style(t) -> str:
    return f"""
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    {scrollbar_style(t)}
    """


def tab_bar_style(t) -> str:
    return f"""
    QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t.text_mute};
        border: none;
        border-bottom: 1px solid transparent;
        padding: 6px 14px;
        {_cn(t, 9)}
    }}
    QTabBar::tab:hover {{
        color: {t.text};
    }}
    QTabBar::tab:selected {{
        color: {t.accent};
        border-bottom: 1px solid {t.accent};
        font-weight: 600;
    }}
    """


def action_card_style(t) -> str:
    """Live2D 动作/表情选择卡。"""
    bg = t.panel_2 if t.is_light else t.panel
    return f"""
    QWidget#ActionCard {{
        background: {bg};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_md}px;
    }}
    QWidget#ActionCard:hover {{
        border: {t.border_width}px solid {t.accent};
    }}
    QWidget#ActionCard[selected="true"] {{
        background: {t.accent_soft};
        border: {t.border_width}px solid {t.accent};
    }}
    """


def search_container_style(t) -> str:
    bg = t.panel_2 if t.is_light else t.panel
    return f"""
    QWidget#SearchBar {{
        background: {bg};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_sm}px;
    }}
    """


# ---------------------------------------------------------------- 内部工具
def _rgb(hex_color: str) -> str:
    """`#RRGGBB` -> `r, g, b`（供 rgba() 使用）。"""
    try:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"
    except Exception:
        return "20, 20, 20"


# ---------------------------------------------------------------- 数值/开关
def spin_style(t) -> str:
    """数值输入框。

    上下箭头交回 Qt 默认绘制 —— 之前用 `image: none` + border 三角形
    拼箭头，在不同平台上会渲染成实心方块或干脆不显示。
    """
    bg = t.panel_3 if t.is_light else t.panel_2
    btn = t.panel_2 if t.is_light else t.panel_3
    up = _arrow_png(t.text_dim, "up")
    down = _arrow_png(t.text_dim, "down")
    return f"""
    QSpinBox, QDoubleSpinBox {{
        background: {bg};
        color: {t.text};
        border: {t.border_width}px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 4px 8px;
        {_cn(t, 9)}
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: {t.border_width}px solid {t.accent};
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url("{up}"); width: 8px; height: 4px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url("{down}"); width: 8px; height: 4px;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        background: {btn};
        border: none;
        width: 16px;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {t.accent};
    }}
    """

def checkbox_style(t) -> str:
    """勾选框：方块描边，选中填强调色。"""
    bg = t.panel_3 if t.is_light else t.panel_2
    return f"""
    QCheckBox {{
        color: {t.text};
        {_cn(t, 9)}
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: {t.border_width}px solid {t.border};
        border-radius: {max(0, t.radius_sm - 1)}px;
        background: {bg};
    }}
    QCheckBox::indicator:hover {{
        border: {t.border_width}px solid {t.accent};
    }}
    QCheckBox::indicator:checked {{
        background: {t.accent};
        border: {t.border_width}px solid {t.accent};
    }}
    """


def slider_style(t) -> str:
    """滑杆：细轨 + 强调色填充段 + 2:1 矩形手柄。

    手柄用 20x10 的矩形（宽:高 = 2:1）—— 原来的 10x10 圆角方块
    在小尺寸下几乎点不到，也不容易看清当前位置。
    """
    return f"""
    QSlider::groove:horizontal {{
        height: 4px;
        background: {t.border};
        border-radius: 0px;
    }}
    QSlider::sub-page:horizontal {{
        background: {t.accent};
        height: 4px;
    }}
    QSlider::handle:horizontal {{
        background: {t.accent};
        width: 40px;
        height: 20px;
        margin: -9px 0;
        border-radius: 0px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {t.accent_deep};
    }}
    QSlider::handle:horizontal:pressed {{
        background: {t.accent_deep};
    }}
    """
