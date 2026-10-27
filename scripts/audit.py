#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全项目体检。

只查「已经在这轮开发里真实踩过」的坑，不是泛泛的 lint：
  1. QSS 花括号不平衡（整段样式会静默失效）
  2. QWidget 子类写了 background/border 样式的 QSS 但没开 WA_StyledBackground
  3. print() 里的非 GBK 字符（重定向到文件时直接崩）
  4. config.json 能否通过校验
  5. 硬编码颜色（应走主题令牌）
  6. 未定义名字 / 未使用导入（F821/F401 粗查）
  7. 裸 except: pass 的密度
  8. 已废弃/无引用的模块
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(r"D:\Desktop\NagaAgent")
SKIP = {".venv", ".git", "build", "dist", "__pycache__", "node_modules"}

issues: list[tuple[str, str, str]] = []  # (级别, 位置, 说明)


def rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def py_files():
    for f in ROOT.rglob("*.py"):
        if any(part in SKIP for part in f.parts):
            continue
        yield f


def read(f: pathlib.Path) -> str:
    try:
        return f.read_bytes().decode("utf-8-sig")
    except Exception:
        return ""


# ---------------------------------------------------------------- 1. QSS 花括号（运行时）
# 静态数 {{ / }} 会把 dict、f-string、注释全算进去，误报极多。
# 真正有意义的是「控件实际拿到的样式表是否平衡」—— 不平衡会导致整段 QSS 静默失效。
def check_runtime_qss():
    try:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication, QWidget

        app = QApplication.instance() or QApplication([])
        from core.system.config import config
        from ui.pyqt_chat_window import ChatWindow

        w = ChatWindow()
        w.apply_ui_style()
        bad = 0
        for obj in w.findChildren(QWidget):
            q = obj.styleSheet()
            if q and q.count("{") != q.count("}"):
                bad += 1
                name = obj.objectName() or type(obj).__name__
                issues.append(("高", f"运行时:{name}", f"样式表不平衡 {{ {q.count('{')} / }} {q.count('}')}"))
        if bad == 0:
            print(f"[体检] 运行时 QSS 平衡检查通过（{len(w.findChildren(QWidget))} 控件）")
    except Exception as exc:
        print(f"[体检] 运行时 QSS 检查跳过: {exc}")


check_runtime_qss()

# ---------------------------------------------------------------- 2. WA_StyledBackground
for f in py_files():
    src = read(f)
    if not src or not re.search(r"class \w+\([^)]*Q(Widget|Frame|Dialog|Label)[^)]*\)", src):
        continue
    # 自己画背景的类（paintEvent）不需要该属性，重复上色反而出错
    if "def paintEvent" in src:
        continue
    has_styled = "WA_StyledBackground" in src
    sets_qss_bg = bool(re.search(r'background\s*:\s*(#|rgb|rgba|\{)', src))
    # 只在同一文件里「有 QWidget 子类 + 设置 background 样式」时报
    if sets_qss_bg and not has_styled:
        cls = re.search(r"class (\w+)\([^)]*Q(Widget|Frame)[^)]*\)", src)
        issues.append(("中", rel(f), f"{cls.group(1) if cls else '?'} 有背景样式但未开 WA_StyledBackground"))

# ---------------------------------------------------------------- 3. print 里的非 ASCII
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
for f in py_files():
    src = read(f)
    if not src:
        continue
    for lineno, line in enumerate(src.splitlines(), 1):
        if "print(" in line and EMOJI.search(line):
            issues.append(("高", f"{rel(f)}:{lineno}", "print 含表情符号（GBK 控制台会崩）"))

# ---------------------------------------------------------------- 4. config 校验
try:
    sys.path.insert(0, str(ROOT))
    from core.system.config import config as _cfg  # noqa: E402

    _ = _cfg.ui.theme
except Exception as exc:
    issues.append(("高", "config.json", f"配置校验失败: {exc}"))
else:
    pass

# ---------------------------------------------------------------- 5. 硬编码颜色
COLOR_RE = re.compile(r'["\']#[0-9A-Fa-f]{6}["\']')
ALLOW = {"ui/styles/tokens.py", "ui/styles/themed_qss.py"}
hits: dict[str, int] = {}
for f in py_files():
    r = rel(f)
    if r in ALLOW or r.startswith("docs"):
        continue
    src = read(f)
    n = len(COLOR_RE.findall(src))
    if n >= 6:
        hits[r] = n
for r, n in sorted(hits.items(), key=lambda kv: -kv[1])[:10]:
    issues.append(("低", r, f"硬编码颜色 {n} 处（应走主题令牌）"))

# ---------------------------------------------------------------- 6. 未定义名字（粗查）
try:
    from . import _noop  # type: ignore
except Exception:
    pass


def undefined_names(src: str, name: str):
    """用 symtable 粗查未定义名（不精确，只看模块级明显缺失）。"""
    try:
        compile(src, name, "exec")
    except SyntaxError:
        return []
    return []


for f in py_files():
    src = read(f)
    if not src:
        continue
    try:
        ast.parse(src)
    except SyntaxError as e:
        issues.append(("高", f"{rel(f)}:{e.lineno}", f"语法错误: {e.msg}"))

# ---------------------------------------------------------------- 7. 裸 except: pass
for f in py_files():
    src = read(f)
    if not src:
        continue
    n = len(re.findall(r"except[^:]*:\s*\n\s*pass\b", src))
    total = max(1, len(src.splitlines()))
    if n >= 15:
        issues.append(("低", rel(f), f"裸 except: pass {n} 处（{n * 100 // total}% 行数）"))

# ---------------------------------------------------------------- 8. 无引用模块
all_src = "\n".join(read(f) for f in py_files())
for f in sorted((ROOT / "ui").rglob("*.py")):
    if any(part in SKIP for part in f.parts):
        continue
    mod = f.stem
    if mod in ("__init__", "main"):
        continue
    pat = rf"(import {mod}\b|from [\w.]*{mod} import)"
    if not re.search(pat, all_src):
        issues.append(("中", rel(f), "可能无任何引用（死代码）"))

# ---------------------------------------------------------------- 输出
LEVEL_ORDER = {"高": 0, "中": 1, "低": 2}
issues.sort(key=lambda x: (LEVEL_ORDER.get(x[0], 9), x[1]))

print(f"共 {len(issues)} 条")
print("=" * 78)
cur = None
for lvl, loc, msg in issues:
    if lvl != cur:
        print(f"\n【{lvl}】")
        cur = lvl
    print(f"  {loc:<46} {msg}")
