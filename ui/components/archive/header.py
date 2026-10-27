#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶栏：LOGO + 副标 + 编号导航 + 状态码。

版式取自莱茵生命档案册实拍：

    RHINE LAB ∞ │ SYNTHESIZE INFORMATION   00 封面 01 索引 02 正文 … │ CAT. RL-X000

对应到本应用：

    NAGA AGENT ∞ │ SYNTHESIZE / ANALYSIS OS   00 对话 01 云图 02 博弈 03 设置 │ MODEL · REV

两套主题的差异由令牌驱动：少前用琥珀金 + 更宽字距，莱茵用橙色 + 档案编号感。
"""

from __future__ import annotations

import logging

from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from ui.styles.tokens import font_stack, get_theme

logger = logging.getLogger(__name__)


class _NavButton(QPushButton):
    """编号导航项：`00 对话` —— 序号等宽、标签跟随主题大小写规则。"""

    def __init__(self, number: int, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._number = number
        self._label = label
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self._scale = 1.0
        self.setCheckable(True)
        self._refresh()

    def _refresh(self) -> None:
        t = get_theme()
        text = f"{self._number:02d} {self._label}"
        if t.uppercase_labels:
            # 序号保持原样，中文标签不变；只对纯英文标签大写
            pass
        self.setText(text)
        color = t.accent if self.isChecked() else t.text_mute
        weight = "700" if self.isChecked() else "500"
        # 字号随选中做轻微放大（_scale 由动画驱动，1.0 -> 1.07）
        size_pt = 10.0 * self._scale
        # 下划线改由 SlidingIndicator 画，这里不再用 border-bottom（那是瞬移）
        self.setStyleSheet(f"""
            QPushButton {{
                color: {color};
                background: transparent;
                border: none;
                font-family: {font_stack(t, 'cn')};
                font-size: {size_pt:.2f}pt;
                font-weight: {weight};
                letter-spacing: {t.label_tracking};
                padding: 6px 10px 5px 10px;
            }}
            QPushButton:hover {{
                color: {t.accent};
            }}
        """)

    def refresh_style(self) -> None:
        self._refresh()

    def getScale(self):
        return self._scale

    def setScale(self, v):
        self._scale = float(v)
        self._refresh()

    scale = pyqtProperty(float, fget=getScale, fset=setScale)



#: 每套主题配一首三行德文诗。
#:   text   —— 诗句（不含署名）
#:   author —— 署名
#:   font   —— 手写/艺术体字体族（Windows 自带，均支持德文变音符号）
#:   size   —— 字号（pt）
_POEMS = {
    "gfl": {
        "text": ("Wo aber Gefahr ist, wächst\n"
                 "das Rettende auch."),
        "author": "Friedrich Hölderlin",
        "font": "Blackadder ITC",
        "size": 15.5,
    },
    "rhine": {
        "text": ("Sein Blick ist vom Vorübergehn der Stäbe\n"
                 "so müd geworden, daß er nichts mehr hält."),
        "author": "Rainer Maria Rilke",
        "font": "Kunstler Script",
        "size": 15.0,
    },
    "default": {
        "text": ("Ich lebe mein Leben in wachsenden Ringen,\n"
                 "die sich über die Dinge ziehn."),
        "author": "Rainer Maria Rilke",
        "font": "Edwardian Script ITC",
        "size": 16.0,
    },
}


class ArchiveHeader(QWidget):

    """档案式顶栏。

    Signals:
        pageSelected(int): 用户点击了某个编号页
    """

    pageSelected = pyqtSignal(int)
    # 点击主题按钮：请求循环切换主题（实际切换与动效由主窗口处理）
    themeCycleRequested = pyqtSignal()

    HEIGHT = 92

    def __init__(self, parent: Optional[QWidget] = None,
                 pages: Optional[List[Tuple[int, str]]] = None):
        super().__init__(parent)
        # QWidget 子类默认不画 QSS 背景，必须显式打开（且要在 super() 之后）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 页码定义：(序号, 标签)。序号从 00 开始，与档案册一致。
        self._pages = pages or [(0, "对话"), (1, "云图"), (2, "博弈"), (3, "设置")]
        self._nav: List[_NavButton] = []
        self._build()

    # -- 构建 --------------------------------------------------------------
    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(16)

        # 左：LOGO + 副标（两行堆叠，模仿档案册的 lockup）
        # 用 QWidget 包一层再按 AlignVCenter 加进 HBox ——
        # 直接 addLayout 会让子控件从顶部排，看起来像贴着上方。
        left_box = QWidget()
        left_box.setStyleSheet("background: transparent;")
        left = QVBoxLayout(left_box)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        self.logo = QLabel("NAGA AGENT")
        self.subtitle = QLabel("SYNTHESIZE / ANALYSIS OS")
        left.addWidget(self.logo)
        left.addWidget(self.subtitle)
        row.addWidget(left_box, 0, Qt.AlignVCenter)

        row.addStretch(1)

        # 中：德文诗（诗句 + 署名，上下居中）
        poem_box = QWidget()
        poem_box.setStyleSheet("background: transparent;")
        poem_lay = QVBoxLayout(poem_box)
        poem_lay.setContentsMargins(0, 0, 0, 0)
        poem_lay.setSpacing(2)
        self.poem = QLabel()
        self.poem.setAlignment(Qt.AlignCenter)
        self.poem.setWordWrap(False)
        self.poem_author = QLabel()
        self.poem_author.setAlignment(Qt.AlignCenter)
        poem_lay.addWidget(self.poem)
        poem_lay.addWidget(self.poem_author)
        row.addWidget(poem_box, 0, Qt.AlignVCenter)

        row.addStretch(1)

        # 中偏右：编号导航
        for number, label in self._pages:
            btn = _NavButton(number, label, self)
            btn.clicked.connect(lambda _=False, n=number: self._on_click(n))
            self._nav.append(btn)
            row.addWidget(btn)

        row.addSpacing(12)
        row.addStretch(1)

        # 主题切换按钮：点击后从按钮位置辐射展开新主题（径向揭示）
        self.theme_btn = QPushButton("THEME")
        self.theme_btn.setFlat(True)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setFixedHeight(24)
        self.theme_btn.clicked.connect(self.themeCycleRequested.emit)
        self.theme_btn.setToolTip("切换界面主题（从按钮位置辐射展开）")
        row.addWidget(self.theme_btn)

        row.addSpacing(10)

        # 右：状态码
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.status)

        # 滑动下划线：由独立控件绘制，选中切换时平滑滑过去
        from ui.components.archive.indicator import SlidingIndicator

        self._nav_indicator = SlidingIndicator(self, horizontal=True)

    # -- 交互 --------------------------------------------------------------
    def _on_click(self, number: int) -> None:
        self.set_current(number)
        self.pageSelected.emit(number)

    def set_current(self, number: int, animate: bool = True) -> None:
        """高亮某个编号（不做页面切换，切换由外部负责）。

        animate=True 时：指示条平滑滑到新项，新旧项字号做一次缩放过渡。
        """
        from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QTimer

        old_index = next((i for i, b in enumerate(self._nav) if b.isChecked()), None)
        new_index = next((i for i, b in enumerate(self._nav) if b._number == number), None)

        for btn in self._nav:
            btn.setChecked(btn._number == number)
            btn._refresh()

        if not self._nav:
            return

        def _sync_indicator():
            try:
                idx = new_index
                if idx is None or idx >= len(self._nav):
                    self._nav_indicator.hide()
                    return
                target = self._nav[idx]
                rect = self._nav_indicator.bar_rect_for(target)
                if rect.isNull():
                    return
                if animate:
                    self._nav_indicator.animate_to(rect)
                else:
                    self._nav_indicator.jump_to(rect)
            except Exception as exc:
                logger.debug(f"[顶栏] 指示条定位失败: {exc}")

        QTimer.singleShot(0, _sync_indicator)

        # 选中项轻微放大（1.0 -> 1.07），旧项缩回
        if animate:
            for i, btn in enumerate(self._nav):
                target = 1.07 if i == new_index else 1.0
                try:
                    anim = QPropertyAnimation(btn, b"scale", btn)
                    anim.setDuration(180)
                    anim.setStartValue(getattr(btn, "_scale", 1.0))
                    anim.setEndValue(target)
                    anim.setEasingCurve(QEasingCurve.OutCubic)
                    anim.start()
                    btn._scale_anim = anim  # 保持引用
                except Exception:
                    pass

    def refresh_style(self, status_text: str = "") -> None:
        """按当前主题重绘。"""
        t = get_theme()
        self.setStyleSheet(f"""
            ArchiveHeader {{
                background: {t.panel_2};
                border-bottom: {t.border_width}px solid {t.divider};
            }}
        """)
        self.logo.setStyleSheet(f"""
            QLabel {{
                color: {t.text};
                font-family: {font_stack(t, 'en')};
                font-size: 24pt;
                font-weight: 800;
                letter-spacing: -0.3px;
                background: transparent;
            }}
        """)
        self.subtitle.setStyleSheet(f"""
            QLabel {{
                color: {t.text_mute};
                font-family: {font_stack(t, 'mono')};
                font-size: 8pt;
                letter-spacing: 2.2px;
                background: transparent;
            }}
        """)
        if status_text:
            self.status.setText(status_text)
        self.status.setStyleSheet(f"""
            QLabel {{
                color: {t.text_mute};
                font-family: {font_stack(t, 'mono')};
                font-size: 8pt;
                letter-spacing: 0.6px;
                background: transparent;
            }}
        """)
        # 主题按钮：显示当前主题缩写，描边用分割线，悬停变强调色
        try:
            self.theme_btn.setText(f"THEME · {t.key.upper()}")
        except Exception:
            pass
        self.theme_btn.setStyleSheet(f"""
            QPushButton {{
                color: {t.text_mute};
                background: transparent;
                border: 1px solid {t.divider};
                border-radius: {max(0, t.radius_sm)}px;
                font-family: {font_stack(t, 'mono')};
                font-size: 7.5pt;
                letter-spacing: 1px;
                padding: 1px 8px;
            }}
            QPushButton:hover {{
                color: {t.accent};
                border: 1px solid {t.accent};
            }}
            QPushButton:pressed {{
                background: {t.accent_soft};
            }}
        """)
        # 德文诗：每套主题不同诗句 + 不同手写体
        try:
            poem = _POEMS.get(getattr(t, "key", "gfl"), _POEMS["gfl"])
            # 用 QFont 设手写体（富文本里 <font face> + span font-size
            # 会互相覆盖，导致两行重叠、署名字号错乱）。
            from PyQt5.QtGui import QFont

            _f = QFont(poem["font"])
            _f.setPointSizeF(float(poem["size"]))
            self.poem.setFont(_f)
            self.poem.setText(poem["text"])
            self.poem.setStyleSheet(
                f"color: {t.text_mute}; background: transparent;"
            )

            _fa = QFont(t.font_mono or "Consolas")
            _fa.setPointSizeF(max(7.0, float(poem["size"]) * 0.52))
            self.poem_author.setFont(_fa)
            self.poem_author.setText("— " + str(poem["author"]))
            self.poem_author.setStyleSheet(
                f"color: {t.text_mute}; background: transparent;"
            )
        except Exception as exc:
            logger.debug(f"[顶栏] 诗句渲染失败: {exc}")

        for btn in self._nav:
            btn.refresh_style()
        try:
            self._nav_indicator.refresh_style()
        except Exception:
            pass
