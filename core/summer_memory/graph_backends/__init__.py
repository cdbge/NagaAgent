#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图存储后端包。

对外只暴露统一的接口与工厂：
    from core.summer_memory.graph_backends import get_backend, GraphBackend

后端实现各自独立文件，按需延迟导入（没装 kuzu/py2neo 也不会影响其它后端）：
    kuzu_backend.py    默认，嵌入式，无需服务
    neo4j_backend.py   可选，需独立 Neo4j 服务
    sqlite_backend.py  兜底，标准库
"""

from .base import GraphBackend, Quintuple
from .factory import get_backend, reset_backend

__all__ = ["GraphBackend", "Quintuple", "get_backend", "reset_backend"]
