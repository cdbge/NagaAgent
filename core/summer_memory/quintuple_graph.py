#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GRAG 五元组存储与检索（后端可插拔）。

后端由 ``config.grag.graph_backend`` 决定：
    kuzu（默认） 嵌入式图数据库，pip 装完即用，无需服务/端口/Docker
    neo4j        可选，需独立 Neo4j 服务
    sqlite       兜底，标准库零依赖

实现见 ``graph_backends/``。本模块只保留业务语义与对外函数名，
**不再直接依赖 py2neo**，因此没装 Neo4j 也能正常使用记忆功能。

本地文件 ``data/logs/knowledge_graph/quintuples.json`` 始终作为可读快照保留：
图后端是查询加速层，文件是兜底与导出用。
"""

import json as _json
import logging
import os
import sys
from pathlib import Path

# 添加项目根目录到路径，以便导入 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

logger = logging.getLogger(__name__)

# 五元组本地快照文件（相对仓库根目录）
QUINTUPLES_FILE = "data/logs/knowledge_graph/quintuples.json"

# ---- 初始化后端 ----
# 保留 GRAG_ENABLED 语义（配置开关）；graph 变量保留为"后端对象"，
# 以便既有调用方 `from .quintuple_graph import graph` 不失效。
_backend = None
GRAG_ENABLED = False
graph = None

try:
    from core.system.config import config

    GRAG_ENABLED = bool(config.grag.enabled)
    if GRAG_ENABLED:
        from .graph_backends import get_backend

        _backend = get_backend()
        graph = _backend  # 兼容旧名字
        if _backend is None:
            print("[GRAG] 图存储后端不可用，记忆将仅保存到本地文件。", file=sys.stderr)
    else:
        print("[GRAG] GRAG 记忆系统已在配置中禁用。", file=sys.stderr)
except Exception as exc:  # 配置或后端导入失败都不应让程序起不来
    print(f"[GRAG] 初始化失败: {exc}", file=sys.stderr)
    GRAG_ENABLED = False
    _backend = None
    graph = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _quintuples_path() -> Path:
    p = Path(QUINTUPLES_FILE)
    return p if p.is_absolute() else _repo_root() / p


# ---------------- 本地文件快照 ----------------

def load_quintuples():
    """读取本地五元组快照。"""
    path = _quintuples_path()
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(tuple(x) for x in _json.load(f))
    except Exception as exc:
        logger.warning(f"[GRAG] 读取五元组文件失败: {exc}")
        return set()


def save_quintuples(quintuples):
    """写入本地五元组快照。"""
    path = _quintuples_path()
    try:
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump([list(x) for x in quintuples], f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        logger.error(f"[GRAG] 保存五元组文件失败: {exc}")
        return False


# ---------------- 对外：写入 ----------------

def store_quintuples(new_quintuples, *, curate_enabled: bool = True) -> bool:
    """存入五元组：先过记忆审查，再写入图后端 + 更新本地快照。

    这里是**唯一的写入收口**，因此把审查放在这一层，任何调用方都绕不过去。
    审查只做确定性规则（碎片/代词/元讨论/数量词等），零额外模型调用，
    不引入延迟。更细的「值不值得长期记忆」由抽取阶段与可选的 LLM 自我审查负责。
    """
    if not new_quintuples:
        return False

    items = [tuple(x) for x in new_quintuples]

    # 0) 记忆审查
    if curate_enabled:
        try:
            from .memory_curator import curate

            result = curate(items)
            if result.dropped_count:
                logger.info(
                    f"[GRAG] 记忆审查：{len(items)} 条 -> 保留 {result.kept_count} 条，"
                    f"丢弃 {result.dropped_count} 条"
                )
                for q, why in result.dropped[:5]:
                    logger.debug(f"[GRAG]   丢弃 {q[0]}--{q[2]}-->{q[3]}：{why}")
            for old, new, _ in result.rewritten[:5]:
                logger.debug(f"[GRAG]   归一化 {old[0]}->{new[0]}，{old[3]}->{new[3]}")
            items = result.kept
        except Exception as exc:
            # 审查本身出问题不应阻断记忆写入
            logger.warning(f"[GRAG] 记忆审查异常，按原样写入: {exc}")

    if not items:
        logger.info("[GRAG] 记忆审查后无合格条目，本次不写入")
        return False

    # 1) 本地快照（始终执行，作为兜底与导出）
    try:
        all_q = load_quintuples()
        all_q.update(items)
        save_quintuples(all_q)
    except Exception as exc:
        logger.warning(f"[GRAG] 更新本地快照失败: {exc}")

    # 2) 图后端
    if _backend is None:
        logger.info(f"[GRAG] 图后端未启用，仅保存 {len(items)} 个五元组到文件")
        return True

    try:
        stored = _backend.store(items)
        logger.info(f"[GRAG] 五元组写入 {_backend.name} 后端: {stored}/{len(items)}")
        return stored > 0
    except Exception as exc:
        logger.error(f"[GRAG] 写入图后端失败: {exc}")
        return False


# ---------------- 对外：检索 ----------------

def get_all_quintuples():
    return load_quintuples()


def query_graph_by_keywords(keywords, limit: int = 20):
    """按关键词检索五元组。

    走当前图后端；后端不可用时回退到本地快照的关键词匹配。
    """
    results = []

    if _backend is not None and _backend.is_available():
        try:
            results = list(_backend.query(list(keywords or []), limit=limit))
        except Exception as exc:
            logger.debug(f"[GRAG] 图后端查询失败，回退本地文件: {exc}")
            results = []

    if results:
        return results

    # 回退：本地快照关键词匹配
    try:
        kws = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        if not kws:
            return results
        for item in load_quintuples():
            if not isinstance(item, (list, tuple)) or len(item) < 5:
                continue
            joined = " ".join(str(x) for x in item)
            if any(kw in joined for kw in kws):
                results.append(tuple(item[:5]))
                if len(results) >= limit:
                    break
    except Exception as exc:
        logger.warning(f"[GRAG] 本地五元组回退检索失败: {exc}")

    return results


def get_backend_info():
    """当前后端信息，供 UI/诊断展示。"""
    if _backend is None:
        return {"backend": None, "available": False, "counts": {"entities": 0, "relations": 0}}
    try:
        counts = _backend.count()
    except Exception:
        counts = {"entities": 0, "relations": 0}
    return {
        "backend": getattr(_backend, "name", "unknown"),
        "available": bool(_backend.is_available()),
        "counts": counts,
    }
