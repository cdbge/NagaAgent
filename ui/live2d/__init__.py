#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D 集成模块

对外只暴露真正在用的三件东西：渲染器、动画管理器、显示控件。
（原先还导出 config_manager 与两个 create_*_from_config 工厂，
它们已随死代码清理一并移除；Live2D 配置统一走 core.system.config 的
config.live2d，不再有第二套配置体系。）
"""

from .renderer import Live2DRenderer
from .animator import Live2DAnimator
from .widget import Live2DWidget

__all__ = [
    "Live2DRenderer",
    "Live2DAnimator",
    "Live2DWidget",
]
