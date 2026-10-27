#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""博弈（意图分析）开关控制器。

历史背景
--------
原来这里只有一个本地布尔 `self_game_enabled`，打开后让聊天请求带上
`use_self_game=True`。但服务端的博弈流程已随 `game/` 模块移除，
请求侧恒为 false —— 于是这个按钮**唯一的效果是把请求从流式变成非流式**，
界面响应反而变差，却没有任何"博弈"功能。

现在它被接到**真正存在的东西**上：后台意图分析
（`core/system/background_analyzer.py`，其自身文档即称"基于博弈论的对话分析机制"）
的启用/停用。状态以服务端返回为准，不做本地假象。
"""

import json
import urllib.request

from core.system.config import config, logger
from . import chat


class GameTool():
    """控制后台意图分析的启停。"""

    def __init__(self, window):
        self.window = window

    def _api_base(self) -> str:
        from core.system.config import get_server_port

        return f"http://127.0.0.1:{get_server_port('api_server')}"

    def _post(self, path: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self._api_base()}{path}",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def toggle_self_game(self):
        """切换后台意图分析的启用状态（以服务端返回为准）。"""
        try:
            result = self._post("/intent_analysis/toggle")
            enabled = bool(result.get("enabled"))
            status = "启用" if enabled else "停用"
            chat.add_user_message("系统", f"● 意图分析已{status}")
            logger.info(f"意图分析已{status}")
        except Exception as exc:
            logger.error(f"切换意图分析状态失败: {exc}")
            chat.add_user_message("系统", f"❌ 切换意图分析失败: {exc}")


from ..utils.lazy import lazy
@lazy
def game():
    return GameTool(config.window)
