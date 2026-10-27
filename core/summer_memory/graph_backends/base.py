#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图存储后端的统一接口。

设计目标
--------
把「五元组存到哪」与「业务逻辑怎么用」解耦，后端可插拔：

    kuzu    默认 —— 嵌入式图数据库，pip 装完即用，无需服务/端口/Docker
    neo4j   可选 —— 需要独立 Neo4j 服务，有相应需求的用户切换
    sqlite  兜底 —— 标准库自带，零依赖

所有后端实现同一套方法，上层（quintuple_graph / memory_manager）只依赖本接口。
新增后端只需实现 GraphBackend 并注册到 backends.get_backend()。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

# 五元组：(主体, 主体类型, 关系, 客体, 客体类型)
Quintuple = Tuple[str, str, str, str, str]


class GraphBackend:
    """图存储后端接口。

    实现约定：
    - 所有方法都不应抛异常到调用方；失败时返回空值/False 并自行记日志。
    - ``store`` 需幂等（重复写入同一条五元组不应产生重复边）。
    - ``query`` 语义：对主体/客体/关系/类型做子串匹配，去重后返回。
    """

    #: 后端标识（与 config.grag.graph_backend 对应）
    name: str = "base"

    def is_available(self) -> bool:
        """后端当前是否可用（依赖是否装好、服务是否连上）。"""
        raise NotImplementedError

    def store(self, quintuples: Sequence[Quintuple]) -> int:
        """写入五元组，返回成功写入（或已存在）的条数。"""
        raise NotImplementedError

    def query(self, keywords: Sequence[str], limit: int = 20) -> List[Quintuple]:
        """按关键词做子串匹配，返回命中的五元组列表。"""
        raise NotImplementedError

    def count(self) -> Dict[str, int]:
        """返回 {'entities': n, 'relations': m}；不可用时返回 0。"""
        return {"entities": 0, "relations": 0}

    def clear(self) -> bool:
        """清空该后端持有的数据。"""
        raise NotImplementedError

    def close(self) -> None:
        """释放资源（连接/句柄）。"""
        return None

    # 便于日志与诊断
    def __repr__(self) -> str:
        return f"<{type(self).__name__} available={self.is_available()}>"
