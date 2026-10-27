#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Agent 的最小基类契约。

背景
----
本仓库的 MCP Agent（agent_memory / agent_mqtt_tool / agent_weather_time /
system_control 等）并不需要完整的 OpenAI Agents SDK 运行时，它们只需要：
以 ``Agent`` 为基类，声明 ``name`` / ``instructions``，并实现
``async def handle_handoff(data: dict) -> str``。

历史上这些类由外部包 nagaagent_core 的 ``vendors/agents.py`` 提供——它是一个
``try: import agents ... except Exception: 提供最小兼容实现`` 的垫片。也就是说在
未安装 ``agents`` 时，这些 Agent 一直跑在垫片的桩类上。

``agents``（PyPI: openai-agents）并未出现在 uv.lock 中，且其当前版本要求
``openai>=3.0.0``，与本项目 langchain-openai 所要求的 ``openai<3.0.0`` 互斥。
因此这里把该最小契约显式落在本仓库内：既保留原有可运行行为，又不再依赖那个
"静默降级成假实现"的垫片。

注意
----
- 这里**不是** OpenAI Agents SDK 的替代品。需要真实 SDK 能力（``Runner``、
  ``function_tool``、``ModelProvider``、``MCPServerStdio``）的模块
  （见 mcpserver/agent_playwright_master/playwright.py）必须安装 openai-agents。
- 与旧垫片不同，``handle_handoff`` 未实现时会抛出 NotImplementedError，
  让问题显式暴露，而不是静默返回错误结果。
"""

from typing import Any, Dict, List, Optional


class RunContextWrapper:
    """钩子函数收到的上下文包装（最小实现）。"""

    def __init__(self, **kwargs: Any) -> None:
        self.data: Dict[str, Any] = kwargs


class AgentHooks:
    """Agent 生命周期钩子接口（最小实现）。"""

    async def on_start(self, context: "RunContextWrapper", agent: "Agent") -> None:
        return None

    async def on_end(
        self, context: "RunContextWrapper", agent: "Agent", output: Any
    ) -> None:
        return None


class ComputerTool:
    """ComputerTool 的最小包装。"""

    def __init__(self, tool: Any) -> None:
        self.tool = tool


class Agent:
    """MCP Agent 基类。

    子类按既有写法设置 ``name`` / ``instructions`` 并在 ``__init__`` 中调用
    ``super().__init__(...)``，然后实现 ``handle_handoff``。
    """

    name: str = ""
    instructions: str = ""

    def __init__(
        self,
        name: str = "",
        instructions: str = "",
        tools: Optional[List[Any]] = None,
        model: str = "",
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.tools = tools or []
        self.model = model
        # 兼容 SDK 的其余关键字（hooks/model_settings 等），避免子类调用报错
        for key, value in kwargs.items():
            setattr(self, key, value)

    async def handle_handoff(self, data: Dict[str, Any]) -> str:
        """处理一次 MCP 工具调用。子类必须实现。"""
        raise NotImplementedError(
            f"{type(self).__name__} 未实现 handle_handoff"
        )


__all__ = [
    "Agent",
    "AgentHooks",
    "RunContextWrapper",
    "ComputerTool",
]
