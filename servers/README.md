# servers — 服务层

三个本地网络服务，全部由根目录的 `main.py` 以独立线程启动（`ServiceManager.start_all_servers`）

## 目录

```
servers/
├── apiserver/     API 服务器（:8000）—— 对话、LLM 接口、消息管理
├── agentserver/   Agent 服务器（:8001）—— 电脑控制、任务调度、工具包
└── mcpserver/     MCP 服务器（:8003）—— 工具注册、调度与各 Agent 实现
```

## 各自职责

| 包 | 入口 | 端口 | 说明 |
|---|---|---|---|
| `apiserver` | `apiserver.api_server:app` | 8000 | 前端 UI 与 LLM 之间的接口；FastAPI，`/docs` 可查 |
| `agentserver` | `agentserver.agent_server:app` | 8001 | 电脑控制 Agent；屏幕解析、鼠标键盘执行、任务调度 |
| `mcpserver` | `mcpserver.mcp_server:app` | 8003 | MCP 工具的统一注册与调度中心 |

## mcpserver 的两个关键文件

- **`mcp_registry.py`** — MCP 的**唯一注册中心**，扫描各 Agent 目录下的
  `agent-manifest.json`，按 `displayName` 注册，并负责实例化
  实现位于本仓库 `servers/mcpserver/`
- **`base_agent.py`** — MCP Agent 的**最小基类契约**（`Agent` / `AgentHooks` /
  `RunContextWrapper`），MCP Agent 只需继承 `Agent` 并实现
  `async def handle_handoff(data: dict) -> str`，不需要完整的 OpenAI Agents SDK

## 添加一个新工具 Agent

1. 在 `servers/mcpserver/` 下新建目录，例如 `agent_my_tool/`
2. 写入 `agent-manifest.json`：
   ```json
   {
     "displayName": "我的工具",
     "version": "1.0.0",
     "description": "功能说明",
     "agentType": "mcp",
     "entryPoint": {
       "module": "servers.mcpserver.agent_my_tool.my_agent",
       "class": "MyAgent"
     },
     "capabilities": {
       "invocationCommands": [
         { "command": "查询", "description": "参数：query", "example": "{\"tool_name\":\"查询\",\"query\":\"x\"}" }
       ]
     }
   }
   ```
3. 新建 `my_agent.py`（文件名自取，此处仅为示例）：
   ```python
   from servers.mcpserver.base_agent import Agent

   class MyAgent(Agent):
       name = "MyAgent"
       instructions = "我的工具"
       async def handle_handoff(self, data: dict) -> str:
           ...
   ```
4. 重启即可 —— `mcp_registry` 会自动扫描注册，无需改任何注册表代码

> `entryPoint.module` 必须是**真实可导入**的完整路径，所有 manifest 都指向
> `servers.mcpserver.*`，与目录位置保持一致

## 端口从哪来

端口不在本目录硬编码，统一由 `core/system/config.py` 的 `get_current_port()` 读取
`config.json`（`api_server` / `agentserver` / `mcpserver` 各节）
