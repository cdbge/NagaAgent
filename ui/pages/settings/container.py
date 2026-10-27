#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置页容器：对外只暴露 `apply_theme_style()`，内部是声明式 SettingsPage。

这样主窗口只认这个接口，换实现不影响调用方 —— 旧的
旧实现（widget_settings / settings_groups / settings_widgets）已随重构删除。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from .page import SettingsPage

__all__ = ["SettingsContainer"]


class SettingsContainer(QWidget):
    """设置页外壳。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SettingsPageHost")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.page = SettingsPage(self)
        lay.addWidget(self.page, 1)

    def apply_theme_style(self) -> None:
        """主题切换时刷新整页。"""
        try:
            self.page.apply_theme_style()
        except Exception:
            pass

    # 兼容旧调用：设置页里切换过数据时重新回填
    def load_current_settings(self) -> None:  # noqa: D401
        try:
            self.page.load_values()
        except Exception:
            pass
