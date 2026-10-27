#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置行控件：把 Field 规格渲染成一行可交互控件。

一个 SettingRow = 左侧（标题 + 说明）+ 右侧（固定 420px 列宽的具体控件）。
样式全部取自主题令牌，换肤无需改这里。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui.styles.tokens import font_stack, get_theme

from .spec import Field

logger = logging.getLogger(__name__)

__all__ = ["SettingRow"]


class SettingRow(QWidget):
    """一行设置。"""

    #: 用户改了值（key, value）
    changed = pyqtSignal(str, object)

    #: 右侧控件列宽（全页统一，保证左右边缘对齐）
    CONTROL_WIDTH = 420
    #: 行高
    ROW_HEIGHT = 84

    def __init__(self, field: Field, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.field = field
        self._control = None
        self._loading = False
        self.setObjectName("SettingRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(self.ROW_HEIGHT)
        self._build()
        self.apply_theme_style()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(16)

        # 左：标题 + 说明
        # 上下各留一个 stretch，让两行文字在行高内**垂直居中** ——
        # 原来只有尾部 stretch，文字被顶到上边缘，和右侧控件不齐。
        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self.title_label = QLabel(self.field.label)
        self.desc_label = QLabel(self.field.desc)
        self.desc_label.setWordWrap(True)
        text_box.addStretch(1)
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.desc_label)
        text_box.addStretch(1)
        row.addLayout(text_box, 1)

        # 右：控件
        control_box = QWidget()
        control_box.setFixedWidth(self.CONTROL_WIDTH)
        control_lay = QHBoxLayout(control_box)
        control_lay.setContentsMargins(0, 0, 0, 0)
        control_lay.setSpacing(0)

        self._control = self._make_control()
        if self.field.kind == "toggle":
            control_lay.addStretch(1)
            control_lay.addWidget(self._control)
        else:
            control_lay.addWidget(self._control, 1)
        row.addWidget(control_box)

    def _make_control(self) -> QWidget:
        f = self.field
        if f.kind in ("text", "secret"):
            w = QLineEdit()
            if f.placeholder:
                w.setPlaceholderText(f.placeholder)
            if f.kind == "secret":
                w.setEchoMode(QLineEdit.Password)
            w.textChanged.connect(self._emit_text)
            return w

        if f.kind == "toggle":
            w = QCheckBox()
            w.setCursor(Qt.PointingHandCursor)
            w.toggled.connect(self._emit_bool)
            return w

        if f.kind == "slider":
            w = _SliderBox(f)
            w.changed.connect(self._emit_value)
            return w

        if f.kind == "select":
            w = QComboBox()
            w.setCursor(Qt.PointingHandCursor)
            if f.editable:
                w.setEditable(True)
            for label, value in f.resolve_options():
                w.addItem(str(label), value)
            w.currentIndexChanged.connect(self._emit_combo)
            return w

        # 未知类型兜底成文本框
        w = QLineEdit()
        w.textChanged.connect(self._emit_text)
        return w

    # ------------------------------------------------------------ 值读写
    def value(self) -> Any:
        f = self.field
        if f.kind in ("text", "secret"):
            return self._control.text()
        if f.kind == "toggle":
            return self._control.isChecked()
        if f.kind == "slider":
            return self._control.value()
        if f.kind == "select":
            data = self._control.currentData()
            return data if data is not None else self._control.currentText()
        return None

    def setValue(self, value: Any) -> None:
        """程序化回填（不触发 changed）。"""
        self._loading = True
        try:
            f = self.field
            if f.kind in ("text", "secret"):
                self._control.setText(str(value if value is not None else ""))
            elif f.kind == "toggle":
                self._control.setChecked(bool(value))
            elif f.kind == "slider":
                self._control.setValue(float(value or 0))
            elif f.kind == "select":
                idx = self._control.findData(value)
                if idx < 0:
                    for i in range(self._control.count()):
                        if str(self._control.itemData(i)) == str(value):
                            idx = i
                            break
                if idx >= 0:
                    self._control.setCurrentIndex(idx)
                elif f.editable:
                    self._control.setCurrentText(str(value))
        finally:
            self._loading = False

    # ------------------------------------------------------------ 信号
    def _emit_text(self, text):
        if not self._loading:
            self.changed.emit(self.field.key, text)

    def _emit_bool(self, checked):
        if not self._loading:
            self.changed.emit(self.field.key, checked)

    def _emit_value(self, value):
        if not self._loading:
            self.changed.emit(self.field.key, value)

    def _emit_combo(self, _index):
        if not self._loading:
            self.changed.emit(self.field.key, self.value())

    # ------------------------------------------------------------ 样式
    def apply_theme_style(self) -> None:
        t = get_theme()
        bg = t.panel_2 if t.is_light else t.panel
        self.setStyleSheet(
            "QWidget#SettingRow {"
            f"  background: {bg};"
            f"  border: {t.border_width}px solid {t.border};"
            "  border-radius: 0px;"
            "}"
        )
        self.title_label.setStyleSheet(
            f"color: {t.text}; background: transparent;"
            f"font-family: {t.font_cn}; font-size: 10.5pt; font-weight: 600;"
        )
        self.desc_label.setStyleSheet(
            f"color: {t.text_mute}; background: transparent;"
            f"font-family: {t.font_cn}; font-size: 8.5pt;"
        )

        c = self._control
        if isinstance(c, QLineEdit):
            c.setStyleSheet(
                "QLineEdit {"
                f"  background: {(t.panel_3 if t.is_light else t.panel_2)};"
                f"  color: {t.text};"
                f"  border: {t.border_width}px solid {t.border};"
                f"  border-radius: {t.radius_sm}px;"
                "  padding: 8px 10px;"
                f"  font-family: {t.font_cn}; font-size: 9.5pt;"
                "}"
                f"QLineEdit:focus {{ border: {t.border_width}px solid {t.accent}; }}"
            )
        elif isinstance(c, QComboBox):
            c.setStyleSheet(_combo_qss(t))
        elif isinstance(c, QCheckBox):
            c.setStyleSheet(_check_qss(t))
        elif isinstance(c, _SliderBox):
            c.apply_theme_style()


# ------------------------------------------------------------------ 滑块组
class _SliderBox(QWidget):
    """滑块 + 数值标签。"""

    changed = pyqtSignal(object)

    def __init__(self, field: Field):
        super().__init__()
        self._field = field
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(field.minimum), int(field.maximum))
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (int(field.maximum) - int(field.minimum)) // 10))
        self.slider.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.slider, 1)

        self.value_label = QLabel()
        self.value_label.setFixedWidth(72)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.value_label)

        self.slider.valueChanged.connect(self._on_slider)
        self._render()

    def value(self):
        f = self._field
        v = self.slider.value() * f.scale
        return round(v, f.decimals) if f.decimals else int(round(v))

    def setValue(self, v):
        try:
            self.slider.setValue(int(round(float(v) / (self._field.scale or 1))))
        except Exception:
            pass

    def _on_slider(self, _v):
        self._render()
        self.changed.emit(self.value())

    def _render(self):
        f = self._field
        v = self.value()
        text = f"{v:.{f.decimals}f}" if f.decimals else f"{v}"
        self.value_label.setText(text + f.suffix)

    def apply_theme_style(self):
        t = get_theme()
        self.value_label.setStyleSheet(
            f"color: {t.accent}; background: transparent;"
            f"font-family: {t.font_mono}; font-size: 9pt; font-weight: 700;"
        )
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            "  height: 4px;"
            f"  background: {t.border};"
            "  border: none; border-radius: 0px;"
            "}"
            "QSlider::sub-page:horizontal {"
            f"  background: {t.accent}; height: 4px; border-radius: 0px;"
            "}"
            "QSlider::handle:horizontal {"
            f"  background: {t.accent};"
            "  width: 40px; height: 20px;"
            "  margin: -8px 0; border: none; border-radius: 0px;"
            "}"
            "QSlider::handle:horizontal:hover,"
            "QSlider::handle:horizontal:pressed {"
            f"  background: {t.accent_deep};"
            "}"
        )


# ------------------------------------------------------------------ QSS 片段
def _combo_qss(t) -> str:
    bg = t.panel_3 if t.is_light else t.panel_2
    # 下拉箭头必须用真实图片：QSS 的 border 三角技巧在
    # QComboBox::down-arrow 上不生效（本项目已踩过一次）。
    # 这里复用 themed_qss 里的运行期三角 PNG 生成器。
    try:
        from ui.styles.themed_qss import _arrow_png

        arrow = _arrow_png(t.text_dim, "down").replace("\\", "/")
    except Exception:
        arrow = ""

    arrow_rule = (
        "QComboBox::down-arrow {"
        f"  image: url(\"{arrow}\");"
        "  width: 10px; height: 6px;"
        "}"
    ) if arrow else ""

    return (
        "QComboBox {"
        f"  background: {bg};"
        f"  color: {t.text};"
        f"  border: {t.border_width}px solid {t.border};"
        f"  border-radius: {t.radius_sm}px;"
        "  padding: 8px 30px 8px 10px;"
        f"  font-family: {t.font_cn}; font-size: 9.5pt;"
        "}"
        f"QComboBox:hover {{ border: {t.border_width}px solid {t.accent}; }}"
        "QComboBox::drop-down {"
        "  subcontrol-origin: padding;"
        "  subcontrol-position: center right;"
        "  width: 24px;"
        "  border: none;"
        "  background: transparent;"
        "}"
        + arrow_rule +
        "QComboBox QAbstractItemView {"
        f"  background: {t.panel}; color: {t.text};"
        f"  border: {t.border_width}px solid {t.border};"
        f"  selection-background-color: {t.accent};"
        f"  selection-color: {t.text_inv};"
        "  outline: none;"
        "}"
    )

def _check_qss(t) -> str:
    bg = t.panel_3 if t.is_light else t.panel_2
    return (
        "QCheckBox { background: transparent; spacing: 8px; }"
        "QCheckBox::indicator {"
        "  width: 18px; height: 18px;"
        f"  border: {t.border_width}px solid {t.border};"
        "  border-radius: 0px;"
        f"  background: {bg};"
        "}"
        f"QCheckBox::indicator:hover {{ border: {t.border_width}px solid {t.accent}; }}"
        "QCheckBox::indicator:checked {"
        f"  background: {t.accent};"
        f"  border: {t.border_width}px solid {t.accent};"
        "}"
    )
