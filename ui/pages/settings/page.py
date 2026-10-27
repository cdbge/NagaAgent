#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置页：左侧类别导航 + 右侧设置行的双栏页面。

**完全声明式** —— 页面对具体设置项一无所知，只认 `SECTIONS` 里的 Field。
加设置只需改 schema.py。

生效策略（参考通用做法：live preview + debounced persist）
=========================================================

* 改值 → 立刻写入内存 config + 节流 16ms 刷新界面（拖动平滑）
* 停手 500ms → 写 config.json + 完整刷新

写盘后会把本次改动重新压回内存，避免配置重载读到旧值导致"回弹"。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.styles.tokens import font_stack, get_theme, get_theme_key

from .schema import SECTIONS
from .spec import Field
from .widgets import SettingRow

logger = logging.getLogger(__name__)

__all__ = ["SettingsPage"]


class _NavButton(QPushButton):
    """左侧类别按钮（带轻微缩放动效）。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._scale = 1.0
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)

    def getScale(self):
        return self._scale

    def setScale(self, v):
        self._scale = float(v)
        f = self.font()
        f.setPointSizeF(12.0 * self._scale)
        self.setFont(f)

    scale = pyqtProperty(float, fget=getScale, fset=setScale)


class SettingsPage(QWidget):
    """设置页。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._rows: Dict[str, SettingRow] = {}
        self._pending: Dict[str, object] = {}
        self._nav_buttons: List[_NavButton] = []
        self._pages: List[QWidget] = []
        self._active = 0

        self._build()
        self.load_values()
        self.apply_theme_style()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 左侧导航 ----------
        self.nav = QWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setAttribute(Qt.WA_StyledBackground, True)
        self.nav.setFixedWidth(268)
        nav_lay = QVBoxLayout(self.nav)
        nav_lay.setContentsMargins(24, 24, 14, 24)
        nav_lay.setSpacing(4)

        self.stack = QStackedWidget()
        for sec in SECTIONS:
            page = self._make_section_page(sec)
            self._pages.append(page)
            self.stack.addWidget(page)

            btn = _NavButton(f"{sec.number:02d}  {sec.title}")
            btn.clicked.connect(lambda _c=False, i=len(self._nav_buttons): self.select(i))
            self._nav_buttons.append(btn)
            nav_lay.addWidget(btn)

        nav_lay.addStretch(1)
        root.addWidget(self.nav, 0)

        # 跟随类别的滑动竖条（新版遗漏了，补回来）
        try:
            from ui.components.archive.indicator import SlidingIndicator

            self._nav_indicator = SlidingIndicator(self.nav, horizontal=False)
        except Exception:
            self._nav_indicator = None

        # ---------- 右侧内容 ----------
        right = QWidget()
        right.setObjectName("SettingsDetail")
        right.setAttribute(Qt.WA_StyledBackground, True)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("SettingsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)

        holder = QWidget()
        holder.setObjectName("SettingsScrollHolder")
        holder.setAttribute(Qt.WA_StyledBackground, True)
        holder_lay = QVBoxLayout(holder)
        holder_lay.setContentsMargins(0, 0, 0, 0)
        holder_lay.setSpacing(0)
        holder_lay.addWidget(self.stack)
        self.scroll.setWidget(holder)
        right_lay.addWidget(self.scroll, 1)

        # 底部：恢复默认
        bottom = QHBoxLayout()
        bottom.setContentsMargins(32, 10, 32, 16)
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label)
        bottom.addStretch(1)
        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setFixedSize(112, 36)
        self.reset_btn.clicked.connect(self.reset_defaults)
        bottom.addWidget(self.reset_btn)
        right_lay.addLayout(bottom)

        root.addWidget(right, 1)
        self.select(0)

    def _make_section_page(self, section) -> QWidget:
        page = QWidget()
        page.setObjectName("SettingsSectionPage")
        page.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(10)

        head = QLabel(f"{section.number:02d}  {section.title}")
        head.setObjectName("SettingsSectionTitle")
        lay.addWidget(head)

        hint = QLabel("SETTINGS / " + section.title)
        hint.setObjectName("SettingsSectionHint")
        lay.addWidget(hint)

        inner = QWidget()
        inner.setMaximumWidth(980)
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 8, 0, 0)
        inner_lay.setSpacing(6)

        for fld in section.fields:
            row = SettingRow(fld, inner)
            row.changed.connect(self._on_row_changed)
            self._rows[fld.key] = row
            inner_lay.addWidget(row)

        inner_lay.addStretch(1)
        lay.addWidget(inner, 0)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ 导航
    def select(self, index: int) -> None:
        if not self._pages:
            return
        index = max(0, min(index, len(self._pages) - 1))
        self._active = index
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
            self._style_nav_button(btn, i == index)
            # 轻微缩放
            try:
                from PyQt5.QtCore import QEasingCurve, QPropertyAnimation

                anim = QPropertyAnimation(btn, b"scale", btn)
                anim.setDuration(180)
                anim.setStartValue(getattr(btn, "_scale", 1.0))
                anim.setEndValue(1.06 if i == index else 1.0)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                anim.start()
                btn._anim = anim
            except Exception:
                pass
        # 竖条滑到当前类别
        def _sync_indicator():
            try:
                ind = getattr(self, "_nav_indicator", None)
                if ind is None or not (0 <= index < len(self._nav_buttons)):
                    return
                rect = ind.bar_rect_for(self._nav_buttons[index])
                if rect.isNull():
                    return
                ind.animate_to(rect)
            except Exception:
                pass

        QTimer.singleShot(0, _sync_indicator)

        try:
            self.scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass

    # ------------------------------------------------------------ 取值
    def load_values(self) -> None:
        """按 config 回填所有控件。"""
        try:
            from core.system.config import config
        except Exception:
            return
        for key, row in self._rows.items():
            group, _, name = key.partition(".")
            section = getattr(config, group, None)
            if section is None:
                continue
            row.setValue(getattr(section, name, None))

    # ------------------------------------------------------------ 变更
    def _on_row_changed(self, key: str, value) -> None:
        # 写入前按声明范围钳制，避免非法值污染整份 config
        value = self._clamp(key, value)
        self._pending[key] = value
        self._set_config_value(key, value)
        self._schedule_preview()
        self._schedule_persist()
        if hasattr(self, "status_label"):
            self.status_label.setText(f"● {key} 已应用")

    def _clamp(self, key: str, value):
        """按 Field 声明把值限制在合法范围，并做类型归一。"""
        try:
            row = self._rows.get(key)
            f = getattr(row, "field", None)
            if f is None:
                return value
            if f.kind == "slider":
                lo = float(f.minimum) * f.scale
                hi = float(f.maximum) * f.scale
                v = max(lo, min(hi, float(value)))
                return round(v, f.decimals) if f.decimals else int(round(v))
            if f.kind == "toggle":
                return bool(value)
            return value
        except Exception:
            return value
    @staticmethod
    def _set_config_value(key: str, value) -> None:
        try:
            from core.system.config import config

            group, _, name = key.partition(".")
            section = getattr(config, group, None)
            if section is not None:
                setattr(section, name, value)
        except Exception as exc:
            logger.debug(f"[设置] 内存赋值失败: {exc}")

    def _schedule_preview(self) -> None:
        if not hasattr(self, "_preview_timer"):
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.timeout.connect(self._refresh_preview)
        if not self._preview_timer.isActive():
            self._preview_timer.start(16)

    def _schedule_persist(self) -> None:
        if not hasattr(self, "_persist_timer"):
            self._persist_timer = QTimer(self)
            self._persist_timer.setSingleShot(True)
            self._persist_timer.timeout.connect(self._persist)
        self._persist_timer.start(500)

    def _refresh_preview(self) -> None:
        """拖动中的即时预览：只做最便宜的那部分。

        参考设置面板的通用做法 —— 拖动过程只反馈**可见且廉价**的属性
        （窗口底、侧栏、输入区），重活（全窗口 QSS 重建、所有消息气泡重绘）
        留到松手后的 `_persist`。之前这里每 16ms 调一次 `apply_ui_style`，
        实测 170ms/次，比刷新间隔还长，所以越拖越卡。
        """
        try:
            win = self.window()
            if win is None:
                return
            if hasattr(win, "apply_alpha_only"):
                win.apply_alpha_only(full=False)
        except Exception as exc:
            logger.debug(f"[设置] 预览刷新失败: {exc}")

    def _persist(self) -> None:
        if not self._pending:
            return
        changes = dict(self._pending)
        self._pending.clear()

        nested: Dict[str, Dict[str, object]] = {}
        for k, v in changes.items():
            group, _, name = k.partition(".")
            if name:
                nested.setdefault(group, {})[name] = v

        try:
            from core.system.config_manager import update_config

            update_config(nested)
            # 重载可能读到落盘前的旧文件，把本次改动再压回内存
            for k, v in changes.items():
                self._set_config_value(k, v)
        except Exception as exc:
            logger.debug(f"[设置] 写盘失败: {exc}")

        try:
            win = self.window()
            if win is not None and hasattr(win, "apply_ui_style"):
                win.apply_ui_style()
        except Exception as exc:
            logger.debug(f"[设置] 完整刷新失败: {exc}")

        # 控件按最终值回填，避免重载期间被旧值覆盖
        self.load_values()
        if hasattr(self, "status_label"):
            self.status_label.setText("● 已保存并生效")

    # ------------------------------------------------------------ 重置
    def reset_defaults(self) -> None:
        """恢复默认值。"""
        try:
            from core.system.config import UIConfig

            d = UIConfig()
            mapping = {
                "ui.user_name": d.user_name,
                "ui.window_bg_alpha": d.window_bg_alpha,
                "ui.animation_duration": d.animation_duration,
                "ui.font_size": d.font_size,
                "ui.font_family": d.font_family,
                "ui.theme": "gfl",
            }
            for key, value in mapping.items():
                row = self._rows.get(key)
                if row is not None:
                    row.setValue(value)
                self._set_config_value(key, value)
                self._pending[key] = value
            self._persist()
            self.status_label.setText("● 已恢复默认外观")
        except Exception as exc:
            logger.debug(f"[设置] 恢复默认失败: {exc}")

    # ------------------------------------------------------------ 样式
    def _style_nav_button(self, btn: QPushButton, active: bool) -> None:
        t = get_theme()
        color = t.accent if active else t.text_dim
        weight = "700" if active else "400"
        btn.setStyleSheet(
            "QPushButton {"
            f"  color: {color};"
            "  background: transparent;"
            "  border: none;"
            f"  text-align: left;"
            "  padding: 8px 12px 8px 16px;"
            f"  font-family: {t.font_cn}; font-size: 12pt;"
            f"  font-weight: {weight};"
            "}"
            f"QPushButton:hover {{ color: {t.accent}; }}"
        )

    def apply_theme_style(self) -> None:
        t = get_theme()
        self.setStyleSheet(
            "#SettingsPage {"
            f"  background: {t.bg};"
            "}"
            "QScrollArea#SettingsScroll { background: transparent; border: none; }"
            "QScrollArea#SettingsScroll > QWidget > QWidget { background: transparent; }"
            f"QWidget#SettingsSectionPage {{ background: {t.bg}; }}"
            f"QWidget#SettingsScrollHolder {{ background: {t.bg}; }}"
            f"QWidget#SettingsDetail {{ background: {t.bg}; }}"
        )
        self.nav.setStyleSheet(
            "QWidget#SettingsNav {"
            f"  background: {t.panel_2 if t.is_light else t.panel};"
            f"  border-right: {t.border_width}px solid {t.divider};"
            "}"
        )
        # 页头
        for page in self._pages:
            for lbl in page.findChildren(QLabel):
                name = lbl.objectName()
                if name == "SettingsSectionTitle":
                    lbl.setStyleSheet(
                        f"color: {t.accent}; background: transparent;"
                        f"font-family: {t.font_cn}; font-size: 18pt; font-weight: 700;"
                        f"letter-spacing: {t.label_tracking};"
                    )
                elif name == "SettingsSectionHint":
                    lbl.setStyleSheet(
                        f"color: {t.text_mute}; background: transparent;"
                        f"font-family: {t.font_mono}; font-size: 7.5pt;"
                        "letter-spacing: 1.4px;"
                    )
        # 行
        for row in self._rows.values():
            row.apply_theme_style()
        # 导航
        try:
            if getattr(self, "_nav_indicator", None) is not None:
                self._nav_indicator.refresh_style()
        except Exception:
            pass
        for i, btn in enumerate(self._nav_buttons):
            self._style_nav_button(btn, i == self._active)
        # 底部
        self.status_label.setStyleSheet(
            f"color: {t.text_mute}; background: transparent;"
            f"font-family: {t.font_mono}; font-size: 8pt;"
        )
        self.reset_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent;"
            f"  color: {t.text_dim};"
            f"  border: {t.border_width}px solid {t.border};"
            f"  border-radius: {t.radius_sm}px;"
            "  padding: 6px 16px;"
            f"  font-family: {t.font_cn}; font-size: 9.5pt;"
            "}"
            f"QPushButton:hover {{ color: {t.accent};"
            f"  border: {t.border_width}px solid {t.accent}; }}"
        )

        # 主题下拉跟随（顶栏按钮切主题后这里要同步）
        try:
            row = self._rows.get("ui.theme")
            if row is not None:
                row.setValue(get_theme_key())
        except Exception:
            pass
