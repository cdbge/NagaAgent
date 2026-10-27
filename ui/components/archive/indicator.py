#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滑动指示条：选中项切换时，指示条平滑滑到新位置，不瞬移。

用在哪
======

* **顶栏编号导航** —— 当前项的强调色下划线
* **设置页左侧类别** —— 当前项的左侧竖条

为什么单独抽出来
================

两处逻辑完全一样：一个 2px 的条，从旧位置动画到新位置。
差别只是方向（横/竖）和颜色。

实现要点
========

* 指示条是**独立子控件**，不参与布局 —— 动它不影响其它控件。
* 动画目标 `geometry`，`OutCubic`，默认 220ms（快而不生硬）。
* 指示条自己画，颜色由 `accent` 令牌决定，跟随主题。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

__all__ = ["SlidingIndicator"]


class SlidingIndicator(QWidget):
    """一条会滑动的强调色指示条。"""

    #: 滑动时长（ms）
    SLIDE_DURATION = 220
    #: 指示条粗细（px）
    THICKNESS = 2

    def __init__(self, parent: QWidget, horizontal: bool = True,
                 thickness: Optional[int] = None):
        super().__init__(parent)
        self._horizontal = horizontal
        self._thickness = thickness or self.THICKNESS
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._anim: Optional[QPropertyAnimation] = None
        self.hide()

    # -- 绘制 --------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        try:
            from ui.styles.tokens import get_theme

            t = get_theme()
            color = QColor(t.accent)
        except Exception:
            color = QColor("#F4C430")
        p = QPainter(self)
        p.fillRect(self.rect(), color)
        p.end()

    def refresh_style(self) -> None:
        self.update()

    # -- 动画 --------------------------------------------------------------
    def jump_to(self, rect: QRect) -> None:
        """立刻定位（首次显示用，不做动画）。"""
        self.setGeometry(rect)
        self.show()
        self.raise_()

    def animate_to(self, rect: QRect, duration: Optional[int] = None) -> None:
        """平滑滑到目标矩形。"""
        if not self.isVisible() or self.geometry() == rect:
            self.jump_to(rect)
            return
        try:
            anim = QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(int(duration) if duration else self.SLIDE_DURATION)
            anim.setStartValue(self.geometry())
            anim.setEndValue(rect)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anim = anim  # 保持引用，避免被 GC
            self.raise_()
        except Exception:
            self.jump_to(rect)

    # -- 尺寸辅助 ----------------------------------------------------------
    def bar_rect_for(self, widget: QWidget, align_top: bool = True) -> QRect:
        """根据目标控件算出指示条矩形（条在控件下方/左侧）。"""
        try:
            p = self.parentWidget()
            tl = widget.mapTo(p, widget.rect().topLeft() if align_top
                              else widget.rect().topRight())
            if self._horizontal:
                # 横向条：位于控件底部，宽度 = 控件宽度
                y = tl.y() + widget.height() - self._thickness
                return QRect(tl.x(), y, widget.width(), self._thickness)
            # 竖向条：位于控件左缘，高度 = 控件高度
            return QRect(tl.x(), tl.y(), self._thickness, widget.height())
        except Exception:
            return QRect()
