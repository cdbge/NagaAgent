#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理知识图谱存量数据：两级审查后重建，并自动备份。

用法：
    python scripts/curate_memory.py            # 预演（只看报告，不改数据）
    python scripts/curate_memory.py --apply    # 实际清理（会先备份）
    python scripts/curate_memory.py --apply --no-llm   # 只用规则审查，不调模型

两级审查：
    1. 规则审查（memory_curator.curate）—— 免费、确定，拦掉碎片/代词/元讨论
    2. LLM 自我审查（memory_curator.review_with_llm）—— 判断是否值得长期记忆

安全措施：
    - 清理前把 quintuples.json 备份为 quintuples.<时间戳>.bak.json
    - 图后端清空后按审查结果重建；若重建失败，文件备份仍可用于恢复
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

KG_DIR = REPO / "data" / "logs" / "knowledge_graph"
QUINTUPLES = KG_DIR / "quintuples.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="清理知识图谱存量数据")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认仅预演）")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM 自我审查")
    ap.add_argument("--max-print", type=int, default=40, help="最多打印多少条明细")
    args = ap.parse_args()

    if not QUINTUPLES.exists():
        print(f"未找到 {QUINTUPLES}")
        return 1

    raw = json.loads(QUINTUPLES.read_text(encoding="utf-8"))
    rows = [tuple(r) for r in raw if isinstance(r, (list, tuple)) and len(r) >= 5]
    print(f"读取 {QUINTUPLES.name}: {len(rows)} 条")
    print()

    from core.summer_memory.memory_curator import curate, review_with_llm

    print("=" * 74)
    print("第 1 级：规则审查")
    print("=" * 74)
    res = curate(rows)
    s = res.summary()
    print(f"  {s['input']} 条 -> 保留 {s['kept']}，丢弃 {s['dropped']}，归一化 {s['rewritten']}")
    print("  丢弃原因 Top 8:")
    for why, c in sorted(s["by_reason"].items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {c:>4}  {why}")

    kept = res.kept
    if not args.no_llm:
        print()
        print("=" * 74)
        print("第 2 级：LLM 自我审查")
        print("=" * 74)
        try:
            kept, dropped = asyncio.run(review_with_llm(res.kept))
            print(f"  {len(res.kept)} 条 -> 保留 {len(kept)}，再丢弃 {len(dropped)}")
        except Exception as exc:
            print(f"  自我审查失败（保持规则审查结果）: {exc}")

    print()
    print("=" * 74)
    print(f"清理后保留 {len(kept)} 条")
    print("=" * 74)
    for q in kept[: args.max_print]:
        print(f"  {q[0]:<10} --{q[2]}--> {q[3]:<24} [{q[1]}/{q[4]}]")
    if len(kept) > args.max_print:
        print(f"  ... 还有 {len(kept) - args.max_print} 条")

    if not args.apply:
        print()
        print("（预演结束，未改动任何数据。加 --apply 实际执行）")
        return 0

    # ---- 备份 ----
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = KG_DIR / f"quintuples.{stamp}.bak.json"
    shutil.copy2(QUINTUPLES, backup)
    print()
    print(f"已备份原数据 -> {backup.name}")

    # ---- 写回文件 ----
    QUINTUPLES.write_text(
        json.dumps([list(q) for q in kept], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {QUINTUPLES.name}: {len(kept)} 条")

    # ---- 重建图后端 ----
    try:
        from core.summer_memory.graph_backends import get_backend, reset_backend

        reset_backend()
        backend = get_backend(force_new=True)
        if backend is None:
            print("图后端不可用，仅更新了文件（下次启动会以文件为准）")
            return 0
        print(f"图后端: {backend.name}，清理前 {backend.count()}")
        backend.clear()
        n = backend.store(kept)
        print(f"重建完成: 写入 {n} 条，现有 {backend.count()}")
    except Exception as exc:
        print(f"图后端重建失败（文件已更新，可据此恢复）: {exc}")
        return 1

    print()
    print("清理完成。如需回滚：把备份文件复制回 quintuples.json 并重启应用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
