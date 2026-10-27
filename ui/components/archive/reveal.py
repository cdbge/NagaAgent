#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""径向揭示：切换主题时，从点击位置扩散一个圆，圆内露出新界面、圆外保留旧快照。

效果对标 Web 的 View Transitions 圆形揭示（`::view-transition-new(root)` +
`clip-path: circle(0% at click)`）。

实现原理
========

Qt 没有 View Transitions，因此用**三层**模拟：

1. **切换前**用 `QWidget.grab()` 拍下整窗快照（旧主题的样子）；
2. 立即应用新主题（此时窗口已经变成新样子，但被覆盖层挡住）；
3. 覆盖层绘制旧快照，并用 `QPainterPath.subtracted()` 把**扩散圆内部**从裁剪区挖掉 ——
   于是圆内露出的就是下层真实的新界面，圆外仍是旧快照。

半径从 0 动画到「能覆盖整窗的最远角距离」，用 `OutCubic` 缓动、620ms，
与莱茵生命规范里的显影时长（`.62s`）一致。

边缘装饰
========

圆的边界画一圈 1.2px 的主题强调色描边，并让它在动画后段淡出 ——
这对应规范里"显影"的观感：不是单纯的遮罩揭开，而是有一道扫过边缘的痕。

降级
====

* 窗口最小化 / 尺寸为 0 时直接跳过动画，避免抓空图。
* 用户配置 `ui.animation_duration <= 0`（减少动效）时直接应用，不播动画。
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                          Qt, pyqtProperty, pyqtSignal)
from PyQt5.QtGui import (QColor, QPainter, QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import QWidget

logger = logging.getLogger(__name__)

__all__ = ["RadialReveal", "play_radial_reveal"]


class RadialReveal(QWidget):
    """全窗覆盖层：圆外绘制旧快照，圆内透明（露出新界面）。"""

    finished = pyqtSignal()

    # 揭示时长（毫秒）。620 对齐莱茵生命规范里的「显影 `.62s`」。
    DEFAULT_DURATION = 620
    # 边缘描边宽度
    EDGE_WIDTH = 1.2

    def __init__(self, parent: QWidget, snapshot: QPixmap, origin: QPoint,
                 duration: int = DEFAULT_DURATION,
                 edge_color: str = "#E9521C"):
        super().__init__(parent)
        self._snapshot = snapshot
        self._origin = QPoint(origin)
        self._duration = max(0, int(duration))
        self._edge_color = edge_color
        self._radius = 0.0
        self._max_radius = self._compute_max_radius(parent.size())

        # 覆盖层不能声明为不透明：圆内是透明洞，必须让下层真实界面透出来。
        # 之前的 WA_OpaquePaintEvent=True 会让 Qt 跳过下层绘制，圆内变成空白。
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()

        self._anim: Optional[QPropertyAnimation] = None

    # -- 几何 --------------------------------------------------------------
    @staticmethod
    def _compute_max_radius(size) -> float:
        """圆心到四角的最大距离 —— 保证动画结束时全覆盖。"""
        w, h = size.width(), size.height()
        return (w * w + h * h) ** 0.5

    # -- 可动画属性 --------------------------------------------------------
    def getRadius(self) -> float:
        return self._radius

    def setRadius(self, value: float) -> None:
        self._radius = float(value)
        self.update()

    radius = pyqtProperty(float, fget=getRadius, fset=setRadius)

    # -- 播放 --------------------------------------------------------------
    def start(self) -> None:
        """开始扩散。duration 为 0 时立刻结束（减少动效模式）。"""
        if self._duration <= 0 or not self.width():
            self._finish()
            return
        anim = QPropertyAnimation(self, b"radius", self)
        anim.setDuration(self._duration)
        anim.setStartValue(0.0)
        anim.setEndValue(self._max_radius)
        # OutCubic：快速启动、平缓收尾 —— 机械感，不过冲
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._finish)
        self._anim = anim
        anim.start()

    def _finish(self) -> None:
        self.finished.emit()
        self.hide()
        self.deleteLater()

    # -- 绘制 --------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1) 圆外区域：画旧快照
        outer = QPainterPath()
        from PyQt5.QtCore import QRectF
        outer.addRect(QRectF(self.rect()))
        if self._radius > 0:
            hole = QPainterPath()
            hole.addEllipse(QPointF(self._origin), self._radius, self._radius)
            clip = outer.subtracted(hole)
        else:
            clip = outer

        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, self._snapshot)
        painter.setClipping(False)

        # 2) 边缘描边：只在扩散过程中可见，最后 25% 淡出
        if 0 < self._radius < self._max_radius:
            progress = self._radius / self._max_radius if self._max_radius else 1.0
            # progress 0.75 之后开始淡出
            alpha = 1.0 if progress < 0.75 else max(0.0, (1.0 - progress) / 0.25)
            color = QColor(self._edge_color)
            color.setAlphaF(min(1.0, alpha * 0.85))
            pen = QPen(color)
            pen.setWidthF(self.EDGE_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(self._origin), self._radius, self._radius)

        painter.end()


def play_radial_reveal(window: QWidget, apply_theme, origin: QPoint,
                       duration: Optional[int] = None,
                       edge_color: str = "#E9521C") -> Optional[RadialReveal]:
    """在 `window` 上播放一次径向揭示，期间执行 `apply_theme()`。

    Args:
        window: 目标窗口（通常是主窗口）
        apply_theme: 应用新主题的回调（在拍完快照后、覆盖层显示前调用）
        origin: 揭示圆心（窗口内坐标，通常是主题按钮中心）
        duration: 覆盖动画时长；None 时读 `config.ui.animation_duration`
        edge_color: 边缘描边颜色

    Returns:
        覆盖层实例（便于测试）；无法播放时返回 None
    """
    try:
        if window is None or window.width() <= 1 or window.height() <= 1:
            apply_theme()
            return None

        # 1) 拍旧快照
        snapshot = window.grab()

        # 2) 应用新主题（此时窗口内容已变，但马上会被覆盖层挡住）
        apply_theme()

        # 3) 决定时长
        if duration is None:
            try:
                from core.system.config import config

                duration = int(getattr(config.ui, "animation_duration", 600) or 600)
            except Exception:
                duration = RadialReveal.DEFAULT_DURATION
            # 配置里 600 对应"面板展开"档；显影用 620 更贴近规范，按比例取
            duration = max(0, min(duration, 900))

        reveal = RadialReveal(window, snapshot, origin,
                              duration=duration, edge_color=edge_color)
        reveal.start()
        return reveal
    except Exception as exc:
        logger.warning(f"[reveal] 径向揭示失败，直接切换: {exc}")
        try:
            apply_theme()
        except Exception:
            pass
        return None
