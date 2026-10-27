#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主题化图标按钮：按当前主题线稿重绘，替代原来的彩色 emoji 圆按钮。

原实现用 emoji 字符 + 彩色圆底（蓝/紫/红），和两套主题的"档案/战术"气质都不合；
emoji 在不同系统上还会渲染成彩色位图，尺寸也难对齐。

这里改成**纯几何线稿**：

* 图标由 `paintEvent` 用 QPainter 画，颜色全部取主题令牌；
* 静止态 `text_mute`，悬停/按下/选中态 `accent`；
* 形状统一 1.4px 描边、28×28 方形，和顶栏导航的气质一致。

图标含义
--------

| kind | 形状 |
|---|---|
| `upload` | 托盘 + 向上箭头 |
| `mind_map` | 三节点连线（图谱） |
| `font_size` | 字母 A + 上下箭头 |
| `intent` | 交叉箭头（博弈/意图） |
| `voice` | 麦克风 |
| `feedback` | 三角 + 感叹号（反馈） |
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QPushButton, QWidget

from ui.styles.tokens import get_theme

__all__ = ["ThemedIconButton", "ICON_KINDS"]

ICON_KINDS = ("upload", "mind_map", "font_size", "intent", "voice", "feedback")


class ThemedIconButton(QPushButton):
    """方形线稿图标按钮。"""

    SIZE = 30

    def __init__(self, kind: str, parent: Optional[QWidget] = None,
                 tooltip: str = ""):
        super().__init__(parent)
        self._kind = kind if kind in ICON_KINDS else "upload"
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setCheckable(kind == "voice")
        if tooltip:
            self.setToolTip(tooltip)
        self._refresh_qss()

    def set_kind(self, kind: str) -> None:
        self._kind = kind if kind in ICON_KINDS else self._kind
        self.update()

    def refresh_style(self) -> None:
        self._refresh_qss()
        self.update()

    def _refresh_qss(self) -> None:
        t = get_theme()
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {t.border};
                border-radius: {max(0, t.radius_sm)}px;
            }}
            QPushButton:hover {{
                border: 1px solid {t.accent};
                background: {t.accent_soft};
            }}
            QPushButton:checked {{
                border: 1px solid {t.accent};
                background: {t.accent_soft};
            }}
        """)

    # -- 绘制 --------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        t = get_theme()
        active = self.isChecked() or self.underMouse()
        color = QColor(t.accent if active else t.text_mute)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(color)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        # 可用绘制区（留 7px 内边距）
        m = 7.0
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        getattr(self, f"_draw_{self._kind}", self._draw_upload)(p, r)
        p.end()

    # -- 各图标 ------------------------------------------------------------
    @staticmethod
    def _draw_upload(p: QPainter, r: QRectF) -> None:
        """托盘 + 向上箭头。"""
        cx = r.center().x()
        p.drawLine(QPointF(cx, r.bottom()), QPointF(cx, r.top() + r.height() * 0.35))
        p.drawLine(QPointF(cx, r.top() + r.height() * 0.35),
                   QPointF(cx - r.width() * 0.22, r.top() + r.height() * 0.58))
        p.drawLine(QPointF(cx, r.top() + r.height() * 0.35),
                   QPointF(cx + r.width() * 0.22, r.top() + r.height() * 0.58))
        p.drawLine(QPointF(r.left(), r.bottom() - r.height() * 0.18),
                   QPointF(r.left(), r.bottom()))
        p.drawLine(QPointF(r.left(), r.bottom()),
                   QPointF(r.right(), r.bottom()))
        p.drawLine(QPointF(r.right(), r.bottom()),
                   QPointF(r.right(), r.bottom() - r.height() * 0.18))

    @staticmethod
    def _draw_mind_map(p: QPainter, r: QRectF) -> None:
        """三节点连线：中心 + 左右上。"""
        c = r.center()
        a = QPointF(r.left() + r.width() * 0.18, r.top() + r.height() * 0.30)
        b = QPointF(r.right() - r.width() * 0.18, r.top() + r.height() * 0.30)
        d = QPointF(r.center().x(), r.bottom() - r.height() * 0.12)
        for pt in (a, b, d):
            p.drawLine(c, pt)
        rad = 2.0
        for pt in (c, a, b, d):
            p.drawEllipse(pt, rad, rad)

    @staticmethod
    def _draw_font_size(p: QPainter, r: QRectF) -> None:
        """字母 A + 上下箭头。"""
        x0 = r.left() + r.width() * 0.10
        x1 = r.left() + r.width() * 0.55
        base = r.bottom() - r.height() * 0.10
        apex = r.top() + r.height() * 0.12
        p.drawLine(QPointF(x0, base), QPointF((x0 + x1) / 2, apex))
        p.drawLine(QPointF((x0 + x1) / 2, apex), QPointF(x1, base))
        p.drawLine(QPointF(x0 + (x1 - x0) * 0.22, base - r.height() * 0.28),
                   QPointF(x1 - (x1 - x0) * 0.22, base - r.height() * 0.28))
        # 右侧上下箭头
        ax = r.right() - r.width() * 0.14
        p.drawLine(QPointF(ax, r.top() + r.height() * 0.18),
                   QPointF(ax, r.top() + r.height() * 0.55))
        p.drawLine(QPointF(ax, r.top() + r.height() * 0.55),
                   QPointF(ax - 2.2, r.top() + r.height() * 0.44))
        p.drawLine(QPointF(ax, r.bottom() - r.height() * 0.18),
                   QPointF(ax, r.bottom() - r.height() * 0.55))
        p.drawLine(QPointF(ax, r.bottom() - r.height() * 0.55),
                   QPointF(ax - 2.2, r.bottom() - r.height() * 0.44))

    @staticmethod
    def _draw_intent(p: QPainter, r: QRectF) -> None:
        """交叉箭头：两条对角带箭头，表示"博弈/意图流向"。"""
        p.drawLine(QPointF(r.left(), r.top()), QPointF(r.right(), r.bottom()))
        p.drawLine(QPointF(r.right(), r.top()), QPointF(r.left(), r.bottom()))
        p.drawLine(QPointF(r.right(), r.bottom()),
                   QPointF(r.right() - r.width() * 0.22, r.bottom()))
        p.drawLine(QPointF(r.right(), r.bottom()),
                   QPointF(r.right(), r.bottom() - r.height() * 0.22))

    @staticmethod
    def _draw_voice(p: QPainter, r: QRectF) -> None:
        """麦克风。"""
        cx = r.center().x()
        w = r.width() * 0.30
        p.drawRoundedRect(
            QRectF(cx - w / 2, r.top(), w, r.height() * 0.52), w / 2, w / 2)
        p.drawArc(QRectF(cx - r.width() * 0.32, r.top() + r.height() * 0.28,
                         r.width() * 0.64, r.height() * 0.44), 180 * 16, 180 * 16)
        p.drawLine(QPointF(cx, r.bottom() - r.height() * 0.28),
                   QPointF(cx, r.bottom()))

    @staticmethod
    def _draw_feedback(p: QPainter, r: QRectF) -> None:
        """三角 + 感叹号。"""
        c = r.center()
        p.drawPolygon(
            QPointF(c.x(), r.top()),
            QPointF(r.right(), r.bottom()),
            QPointF(r.left(), r.bottom()),
        )
        p.drawLine(QPointF(c.x(), r.top() + r.height() * 0.42),
                   QPointF(c.x(), r.top() + r.height() * 0.62))
        p.drawPoint(QPointF(c.x(), r.top() + r.height() * 0.76))
