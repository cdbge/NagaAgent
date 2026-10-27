#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kuzu 图存储后端（默认）。

为什么默认 Kuzu：它是**嵌入式**图数据库 —— `pip install kuzu` 就是一个库，
在 Python 进程内运行，不需要独立服务、端口或 Docker。相比 Neo4j 的
「装 Docker + 拉 821MB 镜像」，对个人工具的使用成本低得多（wheel 仅约 4.7MB）。

已知情况：KuzuDB 上游已归档（最后版本 0.11.3），但既有版本可正常使用。
若日后需要更活跃的方案，切换到 neo4j 后端即可（接口一致）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Sequence

from .base import GraphBackend, Quintuple

logger = logging.getLogger(__name__)

# 建表语句：节点表 + 关系表（Kuzu 是结构化图，需先声明 schema）
_DDL = (
    "CREATE NODE TABLE IF NOT EXISTS Entity("
    "name STRING, etype STRING, PRIMARY KEY(name))",
    "CREATE REL TABLE IF NOT EXISTS Rel(FROM Entity TO Entity, kind STRING)",
)

_STORE_CYPHER = (
    "MERGE (a:Entity {name: $h}) "
    "MERGE (b:Entity {name: $t}) "
    "ON MATCH SET a.etype = $ht, b.etype = $tt "
    "ON CREATE SET a.etype = $ht, b.etype = $tt "
    "MERGE (a)-[r:Rel {kind: $k}]->(b)"
)

_QUERY_CYPHER = """
MATCH (a:Entity)-[r:Rel]->(b:Entity)
WHERE a.name CONTAINS $kw OR b.name CONTAINS $kw OR r.kind CONTAINS $kw
   OR a.etype CONTAINS $kw OR b.etype CONTAINS $kw
RETURN DISTINCT a.name, a.etype, r.kind, b.name, b.etype
LIMIT $lim
"""


class KuzuBackend(GraphBackend):
    """基于 Kuzu 的嵌入式图后端。"""

    name = "kuzu"

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._db = None
        self._conn = None
        self._ready = False
        self._init_error = ""
        self._connect()

    # ---------- 内部 ----------
    def _connect(self) -> None:
        try:
            import kuzu  # 延迟导入：没装 kuzu 时只有本后端不可用
        except Exception as exc:
            self._init_error = f"未安装 kuzu: {exc}"
            logger.warning(f"[图存储] Kuzu 不可用（{self._init_error}）")
            return

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = kuzu.Database(str(self.db_path))
            self._conn = kuzu.Connection(self._db)
            for ddl in _DDL:
                self._conn.execute(ddl)
            self._ready = True
            logger.info(f"[图存储] Kuzu 就绪: {self.db_path}")
        except Exception as exc:
            self._init_error = str(exc)
            self._db = self._conn = None
            self._ready = False
            # Kuzu 为单写入者：同一数据库文件同时只能被一个进程打开。
            # 最常见的原因是「已经开了另一个 NagaAgent 实例」。
            if "lock" in str(exc).lower():
                logger.error(
                    f"[图存储] Kuzu 数据库被占用（{self.db_path}）。"
                    f"Kuzu 是单写入者模型：请确认没有第二个 NagaAgent 实例在运行。"
                )
            else:
                logger.warning(f"[图存储] Kuzu 初始化失败: {exc}")

    # ---------- 接口实现 ----------
    def is_available(self) -> bool:
        return self._ready and self._conn is not None

    def store(self, quintuples: Sequence[Quintuple]) -> int:
        if not self.is_available() or not quintuples:
            return 0
        ok = 0
        for item in quintuples:
            try:
                head, htype, rel, tail, ttype = (list(item) + ["", "", "", "", ""])[:5]
            except Exception:
                continue
            if not head or not rel or not tail:
                continue
            try:
                self._conn.execute(
                    _STORE_CYPHER,
                    {"h": str(head), "ht": str(htype or ""), "t": str(tail),
                     "tt": str(ttype or ""), "k": str(rel)},
                )
                ok += 1
            except Exception as exc:
                logger.debug(f"[图存储] Kuzu 写入失败 {item}: {exc}")
        return ok

    def query(self, keywords: Sequence[str], limit: int = 20) -> List[Quintuple]:
        if not self.is_available():
            return []
        out: List[Quintuple] = []
        seen = set()
        for kw in keywords or []:
            kw = str(kw).strip()
            if not kw:
                continue
            try:
                res = self._conn.execute(_QUERY_CYPHER, {"kw": kw, "lim": int(limit)})
                while res.has_next():
                    row = res.get_next()  # [a.name, a.etype, r.kind, b.name, b.etype]
                    tup = (row[0], row[1], row[2], row[3], row[4])
                    if tup not in seen:
                        seen.add(tup)
                        out.append(tup)
            except Exception as exc:
                logger.debug(f"[图存储] Kuzu 查询失败 kw={kw!r}: {exc}")
        return out

    def count(self) -> Dict[str, int]:
        if not self.is_available():
            return {"entities": 0, "relations": 0}
        try:
            e = self._conn.execute("MATCH (n:Entity) RETURN count(n)").get_next()[0]
            r = self._conn.execute("MATCH ()-[x:Rel]->() RETURN count(x)").get_next()[0]
            return {"entities": int(e), "relations": int(r)}
        except Exception:
            return {"entities": 0, "relations": 0}

    def clear(self) -> bool:
        if not self.is_available():
            return False
        try:
            self._conn.execute("MATCH (a:Entity)-[r:Rel]->(b:Entity) DELETE r")
            self._conn.execute("MATCH (n:Entity) DELETE n")
            return True
        except Exception as exc:
            logger.warning(f"[图存储] Kuzu 清空失败: {exc}")
            return False

    def close(self) -> None:
        self._conn = None
        self._db = None
        self._ready = False
