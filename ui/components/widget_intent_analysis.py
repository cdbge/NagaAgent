#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「博弈图」页 —— 后台意图分析的可视化。

背景
----
「博弈论」是这套后台机制的历史叫法：它分析对话、发现潜在任务，再通过 MCP
把工具调用分发出去（实现见 `core/system/background_analyzer.py`）。
此前这个页面只是个空 `QWidget()`，点进来一片空白；而日志里满屏的 `[博弈论]`
又让人以为有个博弈系统在跑。这里把它做成**真正的观测面板**。

数据来源：`servers/apiserver` 的 `/intent_analysis/*` 端点。
UI 不直接 import 服务层（见 ui/README 的分层约定），一律走 HTTP；
请求放在 QThread 里，避免阻塞界面线程。
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_REFRESH_MS = 3000

# 状态 -> (中文名, 颜色)
_STATUS = {
    "ok": ("已调度", "#67C23A"),
    "empty": ("无任务", "#909399"),
    "skipped": ("跳过", "#E6A23C"),
    "timeout": ("超时", "#F56C6C"),
    "error": ("失败", "#F56C6C"),
}

_STYLE = """
/* 背景全部透明：让主窗口的深色半透明底透出来。
   QScrollArea 的 viewport 是独立子控件，只写 QScrollArea{background:...}
   不会影响它，默认仍会填白 —— 这正是"纯白背景"的来源，必须一并置透明。 */
QWidget#iaRoot, QWidget#iaListHost { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }

QLabel#iaTitle { color: #F5F6FA; font-size: 15px; font-weight: 600; }
QLabel#iaPill  { font-size: 12px; padding: 2px 10px; border-radius: 9px; }

QPushButton#iaBtn {
    background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.22);
    border-radius: 6px; padding: 5px 12px; color: #F0F2F7; font-size: 12px;
}
QPushButton#iaBtn:hover   { background: rgba(255,255,255,0.18); }
QPushButton#iaBtn:pressed { background: rgba(255,255,255,0.26); }
QPushButton#iaBtn:disabled{ color: #8A909C; }

QFrame#iaCard {
    background: rgba(255,255,255,0.075);
    border: 1px solid rgba(255,255,255,0.16);
    border-radius: 8px;
}
QLabel#iaTime  { color: #B4BBC7; font-size: 11px; }
QLabel#iaReason{ color: #F0F2F7; font-size: 13px; }
QLabel#iaMeta  { color: #C6CCD8; font-size: 11px; }
QLabel#iaChip  { color: #EDF0F6; font-size: 11px;
                 background: rgba(255,255,255,0.13); border-radius: 4px; padding: 2px 7px; }
QLabel#iaEmpty { color: #A9B0BC; font-size: 13px; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.25); border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""

# 状态 -> (中文名, 文字色, 底色)
_STATUS = {
    "ok": ("已调度", "#7BD65C", "rgba(103,194,58,0.22)"),
    "empty": ("无任务", "#C0C4CC", "rgba(144,147,153,0.22)"),
    "skipped": ("跳过", "#F0B45C", "rgba(230,162,60,0.22)"),
    "timeout": ("超时", "#FF8A8A", "rgba(245,108,108,0.22)"),
    "error": ("失败", "#FF8A8A", "rgba(245,108,108,0.22)"),
}



class _Fetcher(QThread):
    """后台拉取 /intent_analysis/records。"""

    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            req = urllib.request.Request(self.url, method="GET")
            with urllib.request.urlopen(req, timeout=6) as resp:
                self.done.emit(json.loads(resp.read().decode("utf-8")))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _Poster(QThread):
    """后台发送控制请求（开关 / 清空）。"""

    done = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            req = urllib.request.Request(
                self.url, data=b"{}", headers={"Content-Type": "application/json"},
                method="POST")
            urllib.request.urlopen(req, timeout=6).read()
        except Exception as exc:
            logger.warning(f"意图分析控制请求失败 {self.url}: {exc}")
        finally:
            self.done.emit()


class IntentAnalysisWidget(QWidget):
    """意图分析观测面板（侧边栏「博弈图」页）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # QWidget 子类不设这个属性，QSS 里的 background 不会绘制
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._api_base: Optional[str] = None
        self._fetching = False
        # 保留所有在跑的线程引用：QThread 对象被 GC 掉而线程仍在运行，
        # Qt 会打印 "QThread: Destroyed while thread is still running" 并可能导致崩溃。
        self._threads: List[QThread] = []
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

        # 应用退出时先收线程：否则 QThread 对象被销毁而线程仍在跑，
        # Qt 会打印 "QThread: Destroyed while thread is still running" 并可能崩溃。
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._stop_threads)
        except Exception:
            pass

    # ----------------------------------------------------------- 线程管理
    def _track(self, thread: QThread):
        """登记线程，结束后自动从列表移除。"""
        self._threads.append(thread)
        thread.finished.connect(lambda: self._threads.remove(thread)
                                if thread in self._threads else None)

    def _stop_threads(self, timeout_ms: int = 1500):
        """等待所有后台线程结束（窗口关闭时调用，避免线程被强杀）。"""
        for t in list(self._threads):
            try:
                if t.isRunning():
                    t.quit()
                    t.wait(timeout_ms)
            except Exception:
                pass
        self._threads.clear()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setStyleSheet(_STYLE)
        self.setObjectName("iaRoot")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 顶部：标题 + 状态 + 操作
        bar = QHBoxLayout()
        bar.setSpacing(8)

        title = QLabel("博弈图 · 意图分析")
        title.setObjectName("iaTitle")
        bar.addWidget(title)

        self.pill = QLabel("—")
        self.pill.setObjectName("iaPill")
        bar.addWidget(self.pill)

        self.summary = QLabel("")
        self.summary.setObjectName("iaMeta")
        bar.addWidget(self.summary)
        bar.addStretch()

        self.toggle_btn = QPushButton("停用")
        self.toggle_btn.setObjectName("iaBtn")
        self.toggle_btn.clicked.connect(self.toggle_enabled)
        bar.addWidget(self.toggle_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("iaBtn")
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("iaBtn")
        self.clear_btn.clicked.connect(self.clear_records)
        bar.addWidget(self.clear_btn)

        root.addLayout(bar)

        # 记录列表
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        # QScrollArea 的 viewport 是独立子控件：QSS 里写 QScrollArea{background}
        # 管不到它，默认会填成白色 —— 这就是「纯白背景」的根源。
        # 这里显式关掉自动填充，并给出兜底样式。
        self.scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget {"
            " background: transparent; border: none; }")
        vp = self.scroll.viewport()
        if vp is not None:
            vp.setAutoFillBackground(False)

        self.list_host = QWidget()
        self.list_host.setObjectName("iaListHost")
        self.list_host.setAutoFillBackground(False)
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        self._show_placeholder("正在加载…")

    # --------------------------------------------------------------- 数据
    def _base(self) -> Optional[str]:
        if self._api_base:
            return self._api_base
        try:
            from core.system.config import get_server_port

            self._api_base = f"http://127.0.0.1:{get_server_port('api_server')}"
        except Exception as exc:
            logger.warning(f"无法解析 API 端口: {exc}")
            return None
        return self._api_base

    def refresh(self):
        if self._fetching:
            return
        base = self._base()
        if not base:
            self._show_placeholder("无法解析 API 端口")
            return

        self._fetching = True
        t = _Fetcher(f"{base}/intent_analysis/records?limit=60", self)
        t.done.connect(self._on_data)
        t.failed.connect(self._on_fail)
        t.finished.connect(lambda: setattr(self, "_fetching", False))
        self._track(t)
        t.start()

    def _post(self, path: str):
        base = self._base()
        if not base:
            return
        t = _Poster(f"{base}{path}", self)
        t.done.connect(lambda: QTimer.singleShot(300, self.refresh))
        self._track(t)
        t.start()

    def toggle_enabled(self):
        self._post("/intent_analysis/toggle")

    def clear_records(self):
        self._post("/intent_analysis/clear")

    # --------------------------------------------------------------- 渲染
    def _clear_list(self):
        while self.list_layout.count() > 1:  # 保留末尾的 stretch
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_placeholder(self, text: str):
        self._clear_list()
        lbl = QLabel(text)
        lbl.setObjectName("iaEmpty")
        lbl.setAlignment(Qt.AlignCenter)
        self.list_layout.insertWidget(0, lbl)

    def _on_fail(self, msg: str):
        self.pill.setText("API 不可达")
        self.pill.setStyleSheet("background: rgba(245,108,108,0.30); color: #FF9A9A;"
                                " font-size: 12px; padding: 2px 10px; border-radius: 9px;")
        self._show_placeholder(f"无法连接后端：{msg}")

    def _on_data(self, data: Dict[str, Any]):
        stats = data.get("stats") or {}
        records = data.get("records") or []
        enabled = bool(stats.get("enabled", True))

        # 状态胶囊
        if enabled:
            self.pill.setText("运行中")
            self.pill.setStyleSheet(
                "background: rgba(103,194,58,0.28); color: #8CE06A;"
                " font-size: 12px; padding: 2px 10px; border-radius: 9px;")
        else:
            self.pill.setText("已停用")
            self.pill.setStyleSheet(
                "background: rgba(144,147,153,0.28); color: #D8DCE4;"
                " font-size: 12px; padding: 2px 10px; border-radius: 9px;")
        self.toggle_btn.setText("停用" if enabled else "启用")

        by_status = stats.get("by_status") or {}
        parts = [f"共 {stats.get('total', 0)} 条"]
        for key, label in (("ok", "已调度"), ("empty", "无任务"),
                           ("skipped", "跳过"), ("timeout", "超时"), ("error", "失败")):
            if by_status.get(key):
                parts.append(f"{label} {by_status[key]}")
        if stats.get("running"):
            parts.append(f"进行中 {stats['running']}")
        self.summary.setText("  ·  ".join(parts))

        if not records:
            self._show_placeholder("暂无分析记录 —— 发起一次对话后这里会出现分析结果")
            return

        self._clear_list()
        for i, rec in enumerate(records):
            self.list_layout.insertWidget(i, self._make_card(rec))

    def _make_card(self, rec: Dict[str, Any]) -> QWidget:
        status = rec.get("status", "")
        label, color, bg = _STATUS.get(status, (status or "未知", "#C0C4CC",
                                                "rgba(144,147,153,0.22)"))

        card = QFrame()
        card.setObjectName("iaCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(5)

        # 第一行：时间 · 状态 · 会话 · 耗时
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(rec.get("time", ""))
        t.setObjectName("iaTime")
        head.addWidget(t)

        badge = QLabel(label)
        badge.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;"
            f" background: {bg}; border-radius: 4px; padding: 1px 7px;")
        head.addWidget(badge)

        head.addWidget(self._meta(f"会话 {rec.get('session_id', '-')}"))
        if rec.get("duration_ms"):
            head.addWidget(self._meta(f"{rec['duration_ms']} ms"))
        head.addStretch()
        lay.addLayout(head)

        # 第二行：原因
        reason = rec.get("reason") or "—"
        r = QLabel(reason)
        r.setObjectName("iaReason")
        r.setWordWrap(True)
        lay.addWidget(r)

        # 第三行：工具 chips
        tools = rec.get("tool_calls") or []
        if tools:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(self._meta(f"工具 {len(tools)}:"))
            for tc in tools[:6]:
                name = tc.get("tool_name") or "?"
                svc = tc.get("service_name") or ""
                row.addWidget(self._chip(f"{name} · {svc}" if svc else name))
            if len(tools) > 6:
                row.addWidget(self._meta(f"+{len(tools) - 6}"))
            row.addStretch()
            lay.addLayout(row)
        elif rec.get("task_count"):
            lay.addWidget(self._meta(f"任务 {rec['task_count']} 个，无工具调用"))

        # 第四行：分发结果
        for d in rec.get("dispatched") or []:
            ok = "成功" if d.get("ok") else "失败"
            mark = "✓" if d.get("ok") else "✗"
            lay.addWidget(self._meta(
                f"{mark} 分发到 {d.get('target', '?')} × {d.get('count', 0)}  ({ok}) "
                f"{d.get('detail', '')}"))

        return card

    @staticmethod
    def _meta(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("iaMeta")
        return lbl

    @staticmethod
    def _chip(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("iaChip")
        return lbl

    # --------------------------------------------------------------- 生命周期
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def closeEvent(self, event):
        self._timer.stop()
        self._stop_threads()
        super().closeEvent(event)
