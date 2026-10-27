#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neo4j 图存储后端（可选）。

适用于需要独立图数据库服务的用户：Neo4j 需要自行运行服务（Docker 或本地安装），
默认端口 7687。查询语言为 Cypher，能力与 Kuzu 后端一致。

切换方式：config.json 的 ``grag.graph_backend`` 设为 ``"neo4j"``。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence

from .base import GraphBackend, Quintuple

logger = logging.getLogger(__name__)


class Neo4jBackend(GraphBackend):
    """基于 py2neo 的 Neo4j 后端。"""

    name = "neo4j"

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._graph = None
        self._ready = False
        self._init_error = ""
        self._connect()

    def _connect(self) -> None:
        try:
            from py2neo import Graph
        except Exception as exc:
            self._init_error = f"未安装 py2neo: {exc}"
            logger.warning(f"[图存储] Neo4j 不可用（{self._init_error}）")
            return
        try:
            graph = Graph(self.uri, auth=(self.user, self.password), name=self.database)
            # 触发一次真实通信以确认服务可达
            graph.service.kernel_version
            self._graph = graph
            self._ready = True
            logger.info(f"[图存储] Neo4j 就绪: {self.uri}")
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning(
                f"[图存储] Neo4j 连接失败（{exc}）；"
                f"如需无服务方案，可将 grag.graph_backend 改为 kuzu"
            )
            self._graph = None
            self._ready = False

    def is_available(self) -> bool:
        return self._ready and self._graph is not None

    def store(self, quintuples: Sequence[Quintuple]) -> int:
        if not self.is_available() or not quintuples:
            return 0
        try:
            from py2neo import Node, Relationship
        except Exception:
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
                h_node = Node("Entity", name=str(head), entity_type=str(htype or ""))
                t_node = Node("Entity", name=str(tail), entity_type=str(ttype or ""))
                r = Relationship(h_node, str(rel), t_node,
                                 head_type=str(htype or ""), tail_type=str(ttype or ""))
                self._graph.merge(h_node, "Entity", "name")
                self._graph.merge(t_node, "Entity", "name")
                self._graph.merge(r)
                ok += 1
            except Exception as exc:
                logger.debug(f"[图存储] Neo4j 写入失败 {item}: {exc}")
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
            # 用参数化查询，避免把关键词直接拼进 Cypher
            cypher = (
                "MATCH (e1:Entity)-[r]->(e2:Entity) "
                "WHERE e1.name CONTAINS $kw OR e2.name CONTAINS $kw "
                "   OR type(r) CONTAINS $kw "
                "   OR e1.entity_type CONTAINS $kw OR e2.entity_type CONTAINS $kw "
                "RETURN e1.name, e1.entity_type, type(r), e2.name, e2.entity_type "
                "LIMIT $lim"
            )
            try:
                rows = self._graph.run(cypher, kw=kw, lim=int(limit)).data()
            except Exception as exc:
                logger.debug(f"[图存储] Neo4j 查询失败 kw={kw!r}: {exc}")
                continue
            for rec in rows:
                tup = (rec.get("e1.name"), rec.get("e1.entity_type"),
                       rec.get("type(r)"), rec.get("e2.name"), rec.get("e2.entity_type"))
                if tup not in seen:
                    seen.add(tup)
                    out.append(tup)
        return out

    def count(self) -> Dict[str, int]:
        if not self.is_available():
            return {"entities": 0, "relations": 0}
        try:
            e = self._graph.run("MATCH (n:Entity) RETURN count(n) AS c").data()[0]["c"]
            r = self._graph.run("MATCH ()-[x]->() RETURN count(x) AS c").data()[0]["c"]
            return {"entities": int(e), "relations": int(r)}
        except Exception:
            return {"entities": 0, "relations": 0}

    def clear(self) -> bool:
        if not self.is_available():
            return False
        try:
            self._graph.run("MATCH ()-[r]->() DELETE r")
            self._graph.run("MATCH (n:Entity) DELETE n")
            return True
        except Exception as exc:
            logger.warning(f"[图存储] Neo4j 清空失败: {exc}")
            return False

    def close(self) -> None:
        self._graph = None
        self._ready = False
