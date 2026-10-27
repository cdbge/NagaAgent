#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间工具的单一来源。

背景
----
各个服务里都有一份自己的 ``_now_iso()``，而且实现不一致：

* ``servers/agentserver/agent_server.py``  -> ``datetime.now().isoformat()``
  （**本地时间、无时区标记**）
* ``servers/mcpserver/mcp_server.py``       -> ``datetime.utcnow().isoformat() + "Z"``
  （**UTC**）

于是同一个字段 ``created_at`` / ``completed_at`` 在两个服务里语义不同：
跨服务比较时间会差一个时区（本机实测差 8 小时），
任何「哪个任务先完成」的判断都不可靠。

统一为 **UTC + Z 后缀**（ISO 8601，可跨服务直接比较）。
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["now_iso_utc", "parse_iso_utc"]


def now_iso_utc() -> str:
    """当前 UTC 时间的 ISO 8601 字符串，带 ``Z`` 后缀。

    例：``2026-10-06T14:54:38.270385Z``

    与 ``datetime.utcnow().isoformat() + "Z"`` 等价，但使用
    ``datetime.now(timezone.utc)`` —— ``utcnow()`` 在 Python 3.12+ 已弃用，
    且返回的是 naive datetime（没有时区信息，容易被误当本地时间）。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso_utc(value: str) -> datetime:
    """解析 ``now_iso_utc()`` 产物（或任意 ISO 8601），返回**带时区**的 datetime。

    兼容历史上写成本地时间（无时区后缀）的旧值：这种情况下按本地时区解释，
    保证不抛异常。新写入的值一律带 ``Z``。
    """
    if not value:
        raise ValueError("空时间字符串")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        # 旧数据：无时区 -> 按本地时区补上，避免 naive/aware 比较报错
        dt = dt.astimezone()
    return dt
