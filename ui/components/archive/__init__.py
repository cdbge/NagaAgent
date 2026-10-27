# -*- coding: utf-8 -*-
"""档案式界面骨架：顶栏 / 页脚 / 边缘装置 / 取景框。

设计来源
========

逆推自莱茵生命档案册（详见 `docs/UI重构计划书.md`）：

* **顶栏** —— 左 LOGO + 副标，中偏右编号导航，最右状态码
* **页脚** —— 套准靶 / 色条 / 纸张信息 / 实时坐标
* **边缘装置** —— 莱茵用装订孔，少前用网格刻度
* **取景框** —— 四角 90° 直角框线

这些部件只负责"装置层"，不承载业务内容；业务页面挂在中间的内容区。
"""

from .header import ArchiveHeader
from .footer import ArchiveFooter
from .rail import ArchiveRail
from .frame import draw_viewfinder

__all__ = ["ArchiveHeader", "ArchiveFooter", "ArchiveRail", "draw_viewfinder"]
