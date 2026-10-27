#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志初始化：级别、格式、第三方库噪音压制，统一在这里配置。

原先散在 main.py（约 20 行 `logging.getLogger(...).setLevel(...)`）和
`message_manager.py` 里各配一次，级别不一致，新增库时容易漏配。

用法（进程入口调用一次即可）：

    from core.system.logging_setup import setup_logging
    setup_logging()
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = ["setup_logging", "QUIET_LOGGERS"]

# 第三方库噪音压制：{logger 名: 级别}
# 这些库在 INFO/DEBUG 级别的输出对排查本项目的业务问题没有帮助，
# 只会把真正的日志淹掉。需要调试某个库时，改这里一处即可。
QUIET_LOGGERS = {
    # HTTP 客户端：每个请求都打一行
    "httpcore": logging.WARNING,
    "httpcore.http11": logging.WARNING,
    "httpcore.connection": logging.WARNING,
    "httpx": logging.WARNING,
    "urllib3": logging.WARNING,
    "aiohttp": logging.WARNING,
    # Live2D / OpenGL：启动时刷屏
    "live2d": logging.WARNING,
    "live2d.renderer": logging.WARNING,
    "live2d.animator": logging.WARNING,
    "live2d.widget": logging.WARNING,
    "live2d.config": logging.WARNING,
    "live2d.config_dialog": logging.WARNING,
    "OpenGL": logging.WARNING,
    "OpenGL.acceleratesupport": logging.WARNING,
    "OpenGL.plugins": logging.WARNING,
    # 服务框架：uvicorn 的 access log 在桌面应用里没有意义
    "uvicorn": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "uvicorn.error": logging.WARNING,
    # 其它
    "matplotlib": logging.WARNING,
    "PIL": logging.WARNING,
    "asyncio": logging.WARNING,
}

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: Optional[str] = None, force: bool = False) -> None:
    """初始化根 logger。

    Args:
        level: 根日志级别（默认 INFO，或读 `config.system.log_level`）
        force: 为 True 时重新配置已存在的 handler（测试/重载场景）
    """
    # 优先用配置里的级别；配置不可用时退回 INFO
    resolved = level
    if resolved is None:
        try:
            from core.system.config import config

            resolved = str(getattr(config.system, "log_level", "INFO") or "INFO").upper()
        except Exception:
            resolved = "INFO"
    numeric = getattr(logging, str(resolved).upper(), logging.INFO)

    try:
        logging.basicConfig(
            level=numeric,
            format=_FORMAT,
            datefmt=_DATE_FORMAT,
            force=force,
        )
    except TypeError:
        # Python < 3.8 没有 force 参数
        logging.basicConfig(level=numeric, format=_FORMAT, datefmt=_DATE_FORMAT)

    for name, lvl in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)


def setup_quiet_logging() -> None:
    """只压制第三方噪音，不动根 logger。

    供那些不想接管根 logger 的入口（如 standalone 脚本）使用。
    """
    for name, lvl in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)
