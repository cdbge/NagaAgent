#!/usr/bin/env python3
"""
NagaAgent API服务器
提供RESTful API接口访问NagaAgent功能
"""

import asyncio
import sys
import traceback
import os
import logging

from contextlib import asynccontextmanager
from typing import List, Optional, Any

# 在导入其他模块前先设置HTTP库日志级别
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)

# 创建logger实例
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 流式文本处理模块（仅用于TTS）
from core.system.message_manager import message_manager  # 导入统一的消息管理器


# 导入配置系统
try:
    from core.system.config import config, AI_NAME  # 使用新的配置系统
    from core.system.config import get_prompt  # 导入提示词仓库
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.system.contracts import install_problem_handlers, is_ok

# 对话核心功能已集成到apiserver


def _extract_tool_result(payload_result: Any, ok: bool) -> str:
    """从 MCP 工具回调中取出人类/模型可读的结果文本。

    回调结构::

        {"success": True,
         "results": [{"tool": "today_weather", "success": True, "result": "{...}"}],
         "message": "成功执行 1 个工具调用"}

    真实数据在 ``results[i]["result"]``，**不在**顶层 ``result["result"]``。
    旧实现只读顶层键，于是永远退化成字面量 "执行成功"，导致模型拿不到工具数据。
    """
    if payload_result is None:
        return "执行成功"
    if not isinstance(payload_result, dict):
        return str(payload_result)

    if not ok:
        return str(payload_result.get("error") or "未知错误")

    parts: List[str] = []

    # 1) 标准形态：results 列表
    for item in payload_result.get("results") or []:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        tool = item.get("tool") or item.get("tool_name") or "工具"
        if not is_ok(item, default=True):   # 容错：认得 success/status/error/detail
            parts.append(f"{tool}: 失败 - {item.get('error') or item.get('result')}")
            continue
        value = item.get("result", item.get("data"))
        if value:
            parts.append(f"{tool}: {value}")

    if parts:
        return "\n".join(parts)

    # 2) 退化形态：直接给了 result / data / message
    for key in ("result", "data", "message"):
        value = payload_result.get(key)
        if value:
            return str(value)

    return "执行成功"


# 统一后台意图分析触发函数 - 已整合到message_manager
def _trigger_background_analysis(session_id: str):
    """统一触发后台意图分析 - 委托给message_manager"""
    message_manager.trigger_background_analysis(session_id)

# 统一保存对话与日志函数 - 已整合到message_manager
def _save_conversation_and_logs(session_id: str, user_message: str, assistant_response: str):
    """统一保存对话历史与日志 - 委托给message_manager"""
    message_manager.save_conversation_and_logs(session_id, user_message, assistant_response)


def _schedule_memory_extraction(user_message: str, assistant_response: str) -> None:
    """把本轮对话投递给 GRAG 记忆系统做五元组抽取。

    背景：``memory_manager.add_conversation_memory()`` 是记忆写入的**唯一**入口，
    但此前全仓库没有任何地方调用它 —— 也就是说记忆系统虽然连着 Neo4j、"回忆"
    工具也接好了，却**从来没有写入过任何记忆**（quintuples.json 一直不存在）。

    抽取要走一次 LLM（通常十几秒），因此这里用 create_task 异步执行，
    绝不阻塞本轮回复。
    """
    try:
        from core.summer_memory.memory_manager import memory_manager
        if not memory_manager or not getattr(memory_manager, "enabled", False):
            return

        async def _run():
            try:
                await memory_manager.add_conversation_memory(user_message, assistant_response)
            except Exception as exc:
                logger.warning(f"[记忆] 抽取失败（不影响对话）: {exc}")

        # 已有事件循环时用 create_task；否则交给全局循环
        loop = asyncio.get_event_loop()
        loop.create_task(_run())
    except Exception as exc:
        logger.warning(f"[记忆] 无法调度抽取任务: {exc}")

# 回调工厂类已移除 - 功能已整合到streaming_tool_extractor


def _decode_sse_data(chunk: str) -> Optional[str]:
    """把 SSE 的 ``data: <base64>`` 解成文本。

    不是数据行、是 ``[DONE]``、或解码失败时返回 None。

    这段逻辑原先在 chat_stream 里写了两遍，而且两处失败语义不同：
    一处是 ``except Exception: pass``（完全静默），另一处记 logger.error。
    静默那处会把解码失败吞掉 —— complete_text 留空，随后被当成
    「助手回复了空内容」写进历史。现在统一记 warning 并返回 None。
    """
    if not chunk.startswith("data: "):
        return None
    data_str = chunk[6:].strip()
    if not data_str or data_str == "[DONE]":
        return None
    try:
        import base64
        return base64.b64decode(data_str).decode("utf-8")
    except Exception as e:
        logger.warning(
            f"[API Server] SSE 数据解码失败（跳过该分片）: {type(e).__name__}: {e}")
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    try:
        print("[INFO] 正在初始化API服务器...")
        # 对话核心功能已集成到apiserver
        print("[SUCCESS] API服务器初始化完成")
        yield
    except Exception as e:
        print(f"[ERROR] API服务器初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[INFO] 正在清理资源...")
        # MCP服务现在由mcpserver独立管理，无需清理

# 创建FastAPI应用
app = FastAPI(
    title="NagaAgent API",
    description="智能对话助手API服务",
    version="4.0.0",
    lifespan=lifespan
)

# 统一错误契约：框架异常（HTTPException / 校验失败 / 未捕获异常）
# 也返回 {"success": false, "error": ..., "code": ...}，见 core/system/contracts.py
install_problem_handlers(app, type_base="https://nagaagent.local/problems")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 请求模型
class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None
    use_self_game: bool = False
    disable_tts: bool = False  # V17: 支持禁用服务器端TTS
    return_audio: bool = False  # V19: 支持返回音频URL供客户端播放
    skip_intent_analysis: bool = False  # 新增：跳过意图分析

class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
    status: str = "success"


class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool

# 文档处理功能已整合到 ui/controller/tool_document.py

# 新增：日志解析相关API接口


# ---------------------------------------------------------------------------
# 意图分析（「博弈图」页的数据源）
#
# 「博弈论」是这套后台机制的历史叫法：它分析对话、发现潜在任务，再通过 MCP
# 把工具调用分发出去。UI 不直接 import 服务层，因此这里开一组只读/控制端点，
# 由 UI 通过 HTTP 访问（符合 ui/README 的分层约定）。
# ---------------------------------------------------------------------------


async def _notify_ui_refresh(session_id: str, response_text: str):
    """通知UI刷新会话历史"""
    try:
        import httpx

        # 通过UI通知接口直接显示AI回复
        ui_notification_payload = {
            "session_id": session_id,
            "action": "show_tool_ai_response",
            "ai_response": response_text
        }

        from core.system.config import get_server_port
        api_url = f"http://localhost:{get_server_port('api_server')}/ui_notification"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(api_url, json=ui_notification_payload)
            if response.status_code == 200:
                logger.info(f"[UI通知] AI回复显示通知发送成功: {session_id}")
            else:
                logger.error(f"[UI通知] AI回复显示通知失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[UI通知] 通知UI刷新失败: {e}")


# ---------------------------------------------------------------------------
# 路由注册
#
# 每个 routes/*.py 导出一个 APIRouter。这里放在文件**最末尾**导入，
# 保证 api_server 里的 logger / Pydantic 模型 / 辅助函数都已定义完毕，
# 从而避免 routes 与 api_server 之间的循环导入问题。
# ---------------------------------------------------------------------------
from .routes import chat as _r_chat  # noqa: E402
from .routes import intent as _r_intent  # noqa: E402
from .routes import sessions as _r_sessions  # noqa: E402
from .routes import system as _r_system  # noqa: E402
from .routes import tools as _r_tools  # noqa: E402
from .routes import ui as _r_ui  # noqa: E402

for _module in (_r_system, _r_chat, _r_sessions, _r_tools, _r_intent, _r_ui):
    app.include_router(_module.router)
