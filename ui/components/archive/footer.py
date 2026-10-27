#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页脚：套准靶 + 色条 + 纸张信息 + 实时坐标。

版式取自档案册实拍：

    ⊛(套准靶)   ▪▪▪▪▪▪(CMYK+橙 色条)   PAPER 105G / SINGLE INK   X 0000 · Y 0000 · SEC.00  [GRID]

坐标是**真实可用**的：鼠标在窗口内移动时更新，右侧 `GRID` 按钮切换网格叠加。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QWidget)

from ui.styles.tokens import font_stack, get_theme


class _RegistrationMark(QWidget):
    """套准靶：同心圆 + 十字。"""

    def __init__(self, parent: Optional[QWidget] = None, size: int = 18):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):  # noqa: N802
        t = get_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(t.text_mute))
        pen.setWidthF(0.8)
        p.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) - 1.5
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))
        p.drawEllipse(QPoint(int(cx), int(cy)), max(2, int(r * 0.34)),
                      max(2, int(r * 0.34)))
        p.drawLine(int(cx - r - 1), int(cy), int(cx + r + 1), int(cy))
        p.drawLine(int(cx), int(cy - r - 1), int(cx), int(cy + r + 1))
        p.end()


class _ColorBar(QWidget):
    """印刷色条：CMYK + 专色橙（莱茵）/ 琥珀金（少前）。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setMinimumWidth(72)

    def paintEvent(self, event):  # noqa: N802
        t = get_theme()
        if t.is_light:
            colors = ["#00AEEF", "#EC008C", "#FFF200", "#151513", t.accent]
        else:
            colors = ["#4A4A4A", "#6E6E6E", "#8F8F8F", "#C8C8C8", t.accent]
        p = QPainter(self)
        w = self.width() / len(colors)
        for i, c in enumerate(colors):
            p.fillRect(int(i * w), 0, int(w) + 1, self.height(), QColor(c))
        p.end()


class ArchiveFooter(QWidget):
    """档案式页脚。

    Signals:
        gridToggled(bool): `GRID` 按钮状态变化
    """

    gridToggled = pyqtSignal(bool)

    HEIGHT = 32

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(12)

        self.mark = _RegistrationMark(self)
        row.addWidget(self.mark)

        self.info = QLabel("PAPER 105G / SINGLE INK + SPOT")
        row.addWidget(self.info)

        row.addStretch(1)

        self.colorbar = _ColorBar(self)
        row.addWidget(self.colorbar)

        row.addStretch(1)

        self.coords = QLabel("X 0000 · Y 0000")
        row.addWidget(self.coords)

        self.grid_btn = QPushButton("GRID")
        self.grid_btn.setFlat(True)
        self.grid_btn.setCheckable(True)
        self.grid_btn.setCursor(Qt.PointingHandCursor)
        self.grid_btn.setFixedHeight(18)
        self.grid_btn.toggled.connect(self.gridToggled.emit)
        row.addWidget(self.grid_btn)

    # -- 坐标 --------------------------------------------------------------
    def update_cursor(self, pos: QPoint) -> None:
        """由主窗口在 mouseMoveEvent 里调用，显示实时坐标。"""
        self._last = pos
        self.coords.setText(f"X {pos.x():04d} · Y {pos.y():04d}")

    def _tick(self) -> None:
        # 坐标由鼠标驱动；无鼠标时不需要动。保留 timer 供以后加 SEC 计时。
        pass

    # -- 样式 --------------------------------------------------------------
    def refresh_style(self) -> None:
        t = get_theme()
        self.setStyleSheet(f"""
            ArchiveFooter {{
                background: {t.panel_2};
                border-top: {t.border_width}px solid {t.divider};
            }}
        """)
        for w in (self.info, self.coords):
            w.setStyleSheet(f"""
                QLabel {{
                    color: {t.text_mute};
                    font-family: {font_stack(t, 'mono')};
                    font-size: 7pt;
                    letter-spacing: 1.2px;
                    background: transparent;
                }}
            """)
        self.grid_btn.setStyleSheet(f"""
            QPushButton {{
                color: {t.text_mute};
                background: transparent;
                border: 1px solid {t.divider};
                font-family: {font_stack(t, 'mono')};
                font-size: 7pt;
                letter-spacing: 1.2px;
                padding: 1px 6px;
            }}
            QPushButton:checked {{
                color: {t.accent};
                border: 1px solid {t.accent};
            }}
        """)
        self.mark.update()
        self.colorbar.update()
