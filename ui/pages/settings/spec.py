#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置项规格（声明式）。

设计来源
========

参考 dawiq / pydantic-config-ui 的思路：**先声明"有什么设置"，再由框架生成 UI**，
而不是每个分组手写一堆 QLabel + QWidget + 信号连接。

这里不依赖 pydantic，用轻量 dataclass 描述：
    Field(key="ui.theme", label="界面主题", kind="select", options=theme_options)

页面的职责就变成：遍历 Section → 遍历 Field → 生成一行控件。
加一个新设置 = 在 schema.py 里加一行，不用碰任何 UI 代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Tuple, Union

__all__ = ["Field", "Section", "TEXT", "SECRET", "TOGGLE", "SLIDER", "SELECT", "CHOICE"]

# 选项既可以是静态元组，也可以是回调（字体列表、模型列表这类要运行时取）
OptionSource = Union[Sequence[Tuple[str, Any]], Callable[[], Sequence[Tuple[str, Any]]]]


@dataclass
class Field:
    """一个设置项。"""

    #: 配置键，形如 "ui.theme"（组.字段）
    key: str
    #: 左侧标题
    label: str
    #: 控件类型：text / secret / toggle / slider / select
    kind: str = "text"
    #: 说明文字（弱化色那行）
    desc: str = ""

    # ---- text / secret ----
    placeholder: str = ""

    # ---- slider ----
    minimum: int = 0
    maximum: int = 255
    #: 内部值 = 滑块值 * scale（用于 0~1 的浮点设置）
    scale: float = 1.0
    #: 显示小数位（0 表示整数）
    decimals: int = 0
    #: 数值后缀，如 " px" / " ms"
    suffix: str = ""

    # ---- select ----
    #: 选项来源；元素为 (显示名, 存储值)
    options: Optional[OptionSource] = None
    #: 允许用户输入自定义值（下拉可编辑），如模型名
    editable: bool = False

    #: 依赖条件：返回 False 时该行隐藏（如本地模式才显示端口）
    visible_when: Optional[Callable[[], bool]] = None

    #: 变更后的额外回调（除写配置 + 刷新界面之外）
    on_change: Optional[Callable[[Any], None]] = None

    def resolve_options(self) -> Sequence[Tuple[str, Any]]:
        """取实际选项列表（支持回调）。"""
        src = self.options
        if callable(src):
            try:
                return src() or ()
            except Exception:
                return ()
        return src or ()

    def extra(self) -> dict:
        """额外元数据（给需要自定义的控件用）。"""
        return dict(self.__dict__)


@dataclass
class Section:
    """左侧的一个类别。"""

    number: int
    title: str
    #: 类别说明（页面顶部小字）
    hint: str = ""
    fields: list = field(default_factory=list)


# ------------------------------------------------------------------ 构造器
def TEXT(key, label, desc="", placeholder="", **kw) -> Field:
    return Field(key=key, label=label, kind="text", desc=desc,
                 placeholder=placeholder, **kw)


def SECRET(key, label, desc="", placeholder="", **kw) -> Field:
    return Field(key=key, label=label, kind="secret", desc=desc,
                 placeholder=placeholder, **kw)


def TOGGLE(key, label, desc="", **kw) -> Field:
    return Field(key=key, label=label, kind="toggle", desc=desc, **kw)


def SLIDER(key, label, minimum, maximum, desc="", scale=1.0, decimals=0,
           suffix="", **kw) -> Field:
    return Field(key=key, label=label, kind="slider", desc=desc,
                 minimum=minimum, maximum=maximum, scale=scale,
                 decimals=decimals, suffix=suffix, **kw)


def SELECT(key, label, options, desc="", editable=False, **kw) -> Field:
    return Field(key=key, label=label, kind="select", desc=desc,
                 options=options, editable=editable, **kw)


#: CHOICE 是 SELECT 的别名，语义更贴近"从固定档位里选"
CHOICE = SELECT
