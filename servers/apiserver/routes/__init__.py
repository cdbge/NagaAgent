#!/usr/bin/env python3
"""API 路由包。

按域拆分自 `api_server.py`：system / chat / sessions / tools / intent / ui。
每个模块导出一个 `router`，由 `api_server.py` 末尾统一注册。
"""

from . import system  # noqa: F401
from . import chat  # noqa: F401
from . import sessions  # noqa: F401
from . import tools  # noqa: F401
from . import intent  # noqa: F401
from . import ui  # noqa: F401

__all__ = ["system", "chat", "sessions", "tools", "intent", "ui"]
