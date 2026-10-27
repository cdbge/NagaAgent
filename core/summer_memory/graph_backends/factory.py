#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图存储后端工厂：按配置选择后端，不可用时自动降级。

选择顺序（config.grag.graph_backend 指定首选）：

    kuzu    ->  kuzu 不可用  -> sqlite   （默认链路，全部零服务）
    neo4j   ->  neo4j 不可用 -> kuzu -> sqlite
    sqlite  ->  sqlite

这样无论用户是否装了图数据库服务，记忆功能都不会瘸腿。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .base import GraphBackend, Quintuple

logger = logging.getLogger(__name__)

__all__ = ["GraphBackend", "Quintuple", "get_backend", "reset_backend"]

# 进程内单例：图存储连接较重，避免每次查询都重连
_instance: Optional[GraphBackend] = None
_instance_backend: str = ""


def _repo_root() -> Path:
    # 本文件: <root>/core/summer_memory/graph_backends/__init__ 或 backends.py
    return Path(__file__).resolve().parent.parent.parent.parent


def _try_kuzu(db_path: str) -> Optional[GraphBackend]:
    try:
        from .kuzu_backend import KuzuBackend
    except Exception as exc:
        logger.debug(f"[图存储] 无法导入 Kuzu 后端: {exc}")
        return None
    backend = KuzuBackend(db_path)
    return backend if backend.is_available() else None


def _try_neo4j(cfg) -> Optional[GraphBackend]:
    try:
        from .neo4j_backend import Neo4jBackend
    except Exception as exc:
        logger.debug(f"[图存储] 无法导入 Neo4j 后端: {exc}")
        return None
    backend = Neo4jBackend(
        uri=cfg.neo4j_uri,
        user=cfg.neo4j_user,
        password=cfg.neo4j_password,
        database=getattr(cfg, "neo4j_database", "neo4j"),
    )
    return backend if backend.is_available() else None


def _try_sqlite(db_path: str) -> Optional[GraphBackend]:
    try:
        from .sqlite_backend import SqliteBackend
    except Exception as exc:
        logger.debug(f"[图存储] 无法导入 SQLite 后端: {exc}")
        return None
    backend = SqliteBackend(db_path)
    return backend if backend.is_available() else None


def get_backend(force_new: bool = False) -> Optional[GraphBackend]:
    """获取当前图存储后端（单例）。"""
    global _instance, _instance_backend

    if _instance is not None and not force_new:
        return _instance

    try:
        from core.system.config import config
        cfg = config.grag
    except Exception as exc:
        logger.warning(f"[图存储] 读取配置失败，降级为 sqlite: {exc}")
        cfg = None

    want = (getattr(cfg, "graph_backend", "kuzu") or "kuzu").strip().lower()

    root = _repo_root()
    kuzu_path = str(root / getattr(cfg, "kuzu_db_path", "data/graph.kuzu")) if cfg else str(root / "data/graph.kuzu")
    sqlite_path = str(root / "data" / "graph.sqlite3")

    order: List[str]
    if want == "neo4j":
        order = ["neo4j", "kuzu"]
    elif want == "sqlite":
        order = ["sqlite"]
    else:
        # 默认：kuzu 优先。**故意不自动回退到 sqlite** —— 否则一旦 kuzu 被占用
        # （例如开了第二个实例），数据会一半写进 sqlite、一半留在 kuzu，
        # 造成"记忆时有时无"且极难排查。此处宁可降级到本地文件快照
        # （quintuple_graph 已内置该回退），并给出明确告警。
        order = ["kuzu"]

    for name in order:
        backend = None
        if name == "kuzu":
            backend = _try_kuzu(kuzu_path)
        elif name == "neo4j" and cfg is not None:
            backend = _try_neo4j(cfg)
        elif name == "sqlite":
            backend = _try_sqlite(sqlite_path)
        if backend is not None:
            _instance = backend
            _instance_backend = name
            if name != want:
                logger.info(f"[图存储] 首选 {want} 不可用，已降级为 {name}")
            else:
                logger.info(f"[图存储] 使用后端: {name}")
            return backend

    logger.error(
        "[图存储] 首选后端不可用，记忆将退化为本地文件快照"
        "（data/logs/knowledge_graph/quintuples.json）。"
        "若为 Kuzu 且提示数据库被占用，请检查是否有第二个实例在运行；"
        "也可将 grag.graph_backend 改为 sqlite 使用零依赖后端。"
    )
    _instance = None
    _instance_backend = ""
    return None


def reset_backend() -> None:
    """释放并清除单例（供测试或切换后端时调用）。"""
    global _instance, _instance_backend
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
    _instance = None
    _instance_backend = ""
