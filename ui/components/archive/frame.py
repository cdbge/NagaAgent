# -*- coding: utf-8 -*-
"""取景框：四角 90° 直角框线。

单独放一个模块，因为 `__init__` 里已经 re-export 了 `rail` 的实现；
这里只做一次转出，避免两处都定义。
"""

from .rail import draw_viewfinder

__all__ = ["draw_viewfinder"]
