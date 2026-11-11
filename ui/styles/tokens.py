#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 设计令牌：三套主题的色板、字体、圆角与动效时长。

为什么需要这一层
================

在此之前，310 处颜色字面量散落在 16 个文件里（`ui/styles/settings_styles.py`
一个文件就有 95 处）。换肤意味着逐个文件改字符串，既容易漏、也无法保证
两套主题的结构一致。

改成「令牌 → 样式」两级之后：

* 颜色只在 `THEMES` 里定义一次；
* 组件只引用语义名（`t.accent` / `t.panel`），不关心具体色值；
* 切换主题 = 换一个 `Theme` 实例，重跑 `apply_ui_style()`。

三套主题
========

| key       | 名称             | 类型 | 来源 |
|-----------|------------------|------|------|
| `default` | 深空（默认）      | 深色 | 项目原有配色 |
| `gfl`     | 少女前线 · 战术   | 深色 | 少前百科主题 CSS 实测色值 |
| `rhine`   | 莱茵生命 · 档案   | **浅色** | 官方 PV / 官网实测设计令牌 |

色值依据
--------

**少女前线**取自 [少前百科](https://www.gfwiki.org/) 的站点主题 CSS
（`MediaWiki:Vector.css`）：正文 `#EAEAEA`、背景 `#333333`、
链接与强调 `#F4C430`、访问态 `#F28500`、警示 `#FF4444`、表头暗金 `#655219`。
这是一套经过长期实际使用的配色，不是凭感觉调的。

**莱茵生命**取自 [rhine-lab-motion](https://github.com/Rad-Weed/rhine-lab-motion)
的设计令牌（蒸馏自官方 PV《莱茵生命：访问》与官网实测）：
纸面 `#f6f3eb`、墨色 `#151513`、运行态橙 `#e9521c`、归档态朱红 `#b0243b`、
在线确认 lime `#b9e432`。

两者共同的纪律：**强调色只占 <10% 面积**，底色与文字吃掉 90% 以上。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "Theme",
    "THEMES",
    "DEFAULT_THEME_KEY",
    "theme_options",
    "get_theme",
    "get_theme_key",
    "rgba",
    "font_stack",
]

DEFAULT_THEME_KEY = "gfl"


@dataclass(frozen=True)
class Theme:
    """一套完整的视觉令牌。"""

    key: str
    label: str
    description: str
    is_light: bool

    # ── 底色 ──────────────────────────────────────────────
    bg: str             # 窗口底色
    panel: str          # 输入框 / 卡片
    panel_2: str        # 次级面板 / 悬停底
    panel_3: str        # 更深一档（表头、代码块）

    # ── 文字 ──────────────────────────────────────────────
    text: str           # 正文
    text_dim: str       # 次要文字
    text_mute: str      # 极弱（时间戳、提示）
    text_inv: str       # 强调色块上的反白字

    # ── 强调 ──────────────────────────────────────────────
    accent: str         # 主强调（交互、当前项）
    accent_deep: str    # 按下态 / 渐变端
    accent_soft: str    # 半透明强调底色（悬停、选中行）
    accent_alt: str     # 次强调（仅点缀）

    # ── 语义 ──────────────────────────────────────────────
    success: str
    warn: str
    danger: str

    # ── 结构 ──────────────────────────────────────────────
    border: str         # 常规描边
    border_strong: str  # 强调描边（聚焦）
    divider: str        # 分隔线
    overlay: str        # 弹层/遮罩

    # ── 形状 ──────────────────────────────────────────────
    radius_lg: int      # 窗口
    radius_md: int      # 卡片 / 输入框
    radius_sm: int      # 按钮 / 标签
    border_width: int   # 主描边宽度

    # ── 字体 ──────────────────────────────────────────────
    font_en: str = "Montserrat"
    font_cn: str = "Microsoft YaHei UI"
    font_mono: str = "JetBrains Mono"
    # 标签是否强制大写（莱茵生命/少女前线的英文标签都全大写）
    uppercase_labels: bool = True
    label_tracking: str = "1px"   # 英文标签字距

    # ── 动效（毫秒）────────────────────────────────────────
    dur_fast: int = 120
    dur_base: int = 300
    dur_slow: int = 600

    # ── 角色色（消息气泡）──────────────────────────────────
    bubble_user: str = ""      # 空则用 accent_soft
    bubble_ai: str = ""        # 空则用 panel

    extras: Dict[str, str] = field(default_factory=dict)



# 少女前线：深色战术 + 琥珀金。
# 色值全部取自少前百科站点主题 CSS 的实测值。
_GFL = Theme(
    key="gfl",
    label="少女前线 · 战术",
    description="深灰战术底 + 琥珀金强调，硬朗直角",
    is_light=False,
    bg="#2B2B2B",          # 比 #333 略深，为主区域留出层次
    panel="#252525",       # 代码块底（wiki 实测）
    panel_2="#333333",     # 主背景（wiki 实测）
    panel_3="#3D3D3D",
    text="#EAEAEA",        # wiki 正文
    text_dim="#C8C8C8",
    text_mute="#999999",   # wiki 次要文字
    text_inv="#1A1A1A",    # 琥珀金块上的深字
    accent="#F4C430",      # 琥珀金（wiki 链接/强调）
    accent_deep="#F28500", # 深橙（wiki 访问态）
    accent_soft="rgba(244, 196, 48, 38)",
    accent_alt="#F47130",  # 橙红（wiki a.new）
    success="#8BC34A",
    warn="#FFEBAD",        # 浅米金（wiki 标题色）
    danger="#FF4444",      # wiki 警示红
    border="rgba(153, 153, 153, 90)",   # wiki #999
    border_strong="#F4C430",
    divider="#444444",
    overlay="rgba(20, 20, 20, 220)",
    radius_lg=0,           # 战术终端：全直角，没有圆角
    radius_md=0,
    radius_sm=0,
    border_width=1,
    uppercase_labels=True,
    label_tracking="1.5px",
    bubble_user="rgba(244, 196, 48, 30)",
    bubble_ai="#303030",
    extras={
        # 表头暗金（wiki 实测）
        "header": "#655219",
        # 战术斜纹（警示条）
        "stripe_a": "#F4C430",
        "stripe_b": "#252525",
    },
)

# 莱茵生命：档案（纸）模式。
# 色值取自官方 PV / 官网实测的设计令牌。
_RHINE = Theme(
    key="rhine",
    label="莱茵生命 · 档案",
    description="暖纸底 + 墨色正文 + 运行态橙，印刷档案感",
    is_light=True,
    bg="#F6F3EB",          # --rl-paper
    panel="#FBFAF7",       # 卡片（比纸面更亮一档）
    panel_2="#E2E0DC",     # --rl-tab
    panel_3="#EFEDE7",
    text="#151513",        # --rl-ink
    text_dim="#3D3B37",
    text_mute="#8B8882",   # --rl-mute
    text_inv="#F2F0EB",    # --rl-ink-inv
    accent="#E9521C",      # --rl-orange（运行态）
    accent_deep="#E35D00", # --rl-orange-deep
    accent_soft="rgba(233, 82, 28, 26)",
    accent_alt="#B9E432",  # --rl-lime（在线确认）
    success="#6FA51E",     # lime 的深色版，浅底上才看得清
    warn="#B0243B",        # --rl-crimson（归档态）
    danger="#CD1A37",      # --rl-crimson-deep
    border="#C9C6C0",      # --rl-faint
    border_strong="#151513",
    divider="#C9C6C0",
    overlay="rgba(246, 243, 235, 230)",
    radius_lg=0,           # 印刷档案：纸没有圆角
    radius_md=0,
    radius_sm=0,
    border_width=1,
    uppercase_labels=True,
    label_tracking="1.2px",
    bubble_user="rgba(233, 82, 28, 22)",
    bubble_ai="#FBFAF7",
    extras={
        "header": "#B0243B",       # 归档态朱红用于分节
        "grid": "rgba(17, 18, 20, 0.06)",
        "grid_hex": "rgba(17, 18, 20, 0.08)",
        "caption": "#8B8882",
    },
)


THEMES: Dict[str, Theme] = {
    "gfl": _GFL,
    "rhine": _RHINE,
}

# 设置页下拉用：(显示名, 键)
_ORDER = ("gfl", "rhine",)


def theme_options():
    """返回 [(显示名, 主题键)]，供下拉框使用。"""
    return [(THEMES[k].label, k) for k in _ORDER if k in THEMES]


#: 是否已做过主题键迁移（只跑一次）
_migrated = False


def migrate_theme_key() -> None:
    """配置里的主题键若已不存在（例如已移除的 default），回退并写回。

    只在首次调用时执行；写盘失败也不影响本次运行（内存里已改）。
    """
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        from core.system.config import config

        cur = str(getattr(config.ui, "theme", "") or "").strip().lower()
        if cur and cur not in THEMES:
            config.ui.theme = DEFAULT_THEME_KEY
            logger.info(
                f"[tokens] 主题 {cur!r} 已移除，回退到 {DEFAULT_THEME_KEY}")
            try:
                from core.system.config_manager import update_config

                update_config({"ui": {"theme": DEFAULT_THEME_KEY}})
            except Exception:
                pass
    except Exception:
        pass


def get_theme_key() -> str:
    """读当前主题键；配置不可用或值非法时回退默认主题。"""
    migrate_theme_key()
    try:
        from core.system.config import config

        key = str(getattr(config.ui, "theme", DEFAULT_THEME_KEY) or "").strip().lower()
    except Exception:
        key = DEFAULT_THEME_KEY
    return key if key in THEMES else DEFAULT_THEME_KEY


def get_theme(key: Optional[str] = None) -> Theme:
    """取主题实例。不能抛异常 —— 调用方遍布整个 UI。"""
    if key is None:
        key = get_theme_key()
    theme = THEMES.get(str(key).strip().lower())
    if theme is None:
        logger.debug(f"[tokens] 未知主题 {key!r}，回退 {DEFAULT_THEME_KEY}")
        theme = THEMES[DEFAULT_THEME_KEY]
    # 中文字体跟随实际可用性（随包字体注册后可能变化）
    try:
        from ui.fonts import CN_SANS

        if CN_SANS and CN_SANS != theme.font_cn:
            theme = Theme(**{**theme.__dict__, "font_cn": CN_SANS})
    except Exception:
        pass
    return theme


# ---------------------------------------------------------------------------
# 颜色工具
# ---------------------------------------------------------------------------
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def rgba(color: str, alpha: int) -> str:
    """把 #rgb / #rrggbb 转成 Qt 认识的 rgba()。已是 rgba() 则原样返回。

    Args:
        color: 颜色字符串
        alpha: 0–255
    """
    if not color:
        return "transparent"
    if color.startswith("rgba(") or color.startswith("rgb("):
        return color
    m = _HEX_RE.match(color.strip())
    if not m:
        return color
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {max(0, min(255, int(alpha)))})"


def font_stack(theme: Theme, kind: str = "cn") -> str:
    """返回 QSS 的 font-family 值。

    kind: `cn` 中文正文 / `en` 英文标题 / `mono` 等宽数字
    """
    if kind == "en":
        return f"'{theme.font_en}', '{theme.font_cn}', sans-serif"
    if kind == "mono":
        return f"'{theme.font_mono}', 'Consolas', monospace"
    return f"'{theme.font_cn}', '{theme.font_en}', sans-serif"
