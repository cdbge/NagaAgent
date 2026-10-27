#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown → 带主题样式的 HTML。

为什么不再手写正则转换
======================

原实现 `simple_markdown_to_html()` 有四个会**破坏内容**的问题：

1. `_斜体_` 正则会把 `snake_case` 里的下划线吃掉 ——
   对代码助手是致命的（`get_service_info()` 变成 `get<i>service</i>info()`）；
2. 粗体/斜体替换跑在代码块之前，代码里的 `**` 被误伤；
3. 只把 `* item` 转成 `<li>`，没有 `<ul>` 包裹，列表渲染成孤立行；
4. 最后无差别 `\\n → <br>`，把 `<pre>` 里的换行也毁了。

现在用 **Python-Markdown**（已随依赖安装）做真正解析，再叠加主题 CSS：

* 标题、列表、表格、围栏代码、引用、链接、分隔线、脚注全部由库解析；
* 解析器正确处理转义与嵌套，不会误伤标识符；
* 输出 HTML 里注入主题色，QLabel 用 RichText 渲染。

没有 `markdown` 库时退回 Qt 自带的 `QTextDocument.setMarkdown()`。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["markdown_to_html"]

# Python-Markdown 扩展：
#   extra       —— 表格、脚注、属性列表等常用扩展合集
#   fenced_code —— ``` 围栏代码（extra 里已含，显式列出便于阅读）
#   sane_lists  —— 列表解析更符合直觉，避免相邻列表被合并
#   注意：**不要加 nl2br** —— 它会把 <pre><code> 里的换行也转成 <br>，
#   导致代码块被压成一行。段落之间用空行分隔即可。
_EXTENSIONS = ["extra", "fenced_code", "sane_lists"]


def _theme_css(t) -> str:
    """生成主题相关的 HTML CSS（Qt RichText 支持的子集）。"""
    return f"""
    body {{ color: {t.text}; }}
    p {{ color: {t.text}; margin: 0 0 6px 0; }}
    h1 {{ color: {t.accent}; font-size: 15pt; font-weight: 700; margin: 10px 0 6px 0; }}
    h2 {{ color: {t.accent}; font-size: 13pt; font-weight: 700; margin: 9px 0 5px 0; }}
    h3 {{ color: {t.text};  font-size: 12pt; font-weight: 600; margin: 8px 0 4px 0; }}
    h4, h5, h6 {{ color: {t.text_dim}; font-size: 11pt; font-weight: 600; margin: 6px 0 3px 0; }}
    b, strong {{ color: {t.text}; font-weight: 700; }}
    i, em {{ color: {t.text_dim}; font-style: italic; }}
    code {{
        background-color: {t.panel_3};
        color: {t.accent};
        font-family: 'JetBrains Mono', monospace;
        font-size: 10pt;
    }}
    pre {{
        background-color: {t.panel};
        color: {t.text};
        font-family: 'JetBrains Mono', monospace;
        font-size: 10pt;
        margin: 6px 0;
    }}
    pre code {{
        color: {t.text};
        background-color: transparent;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10pt;
    }}
    a {{ color: {t.accent}; text-decoration: none; }}
    blockquote {{
        color: {t.text_dim};
        background-color: {t.panel_2};
        font-style: italic;
        margin: 6px 0 6px 6px;
    }}
    ul, ol {{ margin: 4px 0 8px 0; }}
    li {{ color: {t.text}; margin: 2px 0; }}
    table {{ border: 1px solid {t.border}; margin: 6px 0; }}
    th {{
        background-color: {t.panel_3};
        color: {t.accent};
        border: 1px solid {t.border};
        padding: 3px 6px;
        font-weight: 600;
    }}
    td {{
        color: {t.text};
        border: 1px solid {t.border};
        padding: 3px 6px;
    }}
    hr {{ color: {t.divider}; }}
    """


def _harden_pre(html: str) -> str:
    """把 ``<pre>`` 内部的换行转成 ``<br>``。

    为什么需要：Qt 的富文本引擎渲染 `<pre>` 时会**折叠内部换行**，
    代码块被压成一行。换成显式 `<br>` 可以绕过这个行为，
    渲染结果稳定且与浏览器一致。
    """
    if "<pre" not in html:
        return html

    def _repl(m):
        inner = m.group(1)
        inner = inner.replace("\r\n", "\n").replace("\n", "<br>")
        return "<pre>" + inner + "</pre>"

    return re.sub(r"<pre[^>]*>(.*?)</pre>", _repl, html, flags=re.S)


def _wrap(inner: str, theme) -> str:
    """把片段包成 QLabel 可渲染的完整 HTML 文档（内嵌主题 CSS）。"""
    return (
        '<html><head><meta name="qrichtext" content="1" />'
        f'<style type="text/css">{_theme_css(theme)}</style>'
        f"</head><body>{_harden_pre(inner)}</body></html>"
    )


def _render_with_markdown(text: str) -> Optional[str]:
    """用 Python-Markdown 渲染；不可用时返回 None。"""
    try:
        import markdown as _md
    except Exception:
        return None
    try:
        return _md.markdown(text, extensions=_EXTENSIONS)
    except Exception as exc:
        logger.warning(f"[markdown] Python-Markdown 渲染失败: {exc}")
        return None


def _render_with_qt(text: str) -> Optional[str]:
    """退回 Qt 自带的 Markdown 解析（Qt 5.14+）。"""
    try:
        from PyQt5.QtGui import QTextDocument

        doc = QTextDocument()
        doc.setMarkdown(text)
        html = doc.toHtml()
        # Qt 会给 body 加白色底，去掉以免覆盖主题
        html = html.replace("background-color:#ffffff;", "")
        html = html.replace("background-color: #ffffff;", "")
        return html
    except Exception as exc:
        logger.warning(f"[markdown] Qt Markdown 渲染失败: {exc}")
        return None


def markdown_to_html(text: str, theme=None, fallback_plain: bool = True) -> str:
    """把 Markdown 文本转成带主题样式的 HTML。

    Args:
        text: Markdown 原文
        theme: `ui.styles.tokens.Theme`；为 None 时读当前主题
        fallback_plain: 两条渲染路径都失败时，是否退化为纯文本

    Returns:
        可直接喂给 `QLabel.setTextFormat(Qt.RichText)` 的 HTML
    """
    if not text:
        return ""

    try:
        if theme is None:
            from ui.styles.tokens import get_theme

            theme = get_theme()

        inner = _render_with_markdown(text)
        if inner is None:
            qt_html = _render_with_qt(text)
            if qt_html is not None:
                # Qt 输出已是完整文档，把主题 CSS 插到它的 <style> 里
                marker = '<style type="text/css">'
                if marker in qt_html:
                    return _harden_pre(
                        qt_html.replace(marker, marker + _theme_css(theme), 1))
                return _wrap(qt_html, theme)

        if inner is not None:
            return _wrap(inner, theme)

        if not fallback_plain:
            return text
        import html as _html

        return _wrap(_html.escape(text).replace("\n", "<br>"), theme)
    except Exception as exc:
        logger.warning(f"[markdown] 转换异常，退化为纯文本: {exc}")
        if not fallback_plain:
            return text
        import html as _html

        return _html.escape(text).replace("\n", "<br>")
