#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动效库：莱茵生命的「压印 / 显影 / 归档」三类动效。

设计纪律
========

来自莱茵生命设计规范的第 5 条铁律：

> 动效只做三件事：**压印、显影、归档** —— 机械缓动，**至多过冲一次**。

因此：

* **禁用**弹跳（bounce）、橡皮筋（elastic）、无限循环的呼吸位移 ——
  那些是"玩具感"，与档案/机械的气质相反。
* 90% 的场景用 `OutCubic`（快速启动、缓慢收尾），需要"数据闪现"时用 `OutExpo`。
* 只有"落位"类动画（徽章、编号）允许 `OutBack` 过冲一次。
* 时值固定四档：`.12s` 微反馈 / `.3s` 默认 / `.6s` 面板 / `1s` 整屏。

三类动效
========

**压印（press）** —— 元素像盖章一样落下：从上方 8px 处下落 + 淡入，
`OutCubic` 240ms。用于新消息、新卡片。

**显影（develop）** —— 像底片显影：从下方浮起 + 淡入，300ms。
用于列表项、提示条。

**归档（file）** —— 元素向外淡出 + 轻微位移，用于替换/清除。

另有：

* `OdometerLabel` —— 数字里程计（数值滚动，`OutExpo`）
* `DrawProgressBar` —— 线条按进度绘制（不是填充，是"画出来"）

用法
====

    from ui.styles.motion import animate_press, animate_develop

    animate_press(self)            # 组件入场
    animate_develop(row_widget)    # 列表项入场

动画对象挂在组件的 `_motion_anims` 上，重复调用会先停掉上一段，避免叠加。
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from PyQt5.QtCore import (QEasingCurve, QPropertyAnimation, QTimer, Qt,
                          pyqtProperty, pyqtSignal)
from PyQt5.QtWidgets import (QGraphicsOpacityEffect, QLabel, QProgressBar,
                             QWidget)

logger = logging.getLogger(__name__)

__all__ = [
    "EASE_DEFAULT", "EASE_SNAP", "EASE_PANEL", "EASE_SOFT", "EASE_PRESS",
    "DUR_INSTANT", "DUR_FAST", "DUR_BASE", "DUR_PANEL", "DUR_SCREEN",
    "animate_press", "animate_develop", "animate_file",
    "animate_opacity", "stop_motion",
    "OdometerLabel", "DrawProgressBar",
]

# ---------------------------------------------------------------------------
# 缓动与时长
# ---------------------------------------------------------------------------
# 默认入场：快速启动、平滑收尾。90% 的场景用它。
EASE_DEFAULT = QEasingCurve.OutCubic
# 数字/数据闪现：开头极快，尾段几乎不动。
EASE_SNAP = QEasingCurve.OutExpo
# 面板展开：比 OutCubic 更急，适合大块高度变化。
EASE_PANEL = QEasingCurve.OutQuint
# 循环漂移：对称缓入缓出，仅用于背景/呼吸，不做入场。
EASE_SOFT = QEasingCurve.InOutSine
# 落位：允许**一次**轻微过冲。
EASE_PRESS = QEasingCurve.OutBack

DUR_INSTANT = 0
DUR_FAST = 120      # 微反馈：hover、聚焦
DUR_BASE = 300      # 默认：入场、显影
DUR_PANEL = 600     # 面板展开
DUR_SCREEN = 1000   # 整屏/页面切换


def _duration(ms: Optional[int], fallback: int) -> int:
    """读配置里的动画时长缩放，允许用户调快调慢。"""
    if ms is not None:
        return max(0, int(ms))
    try:
        from core.system.config import config

        base = int(getattr(config.ui, "animation_duration", DUR_PANEL) or DUR_PANEL)
        # animation_duration 默认 600，对应 DUR_PANEL；按比例缩放其它档位
        return max(0, int(fallback * base / DUR_PANEL))
    except Exception:
        return fallback


def _store_anim(widget: QWidget, anim: QPropertyAnimation) -> None:
    """把动画挂到组件上，防止被 GC；同属性旧动画先停掉。"""
    try:
        anims: List[QPropertyAnimation] = getattr(widget, "_motion_anims", None)
        if anims is None:
            anims = []
            setattr(widget, "_motion_anims", anims)
        prop = anim.propertyName()
        for old in list(anims):
            try:
                if old.propertyName() == prop and old.state() == QPropertyAnimation.Running:
                    old.stop()
            except RuntimeError:
                anims.remove(old)
        anims.append(anim)
        anim.finished.connect(lambda: anims.remove(anim) if anim in anims else None)
    except Exception:
        pass


def _ensure_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    """给组件装（或复用）透明度效果。"""
    eff = getattr(widget, "_motion_opacity", None)
    if eff is None:
        eff = QGraphicsOpacityEffect(widget)
        eff.setOpacity(1.0)
        setattr(widget, "_motion_opacity", eff)
        widget.setGraphicsEffect(eff)
    return eff


def animate_opacity(
    widget: QWidget,
    to: float,
    ms: Optional[int] = None,
    curve: QEasingCurve = EASE_DEFAULT,
    on_done: Optional[Callable[[], None]] = None,
) -> Optional[QPropertyAnimation]:
    """透明度过渡。"""
    try:
        eff = _ensure_effect(widget)
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setDuration(_duration(ms, DUR_BASE))
        anim.setStartValue(float(eff.opacity()))
        anim.setEndValue(float(max(0.0, min(1.0, to))))
        anim.setEasingCurve(curve)
        if on_done:
            anim.finished.connect(on_done)
        _store_anim(widget, anim)
        anim.start()
        return anim
    except Exception as exc:
        logger.debug(f"[motion] 透明度动画失败: {exc}")
        return None


def _slide(widget: QWidget, dy: int, ms: Optional[int],
           curve: QEasingCurve, fade: bool) -> None:
    """内部：从 (当前位置 + dy) 滑到当前位置，可叠加淡入。"""
    try:
        end_pos = widget.pos()
        start_pos = end_pos + __import__("PyQt5.QtCore", fromlist=["QPoint"]).QPoint(0, dy)
        anim = QPropertyAnimation(widget, b"pos", widget)
        anim.setDuration(_duration(ms, DUR_BASE))
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.setEasingCurve(curve)
        _store_anim(widget, anim)
        widget.move(start_pos)
        anim.start()
        if fade:
            eff = _ensure_effect(widget)
            eff.setOpacity(0.0)
            animate_opacity(widget, 1.0, ms, curve)
    except Exception as exc:
        logger.debug(f"[motion] 位移动画失败: {exc}")


def animate_press(widget: QWidget, ms: Optional[int] = None) -> None:
    """压印：从上方落下 + 淡入。

    用于新消息气泡、新卡片 —— 像盖章一样"落"到位，而不是淡出来。
    """
    try:
        end_pos = widget.pos()
        from PyQt5.QtCore import QPoint

        anim = QPropertyAnimation(widget, b"pos", widget)
        anim.setDuration(_duration(ms, 240))
        anim.setStartValue(end_pos + QPoint(0, -8))
        anim.setEndValue(end_pos)
        anim.setEasingCurve(EASE_DEFAULT)
        _store_anim(widget, anim)
        widget.move(end_pos + QPoint(0, -8))
        anim.start()
        _ensure_effect(widget).setOpacity(0.0)
        animate_opacity(widget, 1.0, _duration(ms, 240), EASE_DEFAULT)
    except Exception as exc:
        logger.debug(f"[motion] 压印动画失败: {exc}")


def animate_develop(widget: QWidget, ms: Optional[int] = None,
                    dy: int = 10) -> None:
    """显影：从下方浮起 + 淡入。用于列表项、提示条。"""
    _slide(widget, dy, ms, EASE_DEFAULT, fade=True)


def animate_file(widget: QWidget, ms: Optional[int] = None,
                 on_done: Optional[Callable[[], None]] = None) -> None:
    """归档：向外淡出 + 轻微下移。用于替换/清除旧元素。"""
    try:
        end_pos = widget.pos()
        from PyQt5.QtCore import QPoint

        anim = QPropertyAnimation(widget, b"pos", widget)
        anim.setDuration(_duration(ms, 200))
        anim.setStartValue(end_pos)
        anim.setEndValue(end_pos + QPoint(0, 6))
        anim.setEasingCurve(EASE_DEFAULT)
        _store_anim(widget, anim)
        anim.start()
        animate_opacity(widget, 0.0, _duration(ms, 200), EASE_DEFAULT, on_done)
    except Exception as exc:
        logger.debug(f"[motion] 归档动画失败: {exc}")


def stop_motion(widget: QWidget) -> None:
    """停掉组件上所有动画（清理时调用，避免野指针）。"""
    for anim in list(getattr(widget, "_motion_anims", []) or []):
        try:
            anim.stop()
        except RuntimeError:
            pass
    try:
        widget._motion_anims = []
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 里程计数字
# ---------------------------------------------------------------------------
class OdometerLabel(QLabel):
    """数字里程计：数值变化时滚动到目标值，而不是直接跳变。

    设计规范第 6 条：「数字 = 里程计」。用 `OutExpo` 缓动 —— 开头飞快、
    尾段几乎静止，读起来像机械计数器停稳。
    """

    valueChanged = pyqtSignal(float)

    def __init__(self, text: str = "", parent: Optional[QWidget] = None,
                 decimals: int = 0, duration: int = DUR_PANEL):
        super().__init__(text, parent)
        self._value = 0.0
        self._decimals = decimals
        self._duration = duration
        self._anim: Optional[QPropertyAnimation] = None
        self.setAlignment(Qt.AlignCenter)
        self._refresh_label()

    # -- 可动画属性 ------------------------------------------------------
    def getValue(self) -> float:
        return self._value

    def setValue(self, v: float) -> None:
        self._value = float(v)
        self._refresh_label()
        self.valueChanged.emit(self._value)

    value = pyqtProperty(float, fget=getValue, fset=setValue)

    def _refresh_label(self) -> None:
        fmt = f"{{:.{self._decimals}f}}"
        self.setText(fmt.format(self._value))

    def setNumber(self, target: float, animate: bool = True) -> None:
        """滚到目标值。"""
        target = float(target)
        if not animate or self._duration <= 0:
            self.setValue(target)
            return
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
        anim = QPropertyAnimation(self, b"value", self)
        anim.setDuration(self._duration)
        anim.setStartValue(self._value)
        anim.setEndValue(target)
        anim.setEasingCurve(EASE_SNAP)
        anim.start()
        self._anim = anim


# ---------------------------------------------------------------------------
# 线条按进度绘制
# ---------------------------------------------------------------------------
class DrawProgressBar(QProgressBar):
    """细线进度条：不是"填充"，而是"画出来"。

    莱茵生命规范第 6 条：「线条 = 按进度绘制」。视觉上是一条从左侧
    生长出来的线，末端带一个短亮块（机械限位器）。
    """

    def __init__(self, parent: Optional[QWidget] = None, height: int = 3):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(height)
        self.setRange(0, 100)
        self.setValue(0)

    def setAnimated(self, value: int, ms: int = DUR_PANEL) -> None:
        """平滑长到 value。"""
        anim = QPropertyAnimation(self, b"value", self)
        anim.setDuration(ms)
        anim.setStartValue(self.value())
        anim.setEndValue(int(value))
        anim.setEasingCurve(EASE_DEFAULT)
        _store_anim(self, anim)
        anim.start()
