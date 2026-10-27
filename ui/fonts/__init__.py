# -*- coding: utf-8 -*-
"""随包字体：在应用启动时注册，不依赖系统是否安装。

为什么用 `QFontDatabase.addApplicationFont` 而不是要求用户装字体
------------------------------------------------------------------
1. 打包后的 exe 在别人机器上跑，对方没装字体会静默回退成系统默认体，
   整个设计就垮了；
2. `addApplicationFont` 只影响当前进程，装上即用、退出即还原，
   不污染系统字体目录。

字体清单
--------
* **Montserrat**（Regular / Medium / Bold）—— 英文标题与标签。
  莱茵生命的机械感很大程度来自"全大写 + 大字距"的 Montserrat。
* **JetBrains Mono** —— 数字、编号、状态值等需要等宽的场合。
  设计规范里"数字=里程计"要求数字宽度一致，否则跳动时版面会抖。

中文不打包：思源黑体/Noto Sans SC 的完整字库 10 MB 以上，
而系统自带的"Microsoft YaHei UI"在观感上足够接近，且两条设计规范
的官方回退链里都包含它。

许可
----
Montserrat 与 JetBrains Mono 均为 SIL Open Font License 1.1，
允许随软件分发。全文见同目录 `OFL.txt`。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

__all__ = ["register_bundled_fonts", "FONT_DIR", "EN_DISPLAY", "MONO", "CN_SANS"]

FONT_DIR = Path(__file__).resolve().parent

# 逻辑字体名 -> 实际 family（用于 QSS / QFont 里引用）
EN_DISPLAY = "Montserrat"        # 英文标题、标签
MONO = "JetBrains Mono"          # 数字、编号、状态值

# 中文字体：优先随包（若有），否则系统雅黑
CN_SANS_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
)

CN_SANS = "Microsoft YaHei UI"   # 启动时按实际可用性修正

_registered = False


def _pick_chinese_family() -> str:
    """在已安装字体里挑一个可用的中文族。"""
    try:
        from PyQt5.QtGui import QFontDatabase

        installed = set(QFontDatabase().families())
        for name in CN_SANS_CANDIDATES:
            if name in installed:
                return name
    except Exception as exc:
        logger.debug(f"[fonts] 探测中文字体失败: {exc}")
    return "Microsoft YaHei"


def register_bundled_fonts() -> List[str]:
    """把 ui/fonts/ 下的字体注册到当前 Qt 进程。返回成功的 family 名列表。

    可重复调用（内部有幂等保护）。必须在创建 QApplication **之后**调用。
    """
    global _registered, CN_SANS

    if _registered:
        return []

    try:
        from PyQt5.QtGui import QFontDatabase
    except Exception as exc:
        logger.warning(f"[fonts] 无法导入 QFontDatabase，跳过字体注册: {exc}")
        return []

    loaded: List[str] = []
    for path in sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf")):
        try:
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                logger.warning(f"[fonts] 加载失败: {path.name}")
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                loaded.extend(families)
                logger.debug(f"[fonts] 已加载 {path.name} -> {families}")
            else:
                logger.warning(f"[fonts] {path.name} 没有可用家族名（可能是变量字体）")
        except Exception as exc:
            logger.warning(f"[fonts] 加载 {path.name} 异常: {exc}")

    CN_SANS = _pick_chinese_family()
    _registered = True
    logger.info(
        f"[fonts] 随包字体就绪: {sorted(set(loaded))}；中文字体: {CN_SANS}")
    return loaded
