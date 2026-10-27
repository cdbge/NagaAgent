# core — 核心能力层

被服务层与 UI 层共用的基础设施与业务能力

## 目录

```
core/
├── system/         配置、日志、意图分析、启动自检、提示词
├── summer_memory/  GRAG 五元组知识图谱记忆（Neo4j）
├── voice/          语音输入（input/）与 TTS 输出（output/）
└── mqtt_tool/      物联网设备开关
```

## 各模块职责

| 模块 | 关键文件 | 说明 |
|---|---|---|
| `system` | `config.py` | **配置模型与端口唯一来源**；`load_config()` 读根目录 `config.json` |
| `system` | `deepseek.py` | DeepSeek 端点与模型名的唯一来源（不要在别处硬编码 URL / 模型名） |
| `system` | `json_config.py` | 配置文件的**唯一读写入口**：编码检测、`#` 注释剥离、解析与写回 |
| `system` | `timeutil.py` | 时间工具；`now_iso_utc()` 统一为 UTC + `Z`，供跨服务比较 |
| `system` | `naga_parsing.py` | 非标准 JSON（含中文全角括号）与工具调用解析 |
| `system` | `system_checker.py` | 启动自检；缺失依赖时给出修复建议 |
| `system` | `logging_setup.py` | 日志级别与第三方噪音压制，进程入口调用一次 |
| `system` | `health_check.py` | **运行期连通性诊断**：服务端口/端点探活、依赖、存储，见下文 |
| `system` | `background_analyzer.py` | 对话意图分析（后台触发） |
| `system` | `event_bus.py` | **进程内事件总线**：服务层靠它通知界面，无需 `import ui`，见下文 |
| `system` | `contracts.py` | **统一响应契约**：`ok()` / `fail()` / `is_ok()` / Problem Details，见下文 |
| `system` | `message_manager.py` | 会话与消息存储（历史、日志、上下文拼装） |
| `system` | `response_util.py` | 文本提取工具（纯 JSON 解析，无 UI 依赖） |
| `summer_memory` | `memory_manager.py` / `quintuple_*.py` | 五元组抽取、检索、可视化 |
| `summer_memory` | `memory_curator.py` | 记忆自我审查：规则过滤 + LLM 自审，决定哪些内容值得入库 |
| `summer_memory` | `graph_backends/` | 可插拔图存储后端（kuzu / neo4j / sqlite），见下文 |
| `voice` | `input/`、`output/` | 语音识别与 TTS；实时语音走 `input/voice_realtime/` |
| `mqtt_tool` | `device_switch.py` | MQTT 设备开关控制 |

## 事件总线

服务端与界面通过主题名通信，服务端不 import UI

```python
# 服务端
event_bus.publish("tool.ai_response", text=ai_response)

# 界面（GUI 线程，启动时注册；退出时退订）
event_bus.subscribe("tool.ai_response",
                    lambda text: chat.tool_ai_response_received.emit(text))
```

主题按 `.` 分层（发布 `a.b` 也会通知订阅 `a` 的监听者）；订阅绑定方法时按弱引用保存；
回调在发布线程执行，跨线程更新由订阅方转交

## 统一响应契约

| 函数 | 用途 |
|---|---|
| `ok(**fields)` | 成功响应 `{"success": true, ...}` |
| `fail(err, code=...)` | 失败响应，`error` 可读文本、`error_code` 机器码 |
| `is_ok(payload, default=False)` | 容错读取，同时识别历史上的各种写法 |
| `problem(status, code, detail)` | RFC 9457 形态，并保留 `success`/`error` 兼容旧客户端 |
| `install_problem_handlers(app)` | 框架自身异常也走同一信封 |

判断失败用 `is_ok()`，不要用 `payload.get("success") is False`
判断 `results` 列表条目时传 `default=True`

## 路径约定（重要）

本层模块嵌套较深，需要定位「仓库根目录」的代码统一按**层级回退**取得：

| 文件 | 回到根目录的写法 |
|---|---|
| `core/system/config.py` | `Path(__file__).parent.parent.parent` |
| `core/mqtt_tool/device_switch.py` | 同上（3 层） |
| `core/summer_memory/*.py` | 同上（3 层） |
| `core/voice/output/*.py` | `dirname` × 4 |

**不要新增 `sys.path` 拼接**：正常情况下应用从仓库根目录启动，根目录已在 `sys.path` 上
新代码请优先使用包内绝对导入，例如 `from core.system.config import config`

## 配置系统

`system/config.py` 是配置的唯一权威：

- `config.system.base_dir` → 仓库根目录
- `config.system.log_dir` → `<repo>/data/logs`
- `get_current_port("<name>")` → 从 `config.json` 读取端口，缺省值仅作兜底

`config.json` 位于仓库根目录且**不入库、不进发布包**；`config.json.example` 是模板

## 日志与运行时数据

运行期产生的文件统一写往 `<repo>/data/logs/`（知识图谱导出、音频临时文件、提示词留存等），
相关规则见根目录 `.gitignore`

## 记忆审查（避免图谱被对话碎片污染）

知识图谱只应保存**长期事实**，不应保存对话过程本身（碎片主体、代词、元讨论、
同一实体的多种拼写等）治理分三层，**治本 + 兜底**并用：

| 层 | 位置 | 作用 |
|---|---|---|
| 1. 提示词约束（治本） | `quintuple_extractor.py` 的 `_quality_rules_block()` | 明确「只记长期事实、不记对话过程」，要求消解代词、统一实体名 |
| 2. 规则审查（免费兜底） | `memory_curator.py` 的 `curate()` | 拒绝代词/碎片/数量词/元讨论/对话行为；归一化人称与实体别名；关系同义词归一 |
| 3. LLM 自我审查（可选） | `memory_curator.py` 的 `review_with_llm()` | 一次批量调用判断「是否值得长期记忆」，处理规则难以判定的灰色地带 |

**接入点**：`quintuple_graph.store_quintuples()` —— 唯一的写入收口，任何调用方都绕不过去
规则层零模型调用、不增延迟；第 3 层失败时**放行**（不因审查服务异常而丢数据）

### 清理存量数据

```bash
python scripts/curate_memory.py            # 预演，只出报告不改数据
python scripts/curate_memory.py --apply    # 实际清理（自动备份 + 重建图后端）
python scripts/curate_memory.py --apply --no-llm   # 只用规则审查
```

清理前会自动把 `quintuples.json` 备份为 `quintuples.<时间戳>.bak.json`，可随时回滚

### 调整审查标准

- 拒收/归一规则集中在 `memory_curator.py` 顶部的常量（`_PRONOUNS` / `_JUNK_SINGLE` /
  `_META_HEADS` / `_CONVERSATION_VERBS` / `_RELATION_SYNONYMS`），按需增删即可
- 自我审查的判定标准在 `_REVIEW_SYSTEM` 常量里

## 图存储后端（可插拔）

GRAG 记忆的五元组存在**图后端**里，后端可切换、互不依赖，实现位于
`core/summer_memory/graph_backends/`，上层只依赖统一接口 `GraphBackend`

| 后端 | 说明 | 依赖 | 适用 |
|---|---|---|---|
| **`kuzu`**（默认） | 嵌入式图数据库，进程内运行 | `pip install kuzu`（约 4.7MB） | **默认**，无需服务/端口/Docker |
| `neo4j` | 独立图数据库服务 | Neo4j 服务 + `py2neo` | 需要独立图服务、更大规模 |
| `sqlite` | 标准库自带 | 无 | 想彻底零依赖 |

切换方式（`config.json`）：

```json
"grag": {
  "graph_backend": "kuzu",          // kuzu(默认) / neo4j / sqlite
  "kuzu_db_path": "data/graph.kuzu"
}
```

**降级策略**：首选后端不可用时**不会**静默换成另一个图库（否则数据会分散在两个库里、
极难排查），而是退化为本地文件快照 `data/logs/knowledge_graph/quintuples.json`
（查询会自动回退到该文件的子串匹配）；若需零依赖，把 `graph_backend` 设为 `sqlite`

> ⚠️ **Kuzu 是单写入者模型**：同一个数据库文件同一时刻只能被一个进程打开
> 因此**不要同时运行两个 NagaAgent 实例**，否则后启动的那个会因锁冲突而降级到文件模式

### 新增一个后端

1. 在 `graph_backends/` 下新建一个文件（如 `my_backend.py`），继承 `GraphBackend` 并实现
   `is_available` / `store` / `query` / `count` / `clear` / `close`
2. 在 `factory.py` 的 `get_backend()` 里加一个分支
3. 无需改动业务层（`quintuple_graph.py` / `memory_manager.py`）

## 运行期健康检查

`system_checker.py` 检查「能不能启动」；`health_check.py` 检查「跑起来之后各服务通不通」

| 检查项 | 判定方式 |
|---|---|
| `api_server` | 端口 + `GET /health` |
| `agent_server` | 端口 + `GET /health` |
| `mcp_server` | 端口 + `GET /status` |
| `tts_server` | 仅端口（TTS 只有 `POST /v1/audio/speech`） |
| `asr_server` | 端口，仅当 `voice_mode = local` 时算必需 |
| `dependencies` | 必需/可选依赖能否 import |
| `storage` | 数据目录可写性 |

```bash
python -m core.system.health_check     # 非全绿时退出码 1
curl http://127.0.0.1:8000/health/full # 单次 2–3 秒
```

启动后由后台线程延迟 6 秒执行一次，只写日志；可选能力缺失记为 `degraded`

