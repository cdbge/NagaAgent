#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""边缘装置：莱茵用装订孔，少前用网格刻度。

两者都是**纯绘制**，不承载交互 —— 作用是让界面边缘不空，形成"这是一册
装订起来的档案 / 这是一块战术显示屏"的心理暗示。

| 主题 | 装置 |
|---|---|
| 莱茵（纸） | 左边缘一列装订孔（灰圆点），右侧对应同样的孔 |
| 少女前线 | 上下边缘的网格刻度（短竖线 + 每 5 格加长） |
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QSizePolicy, QWidget

from ui.styles.tokens import get_theme


class ArchiveRail(QWidget):
    """边缘装置条。

    Args:
        side: `"left"` / `"right"` / `"top"` / `"bottom"`
        thickness: 厚度（px）
    """

    def __init__(self, side: str = "left", thickness: int = 28,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._side = side
        self._thickness = thickness
        if side in ("left", "right"):
            self.setFixedWidth(thickness)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self.setFixedHeight(thickness)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):  # noqa: N802
        t = get_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if t.is_light:
            self._paint_binding(p, w, h, t)
        else:
            self._paint_ticks(p, w, h, t)

        p.end()

    # -- 莱茵：装订孔 -------------------------------------------------------
    def _paint_binding(self, p: QPainter, w: int, h: int, t) -> None:
        hole_r = 3.0
        gap = 46
        cx = w / 2
        color = QColor(t.border)
        color.setAlpha(210)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        y = gap
        while y < h - gap:
            p.drawEllipse(QPoint(int(cx), int(y)), int(hole_r), int(hole_r))
            y += gap
        p.setBrush(Qt.NoBrush)

    # -- 少女前线：网格刻度 -------------------------------------------------
    def _paint_ticks(self, p: QPainter, w: int, h: int, t) -> None:
        pen = QPen(QColor(t.divider))
        pen.setWidthF(1.0)
        p.setPen(pen)
        horizontal = self._side in ("top", "bottom")
        n = (w if horizontal else h)
        step = 12
        i = 0
        pos = 0
        while pos < n:
            major = (i % 5 == 0)
            ln = 10 if major else 4
            if horizontal:
                y1 = h - 1 if self._side == "bottom" else 0
                y2 = y1 - ln if self._side == "bottom" else y1 + ln
                p.drawLine(pos, y1, pos, y2)
            else:
                x1 = w - 1 if self._side == "right" else 0
                x2 = x1 - ln if self._side == "right" else x1 + ln
                p.drawLine(x1, pos, x2, pos)
            pos += step
            i += 1


def draw_viewfinder(painter: QPainter, rect, color: str,
                    arm: int = 18, width: float = 1.2,
                    skip: tuple = ()) -> None:
    """在 `rect` 的四角画取景框直角。

    Args:
        painter: 已激活的 QPainter
        rect: 目标区域（QRect）
        color: 颜色字符串
        arm: 直角臂长
        width: 线宽
    """
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    painter.setPen(pen)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    r = x + w
    b = y + h
    skip = skip or ()

    # 左上
    if "tl" not in skip:
        painter.drawLine(x, y, x + arm, y)
        painter.drawLine(x, y, x, y + arm)
    # 右上（窗口按钮组那一角会被跳过，改由按钮自己的包裹框画）
    if "tr" not in skip:
        painter.drawLine(r - arm, y, r, y)
        painter.drawLine(r, y, r, y + arm)
    # 左下
    if "bl" not in skip:
        painter.drawLine(x, b - arm, x, b)
        painter.drawLine(x, b, x + arm, b)
    # 右下
    if "br" not in skip:
        painter.drawLine(r - arm, b, r, b)
        painter.drawLine(r, b - arm, r, b)
