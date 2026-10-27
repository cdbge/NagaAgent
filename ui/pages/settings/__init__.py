#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声明式设置页。

    ui/pages/settings/
    ├── spec.py      # Field / Section 规格 + 构造器
    ├── schema.py    # 全部设置项的声明表（加设置只改这里）
    ├── widgets.py   # SettingRow：把 Field 渲染成一行
    └── page.py      # SettingsPage：双栏骨架 + 即时生效

旧实现（SettingsGroupsMixin + ElegantSettingsWidget）把「控件创建、
信号绑定、取值回填、样式」全揉在一起，加一个设置要改 4 处；
重构后已连同其依赖一并删除。
"""

from .page import SettingsPage
from .spec import Field, Section

__all__ = ["SettingsPage", "Field", "Section"]
