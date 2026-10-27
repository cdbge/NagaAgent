#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 图存储后端（零依赖兜底）。

仅用 Python 标准库。存储为一张去重表，查询用 LIKE 子串匹配 ——
完全覆盖当前实现的查询语义（对主体/客体/关系/类型做 CONTAINS）。

当 Kuzu 或 Neo4j 不可用时可作为保底，保证「记忆」功能不会因为缺依赖而瘸腿。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Sequence

from .base import GraphBackend, Quintuple

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS quintuples (
    head       TEXT NOT NULL,
    head_type  TEXT,
    rel        TEXT NOT NULL,
    tail       TEXT NOT NULL,
    tail_type  TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(head, rel, tail)
);
CREATE INDEX IF NOT EXISTS idx_head ON quintuples(head);
CREATE INDEX IF NOT EXISTS idx_tail ON quintuples(tail);
CREATE INDEX IF NOT EXISTS idx_rel  ON quintuples(rel);
"""

_QUERY_SQL = """
SELECT head, head_type, rel, tail, tail_type
FROM quintuples
WHERE head LIKE ? OR tail LIKE ? OR rel LIKE ? OR head_type LIKE ? OR tail_type LIKE ?
LIMIT ?
"""


class SqliteBackend(GraphBackend):
    """基于标准库 sqlite3 的后端。"""

    name = "sqlite"

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ready = False
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.executescript(_DDL)
            self._conn.commit()
            self._ready = True
            logger.info(f"[图存储] SQLite 就绪: {self.db_path}")
        except Exception as exc:
            logger.warning(f"[图存储] SQLite 初始化失败: {exc}")
            self._conn = None
            self._ready = False

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
                    "INSERT OR IGNORE INTO quintuples(head,head_type,rel,tail,tail_type) "
                    "VALUES (?,?,?,?,?)",
                    (str(head), str(htype or ""), str(rel), str(tail), str(ttype or "")),
                )
                ok += 1
            except Exception as exc:
                logger.debug(f"[图存储] SQLite 写入失败 {item}: {exc}")
        try:
            self._conn.commit()
        except Exception:
            pass
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
            pat = f"%{kw}%"
            try:
                rows = self._conn.execute(
                    _QUERY_SQL, (pat, pat, pat, pat, pat, int(limit))
                ).fetchall()
            except Exception as exc:
                logger.debug(f"[图存储] SQLite 查询失败 kw={kw!r}: {exc}")
                continue
            for row in rows:
                tup = tuple(row)
                if tup not in seen:
                    seen.add(tup)
                    out.append(tup)
        return out

    def count(self) -> Dict[str, int]:
        if not self.is_available():
            return {"entities": 0, "relations": 0}
        try:
            rel = self._conn.execute("SELECT COUNT(*) FROM quintuples").fetchone()[0]
            ent = self._conn.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT head AS n FROM quintuples UNION SELECT tail FROM quintuples)"
            ).fetchone()[0]
            return {"entities": int(ent), "relations": int(rel)}
        except Exception:
            return {"entities": 0, "relations": 0}

    def clear(self) -> bool:
        if not self.is_available():
            return False
        try:
            self._conn.execute("DELETE FROM quintuples")
            self._conn.commit()
            return True
        except Exception as exc:
            logger.warning(f"[图存储] SQLite 清空失败: {exc}")
            return False

    def import_quintuples_json(self, json_path: str | Path) -> int:
        """从旧的 quintuples.json 导入（一次性迁移用）。"""
        p = Path(json_path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return 0
        return self.store([tuple(r[:5]) for r in data if isinstance(r, (list, tuple))])

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self._ready = False
