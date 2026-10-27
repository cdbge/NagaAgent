# NagaAgent Server

独立的意图分析与任务调度服务（端口 8001）

## 架构特点

### 微服务架构
- **独立服务**：意图分析作为独立的 HTTP 服务运行
- **异步处理**：Fire-and-forget 模式，不阻塞主流程
- **任务调度**：分析结果直接转化为可执行任务

### 核心组件

#### 1. Agent Server (`agent_server.py`)
- FastAPI 服务，提供 HTTP 接口
- 管理全局模块状态（`Modules`）
- 处理意图分析、任务调度、工具包调用与文件读写请求

#### 2. Task Scheduler (`task_scheduler.py`)
- 负责任务执行调度
- 管理任务生命周期（步骤、失败尝试、压缩记忆）
- 支持并发任务执行

使用示例：

```python
from servers.agentserver.task_scheduler import get_task_scheduler

task_scheduler = get_task_scheduler()

# 查询统计
total = len(task_scheduler.task_registry)
running = len([t for t in task_scheduler.task_registry.values() if t.get("status") == "running"])
queued = len([t for t in task_scheduler.task_registry.values() if t.get("status") == "queued"])
```

#### 3. Toolkit Manager (`toolkit_manager.py`)
- 加载并管理 `tools/` 下的工具包
- 对外提供工具清单与调用入口

#### 4. Computer Control (`agent_computer_control/`)
- `computer_control_agent.py`：电脑控制智能体，对外的 `handle_handoff` 入口
- `action_executor.py`：动作执行（点击/输入/滚动等）
- `computer_use_adapter.py`：屏幕适配层（截图、坐标缩放、DPI 感知）
- `visual_analyzer.py`：视觉定位

> **注意**：电脑控制依赖可选的 `gui-agents`，未安装时适配器 `init_ok` 为 `False`
> 所有执行入口会**明确返回失败**，不会做任何屏幕操作

#### 5. Config (`config.py`)
- 任务超时、日志级别等本服务专属配置
- 端口来自 `core/system/config.py` 的 `get_current_port("agent_server")`（唯一权威来源）

## API 接口

### 健康检查
```http
GET /health
```

### 意图分析与调度
```http
POST /analyze_and_execute
Content-Type: application/json

{
    "messages": [
        {"role": "user", "content": "帮我查一下明天的天气"}
    ],
    "session_id": "main_session"
}
```

```http
POST /schedule
Content-Type: application/json

{
    "id": "task-1",
    "query": "原始请求",
    "tool_calls": [],
    "created_at": "2026-10-06T15:00:00.000000Z"
}
```

### 电脑控制
```http
GET  /computer_control/availability
POST /computer_control/execute
```

### 任务与记忆
```http
GET    /tasks
GET    /tasks/{task_id}
GET    /tasks/{task_id}/memory
POST   /tasks/{task_id}/steps
DELETE /tasks/{task_id}/memory

GET    /memory/global
DELETE /memory/global

GET    /sessions
GET    /sessions/{session_id}/memory
GET    /sessions/{session_id}/compressed_memories
GET    /sessions/{session_id}/key_facts
GET    /sessions/{session_id}/failed_attempts
GET    /sessions/{session_id}/tasks
DELETE /sessions/{session_id}/memory
```

### 工具包与文件
```http
GET  /tools
GET  /toolkits
GET  /toolkits/{toolkit_name}
POST /tools/{toolkit_name}/{tool_name}

POST /file/edit
POST /file/write
GET  /file/read
GET  /file/list
```

## 启动方式

### 统一启动（推荐）
Agent Server 已集成到主流程中，通过 `main.py` 统一启动：

```bash
python main.py
```

这将同时启动：
- 主对话流程（GUI）
- API 服务器（端口 8000）
- Agent Server（端口 8001）
- MCP 工具服务（端口 8003）
- TTS 服务（端口 15048）

### 独立启动（开发调试）
如果需要独立启动 Agent Server 进行调试：

```bash
uvicorn servers.agentserver.agent_server:app --host 0.0.0.0 --port 8001
```

## 配置说明

本服务专属配置在 `servers/agentserver/config.py`：
- 任务超时时间
- 日志级别等

端口不在此处配置 —— 它来自 `core/system/config.py` 的 `get_current_port("agent_server")`，
权威来源始终是根目录的 `config.json`

## 与主流程集成

主对话流程通过 HTTP 调用 Agent Server，例如意图分析结果的回调：

```python
# core/system/background_analyzer.py
url = f"http://127.0.0.1:{get_server_port('agent_server')}/schedule"
payload = {"id": task_id, "query": query, "tool_calls": tool_calls,
           "created_at": now_iso_utc()}
```

时间字段统一使用 `core/system/timeutil.py` 的 `now_iso_utc()`（UTC + `Z` 后缀），
以便跨服务比较

## 注意事项

1. **服务依赖**：需要确保 Agent Server 在端口 8001 运行
2. **网络延迟**：HTTP 调用会增加少量延迟
3. **错误处理**：需要处理网络异常和服务不可用情况
4. **资源管理**：需要合理配置任务并发数和超时时间
5. **失败语义**：工具调用失败会返回 `success: false` + `error` 字段，
   不再以「已提交调用」之类占位文案冒充成功

## 更新记录

- 2025-09-30: 修复导入路径，将 `apiserver.task_scheduler` 更正为 `agentserver.task_scheduler`
- 2025-10-06: 新增 `task_scheduler.py` 轻量实现与用法示例
- 2026-10-06: 文档与实现对齐
  - 补充任务记忆、会话、工具包、文件四组端点
  - 修正端点清单（移除 `POST /tasks/{task_id}/cancel`，该端点不存在）
  - 时间字段统一为 UTC（`core/system/timeutil.py` 的 `now_iso_utc()`）
  - 电脑控制状态如实反映 `handle_handoff` 的返回值
