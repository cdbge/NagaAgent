#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON 配置文件读取工具。

背景（重要）
------------
项目里的 ``config.json.example`` 使用带注释的 JSON 风格（``# 说明``）。
但 PyPI 上的 ``json5`` 包**并不支持注释**（0.9 ~ 0.15 各版本实测都会报
``Unexpected " "``），历史上代码里"json5 支持带注释解析"的说法是不成立的：
注释实际上是被下面这种兜底逻辑丢掉的::

    line.split('#')[0]

这种朴素写法会把**字符串值里的 ``#`` 一起截断**（例如 ``"#fff"``、URL 片段），
一旦谁在配置值里加了 ``#`` 就会静默出错。

这里提供一个**识别字符串字面量**的注释剥离实现，作为规范做法。
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union

__all__ = [
    "strip_json_comments",
    "loads_with_comments",
    "detect_encoding",
    "read_config_text",
    "load_config_json",
    "resolve_write_encoding",
    "dump_config_json",
]


def strip_json_comments(text: str) -> str:
    """去掉 JSON 文本中的 ``#`` 与 ``//`` 注释，但保留字符串内的内容。

    逐字符扫描，跟踪是否处于字符串字面量及其转义状态，因此
    ``{"color": "#fff"}`` 不会被破坏。

    无注释时直接返回：扫描是纯 Python 逐字符循环（实测约 90 ns/字符），
    而运行时写回的配置文件通常已经不含注释，先做一次 C 层判断可以
    整段省掉扫描。

    注意 ``//`` 的判定要先排掉 ``://`` —— 配置里的 URL
    （如 ``https://api.deepseek.com``）含有 ``//``，若直接判
    ``"//" in text``，每一份配置都会被误判成「有注释」。
    """
    # 快速路径：没有任何注释起始符
    if "#" not in text and "/*" not in text and "//" not in text.replace("://", ""):
        return text

    out = []
    in_string = False
    quote = ""
    escaped = False

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            i += 1
            continue

        # 不在字符串中
        if ch in ('"', "'"):
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        # 行注释：// 或 #
        if ch == "#" or (ch == "/" and i + 1 < n and text[i + 1] == "/"):
            # 跳到行尾，保留换行
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        # 块注释 /* ... */
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def loads_with_comments(text: str) -> Dict[str, Any]:
    """剥离注释后用标准 json 解析。"""
    import json

    return json.loads(strip_json_comments(text))


# --------------------------------------------------------------------------
# 文件级读写：配置文件的编码检测与读写统一在这里，避免各处各写一份
# --------------------------------------------------------------------------

#: 项目对配置文件使用的编码（新建文件时）
DEFAULT_CONFIG_ENCODING = "utf-16"

#: 读取失败时依次尝试的编码
_FALLBACK_READ = ("utf-8-sig", "utf-8", "utf-16", "gbk")


def detect_encoding(path: Union[str, Path]) -> Optional[str]:
    """用 charset_normalizer 检测文件编码；检测不到返回 ``None``。"""
    from charset_normalizer import from_path

    results = from_path(str(path))
    if not results:
        return None
    best = results.best()
    return best.encoding if best else None


def read_config_text(path: Union[str, Path]) -> str:
    """读取配置文件文本。

    优先用自动检测到的编码；检测失败或解码失败时按常见编码依次回退，
    因此调用方不必再自己写 try/except 与回退分支。
    """
    path = str(path)
    candidates = []
    detected = detect_encoding(path)
    if detected:
        candidates.append(detected)
    for enc in _FALLBACK_READ:
        if enc not in candidates:
            candidates.append(enc)

    last_error: Optional[Exception] = None
    for enc in candidates:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError) as e:
            last_error = e
            continue
    raise ValueError(f"无法以任何已知编码读取 {path}: {last_error}")


def load_config_json(path: Union[str, Path]) -> Dict[str, Any]:
    """读取配置文件：自动检测编码 + 剥离 ``#`` 注释 + 标准 JSON 解析。"""
    return loads_with_comments(read_config_text(path))


def resolve_write_encoding(path: Union[str, Path]) -> str:
    """决定写回配置文件时应使用的编码。

    规则：

    * 文件不存在 → 用项目约定 ``utf-16``；
    * 检测结果为 ``ascii`` → **升级为 ``utf-8``**。纯 ASCII 文件被检测成
      ``ascii`` 是正常现象，但按 ``ascii`` 写回时只要内容出现中文就会抛
      ``UnicodeEncodeError``；ASCII 是 UTF-8 的子集，写成 UTF-8 更安全，
      且读回结果完全一致；
    * 其余情况保持原编码，避免改变既有文件的格式（如 UTF-16 + BOM）。
    """
    p = Path(path)
    if not p.exists():
        return DEFAULT_CONFIG_ENCODING
    detected = detect_encoding(p)
    if not detected:
        return "utf-8"
    if detected.lower().replace("_", "-") == "ascii":
        return "utf-8"
    return detected


def dump_config_json(path: Union[str, Path],
                     data: Dict[str, Any],
                     indent: int = 2) -> str:
    """按原编码写回配置文件，返回实际使用的编码。

    使用 ``resolve_write_encoding()`` 选择编码，因此不会把 UTF-16 的配置文件
    写成 UTF-8，也不会因检测到 ``ascii`` 而在写入中文时崩溃。
    """
    import json

    encoding = resolve_write_encoding(path)
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    with open(str(path), "w", encoding=encoding) as f:
        f.write(text)
    return encoding
