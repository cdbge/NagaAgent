#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用内心智云图页面。

设计要点
--------
1. **纯画布**：不显示工具条、标题、状态栏、边框与滚动条，只留图谱本身。
2. **无需按钮**：进入页面时自动判断数据是否比图谱新，是则自动重新生成；
   数据没变就直接加载，不浪费时间重排布局。
3. **保留手工入口**：右键菜单提供「重新生成 / 在浏览器打开 / 打开数据目录」，
   不占用界面空间。
4. **优雅降级**：缺少 PyQtWebEngine 时退回为提示 + 浏览器打开，不让界面崩掉。

原实现有两处问题：应用内的心智云图页其实是个空 QWidget（`QWidget()`），
点侧边栏只会把 graph.html 丢给外部浏览器；且侧边栏索引写反，点「心智云图」
实际切到了博弈页。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_KG_DIR = _REPO_ROOT / "data" / "logs" / "knowledge_graph"
_GRAPH_HTML = _KG_DIR / "graph.html"
_QUINTUPLES = _KG_DIR / "quintuples.json"

# PyQtWebEngine 在部分环境下可能缺失；缺失时优雅降级
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_OK = True
except Exception as _exc:  # pragma: no cover - 取决于运行环境
    QWebEngineView = None  # type: ignore
    _WEBENGINE_OK = False
    logger.warning(f"PyQtWebEngine 不可用，心智云图将退化为浏览器打开: {_exc}")


class MindMapWidget(QWidget):
    """心智云图页面（纯画布，无工具条）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_once = False
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        # 去掉所有外边距，让画布铺满整个页面
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if _WEBENGINE_OK:
            self.view = QWebEngineView(self)
            # 让应用自身的深色背景透出来：页面背景设为透明，WebView 也不画底色。
            # 图谱生成侧同时把 node/edge 文字改成了浅色，两边配合才不会出现
            # 「白底黑字」或「透明底黑字看不见」。
            try:
                self.view.page().setBackgroundColor(Qt.transparent)
                self.view.setStyleSheet("background: transparent;")
                self.setStyleSheet("background: transparent;")
                self.setAttribute(Qt.WA_TranslucentBackground, True)
            except Exception as exc:
                logger.warning(f"设置心智云图透明背景失败，将使用默认底色: {exc}")
            root.addWidget(self.view, 1)
            self.hint = None
        else:
            self.view = None
            self.hint = QLabel(
                "当前环境缺少 PyQtWebEngine，无法在应用内显示图谱。\n\n"
                "安装后即可在应用内查看：uv sync（或 pip install PyQtWebEngine）\n"
                "也可以右键选择「在浏览器打开」。"
            )
            self.hint.setAlignment(Qt.AlignCenter)
            self.hint.setWordWrap(True)
            self.hint.setStyleSheet("color: #909399; font-size: 13px;")
            root.addWidget(self.hint, 1)

        # 右键菜单承载全部操作，界面上不显示任何按钮
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # -------------------------------------------------------------- 右键菜单
    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("重新生成", self.regenerate)
        menu.addAction("在浏览器打开", self.open_in_browser)
        menu.addSeparator()
        menu.addAction("打开数据目录", self.open_data_dir)
        menu.exec_(self.mapToGlobal(pos))

    # -------------------------------------------------------------- 行为
    def _is_stale(self) -> bool:
        """图谱文件是否比数据旧（或不存在）。"""
        if not _GRAPH_HTML.exists():
            return True
        if not _QUINTUPLES.exists():
            return False
        try:
            return _QUINTUPLES.stat().st_mtime > _GRAPH_HTML.stat().st_mtime
        except OSError:
            return False

    def load_current(self):
        """加载已存在的 graph.html（不重新生成）。"""
        if self.view is None:
            return
        if not _GRAPH_HTML.exists():
            return
        self.view.load(QUrl.fromLocalFile(str(_GRAPH_HTML)))

    def regenerate(self):
        """重新生成图谱并加载到页面内。"""
        try:
            from core.summer_memory.quintuple_visualize_v2 import visualize_quintuples

            visualize_quintuples()
        except Exception as exc:
            logger.error(f"生成心智云图失败: {exc}")
            return
        self.load_current()

    def ensure_fresh(self):
        """进入页面时调用：数据比图谱新才重新生成，否则直接加载。"""
        if _WEBENGINE_OK and self._is_stale():
            self.regenerate()
        else:
            self.load_current()

    def open_in_browser(self):
        """在系统默认浏览器中打开（备用入口）。"""
        import webbrowser

        if not _GRAPH_HTML.exists():
            logger.warning("暂无图谱文件，无法在浏览器打开")
            return
        try:
            webbrowser.open(_GRAPH_HTML.as_uri())
        except Exception as exc:
            logger.error(f"打开浏览器失败: {exc}")

    def open_data_dir(self):
        """在资源管理器中打开图谱数据目录。"""
        import subprocess
        import sys

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(_KG_DIR)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(_KG_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(_KG_DIR)])
        except Exception as exc:
            logger.error(f"打开数据目录失败: {exc}")

    def cleanup(self):
        """释放 QWebEngineView。

        QWebEngineView 会拉起独立的渲染进程，进程退出前必须显式收掉，
        否则渲染进程会成为孤儿残留。页面原先没有任何清理入口。
        """
        try:
            view = getattr(self, "view", None)
            if view is not None:
                view.stop()
                view.setUrl(QUrl("about:blank"))
                view.deleteLater()
                self.view = None
                logger.info("心智云图视图已释放")
        except Exception as exc:
            logger.warning(f"释放心智云图视图失败（忽略）: {exc}")

    def showEvent(self, event):
        """首次显示时自动准备内容。"""
        super().showEvent(event)
        if self._loaded_once:
            return
        self._loaded_once = True
        self.ensure_fresh()


def create_mindmap_widget() -> QWidget:
    """工厂函数，供窗口构造时调用。"""
    return MindMapWidget()
