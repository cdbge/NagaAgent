#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐条核对被删除文件是否仍被引用（精确版）。

只认真正的 import 语句与 importlib 字符串，不再用「词是否出现」——
上一版把 README / core / logs 这类通用词也算命中，误报一片。

分类：
  DATA   非 .py 文件（日志、md、备份、xlsx）→ 无代码引用，天然安全
  PY     从路径推导点分模块名，查 import 语句与动态导入字符串
"""

import pathlib
import re
import subprocess

ROOT = pathlib.Path(r"D:\Desktop\NagaAgent")
SKIP = {".venv", ".git", "build", "dist", "__pycache__", "docs", "data"}

out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                     capture_output=True, text=True).stdout
deleted = [l[3:].strip() for l in out.splitlines() if l[:2].strip() in ("D", "RD")]

corpus = []
for f in ROOT.rglob("*.py"):
    if any(p in SKIP for p in f.parts):
        continue
    try:
        corpus.append(f.read_bytes().decode("utf-8-sig"))
    except Exception:
        pass
blob = "\n".join(corpus)

# 收集现存代码里所有 import 的模块名 + importlib 字符串
imported = set()
for m in re.finditer(r"(?m)^\s*from\s+([A-Za-z_][\w.]*)\s+import", blob):
    imported.add(m.group(1))
for m in re.finditer(r"(?m)^\s*import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*)", blob):
    for part in m.group(1).split(","):
        imported.add(part.strip())
for m in re.finditer(r"""import_module\(\s*["']([\w.]+)["']""", blob):
    imported.add(m.group(1))

# 只要顶层包被 import，整棵子树都算被引用
top_packages = {p.split(".")[0] for p in imported}


def module_path(rel: str) -> str | None:
    p = pathlib.PurePosixPath(rel)
    if p.suffix != ".py":
        return None
    parts = list(p.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


rows = []
for rel in deleted:
    mp = module_path(rel)
    if mp is None:
        rows.append((rel, "DATA", "非代码文件，无 import 风险"))
        continue
    # 只认「导入的正是该模块或其子模块」；
    # 反过来（mp 以 i 开头）会把所有 "from ui.xxx import" 都算成命中 ui.* 的删除项
    hits = [i for i in imported if i == mp or i.startswith(mp + ".")]
    if hits:
        rows.append((rel, "REF", "被引用于: " + ", ".join(sorted(hits)[:3])))
    else:
        rows.append((rel, "OK", ""))

# 汇总
from collections import Counter

cnt = Counter(r[1] for r in rows)
print(f"被删除 {len(rows)} 项：安全 {cnt['OK'] + cnt['DATA']} / 仍有引用 {cnt['REF']}")
print("=" * 84)

cur = None
for rel, kind, note in rows:
    top = pathlib.PurePosixPath(rel).parts[0]
    if top != cur:
        print(f"\n[{top}]")
        cur = top
    icon = {"OK": "  OK  ", "DATA": " DATA ", "REF": " !!   "}[kind]
    print(f"{icon} {rel:<60} {note}")

print("\n" + "=" * 84)
print(f"需处理（仍被 import）: {cnt['REF']} 项")
for rel, kind, note in rows:
    if kind == "REF":
        print(f"  !! {rel}  <-  {note}")
