#!/usr/bin/env python3
"""
LLM服务模块
提供统一的LLM调用接口，替代conversation_core.py中的get_response方法
"""

import json
import logging
import sys
import os
from typing import Optional, Dict, Any, List

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from fastapi import FastAPI, HTTPException
from core.system.config import config

class _ThinkTagStripper:
    """流式剥离模型内联的思考过程。

    即使把 DeepSeek 的 ``thinking`` 参数设为 disabled，模型有时仍会把思维链
    直接写进 ``content``，形式为 ``<!--<think>...</think>-->`` 包裹的 HTML 注释。
    这些内容不应该出现在对话气泡里。

    难点在于标签可能在任意位置被切成多个 SSE 分片（例如 ``<!--<thi`` + ``nk>``），
    因此不能简单地按分片正则替换。这里维护一个缓冲：仅当缓冲中能确定"不是标签开头"
    时才把内容推给前端，标签片段则一直保留到闭合。

    若最终仍未闭合（异常情况），在 flush() 时原样输出，避免吞掉真实回复。
    """

    _MAX_TAG = 64  # 标签最长可能长度

    def __init__(self):
        self._buf = ""

    def feed(self, text: str) -> str:
        """喂入一个分片，返回可以安全发送给前端的文本（可能为空）。"""
        self._buf += text

        # 1) HTML 注释 <!-- ... --> ：其中可能包含 <think> 文本，整体丢弃。
        #    只有当 --> 真正出现后才丢弃，避免把注释切成两半泄漏出去。
        while True:
            start = self._buf.find("<!--")
            if start == -1:
                break
            end = self._buf.find("-->", start + 4)
            if end == -1:
                # 未闭合：注释之前的内容可以安全输出，注释留在缓冲等待闭合
                head, self._buf = self._buf[:start], self._buf[start:]
                if head:
                    return head
                # 整个缓冲都是未闭合注释 -> 不输出
                return ""
            self._buf = self._buf[:start] + self._buf[end + 3:]

        # 2) 裸 <think ...> ... </think ...> （不包在注释里时）
        while True:
            lt = self._buf.find("<think")
            if lt == -1:
                break
            end = self._buf.find("</think", lt + 6)
            if end == -1:
                head, self._buf = self._buf[:lt], self._buf[lt:]
                if head:
                    return head
                return ""
            gt = self._buf.find(">", end)
            if gt == -1:
                head, self._buf = self._buf[:lt], self._buf[lt:]
                if head:
                    return head
                return ""
            self._buf = self._buf[:lt] + self._buf[gt + 1:]

        # 3) DeepSeek 的 DSML 内联工具调用标记
        #    当模型想调用一个**不在本次 tools 列表里**的工具时，它不会走原生
        #    tool_calls，而是把内部标记直接写进正文：
        #
        #        <｜｜DSML｜｜ calls>
        #        <｜｜DSML｜｜ invoke name="xxx">...</｜｜DSML｜｜ invoke>
        #        </｜｜DSML｜｜ calls>
        #
        #    这些是模型内部的协议文本，绝不能出现在用户看到的气泡里。
        while True:
            start = self._buf.find("<｜｜DSML｜｜")
            if start == -1:
                break
            end_marker = "</｜｜DSML｜｜ calls>"
            end = self._buf.find(end_marker, start)
            if end == -1:
                # 未闭合：标记之前的正文可以安全输出，标记留在缓冲
                head, self._buf = self._buf[:start], self._buf[start:]
                if head:
                    return head
                return ""
            self._buf = self._buf[:start] + self._buf[end + len(end_marker):]

        # 4) 尾部若可能是标签开头，保留不输出（否则标签会被切坏）
        hold = 0
        lt = self._buf.rfind("<")
        if lt != -1:
            tail = self._buf[lt:]
            for mark in ("<!--", "<think", "<｜｜DSML｜｜"):
                if mark.startswith(tail) and len(tail) < len(mark):
                    hold = len(tail)
                    break

        if hold:
            safe, self._buf = self._buf[: len(self._buf) - hold], self._buf[len(self._buf) - hold:]
            return safe
        safe, self._buf = self._buf, ""
        return safe

    def flush(self) -> str:
        """流结束时输出剩余内容（未闭合标签按原样输出，避免丢字）。

        例外：残缺的 DSML 标记一定属于内部协议文本，不是用户想看的正文，
        直接丢弃而不是"避免丢字"地吐出去。
        """
        rest, self._buf = self._buf, ""
        idx = rest.find("<｜｜DSML｜｜")
        if idx != -1:
            rest = rest[:idx]
        return rest


# 配置日志
logger = logging.getLogger("LLMService")


def _describe_api_error(exc: Exception) -> str:
    """把 SDK / HTTP 异常翻译成人能看懂的一句话。

    OpenAI SDK 的 APIStatusError 带有 status_code 与 response 正文，DeepSeek 会
    把真正的失败原因放在 response 里（例如鉴权失败会说明 key 无效）。原先只回传
    ``str(exc)``，用户界面只能看到笼统信息，难以定位问题。
    """
    status = getattr(exc, "status_code", None)
    body = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.text or ""
        except Exception:
            body = ""

    detail = body.strip()
    if detail:
        # 尽量只取人类可读的 message 字段
        try:
            import json as _json
            parsed = _json.loads(detail)
            detail = (
                parsed.get("error", {}).get("message")
                if isinstance(parsed.get("error"), dict)
                else parsed.get("message") or detail
            )
        except Exception:
            pass

    if status == 401:
        return f"鉴权失败(401)：API Key 无效或已过期，请在 config.json 的 api.api_key 中更换。详情: {detail}"
    if status == 402:
        return f"余额不足(402)：请前往 DeepSeek 平台充值。详情: {detail}"
    if status == 429:
        return f"请求过于频繁(429)：请稍后重试或降低并发。详情: {detail}"
    if status:
        return f"API 返回 {status}：{detail or exc}"
    return f"{type(exc).__name__}: {exc}"


class LLMService:
    """LLM服务类 - 提供统一的LLM调用接口"""
    
    def __init__(self):
        self.async_client: Optional[AsyncOpenAI] = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化OpenAI客户端"""
        try:
            self.async_client = AsyncOpenAI(
                api_key=config.api.api_key, 
                base_url=config.api.base_url.rstrip('/') + '/'
            )
            logger.info("LLM服务客户端初始化成功")
        except Exception as e:
            logger.error(f"LLM服务客户端初始化失败: {e}")
            self.async_client = None
    
    def _request_params(
        self,
        messages: List[Dict],
        temperature: float,
        stream: bool,
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """构造请求体（**原始 HTTP 流式调用**使用）。

        DeepSeek 官方当前模型（deepseek-flash / deepseek-v4-pro）支持
        ``thinking`` 与 ``reasoning_effort``；这两个是 DeepSeek 扩展参数，需要走
        原始 HTTP 请求（见 stream_chat_with_context）。

        注意：**不要把这两个参数传给 OpenAI SDK** —— SDK 的
        ``AsyncCompletions.create()`` 只接受它声明过的关键字，遇到未知的
        ``thinking`` 会直接抛
        ``TypeError: got an unexpected keyword argument 'thinking'``。
        SDK 路径请使用 _sdk_params()。

        Args:
            tools: OpenAI function calling 的工具定义。传了就启用原生工具调用
                （``parallel_tool_calls`` 一并打开 —— DeepSeek 实测支持并行调用）。
        """
        params: Dict[str, Any] = {
            "model": config.api.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": config.api.max_tokens,
        }

        thinking_enabled = getattr(config.api, "thinking_enabled", True)
        params["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}
        if thinking_enabled:
            effort = getattr(config.api, "reasoning_effort", "medium")
            if effort:
                params["reasoning_effort"] = effort

        # 工具定义：只有非空才传，空列表会被部分服务端当成「禁用工具」
        if tools:
            params["tools"] = tools
            params["parallel_tool_calls"] = True

        if stream:
            params["stream"] = True
        return params

    def _sdk_params(self, messages: List[Dict], temperature: float) -> Dict[str, Any]:
        """构造请求体（**OpenAI SDK 非流式调用**使用）。

        只包含 SDK 认识的标准参数；thinking / reasoning_effort 等 DeepSeek
        专有扩展不在此传，避免 SDK 抛 TypeError。
        """
        return {
            "model": config.api.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": config.api.max_tokens,
        }

    async def get_response(self, prompt: str, temperature: float = 0.7) -> str:
        """为其他模块提供API调用接口"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                return f"LLM服务不可用: 客户端初始化失败"
        
        params = self._sdk_params([{"role": "user", "content": prompt}], temperature)
        try:
            response = await self.async_client.chat.completions.create(**params)
            return response.choices[0].message.content
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常，重新创建客户端: {e}")
                # 重新创建客户端并重试
                self._initialize_client()
                if self.async_client:
                    response = await self.async_client.chat.completions.create(**params)
                    return response.choices[0].message.content
                else:
                    return f"LLM服务不可用: 重连失败"
            else:
                logger.error(f"API调用失败: {e}")
                return f"API调用出错: {str(e)}"
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            return f"API调用出错: {_describe_api_error(e)}"
    
    def is_available(self) -> bool:
        """检查LLM服务是否可用"""
        return self.async_client is not None
    
    async def chat_with_context(self, messages: List[Dict], temperature: float = 0.7) -> str:
        """带上下文的聊天调用"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                return f"LLM服务不可用: 客户端初始化失败"
        
        try:
            response = await self.async_client.chat.completions.create(
                **self._sdk_params(messages, temperature)
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"上下文聊天调用失败: {e}")
            return f"聊天调用出错: {_describe_api_error(e)}"
    
    async def stream_chat_with_context(self, messages: List[Dict], temperature: float = 0.7):
        """带上下文的流式聊天调用"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                yield f"LLM服务不可用: 客户端初始化失败"
                return
        
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=180, connect=60, sock_read=120)
            _params = self._request_params(messages, temperature, stream=True)
            _stripper = _ThinkTagStripper()
            # 流式收尾要用的状态：提前初始化，避免中途异常时未定义
            finish_reason = None
            reasoning_chars = 0
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{config.api.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.api.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "Connection": "keep-alive"
                    },
                    json=_params
                ) as resp:
                    if resp.status != 200:
                        # 关键：把 API 返回正文读出来，否则用户只能看到"状态码 401"
                        # 而不知道真正原因（key 无效 / 余额不足 / 模型不存在等）
                        raw = await resp.text()
                        detail = raw.strip()
                        try:
                            import json as _json
                            parsed = _json.loads(detail)
                            err = parsed.get("error")
                            if isinstance(err, dict) and err.get("message"):
                                detail = err["message"]
                        except Exception:
                            pass

                        if resp.status == 401:
                            hint = "API Key 无效或已过期，请在 config.json 的 api.api_key 中更换"
                        elif resp.status == 402:
                            hint = "账户余额不足，请前往 DeepSeek 平台充值"
                        elif resp.status == 429:
                            hint = "请求过于频繁，请稍后重试"
                        else:
                            hint = "请检查 config.json 中的 api.base_url / api.model"

                        logger.error(f"LLM API 调用失败: HTTP {resp.status} - {detail}")
                        # 注意：不要在这里用 emoji。Web GUI 按系统代码页编码，
                        # emoji 会抛 UnicodeEncodeError 并被下面的兜底 except 捕获，
                        # 用户只会看到"流式调用出错"，看不到真正原因。
                        yield f"data: [ERROR] LLM API 调用失败 (HTTP {resp.status})：{hint}\n\n原始返回：{detail}"
                        return
                    
                    # ---------- SSE 分片解析 ----------
                    # 网络分片**不保证**按 SSE 事件边界对齐：一行 `data: ...` 可能被
                    # 切成两个 TCP 分片。逐分片 split('\n') 会让跨界的半行两头落空
                    # （前半 JSON 解不出、后半不以 'data: ' 开头，双双丢弃），
                    # 表现就是正文**随机吞字**。
                    # 正确做法与官方示例一致：累积到缓冲区，只在收到完整事件
                    # （以空行结束）后才解析，尾巴留到下一轮。
                    #
                    # 解码同理：一个汉字占 3 字节，可能被切在两个分片之间；
                    # 用 errors='replace' 会把它变成 U+FFFD 并导致整行 JSON 解析失败。
                    # 增量解码器可以正确跨分片拼接多字节字符。
                    import codecs

                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    sse_buffer = ""

                    async for chunk in resp.content.iter_chunked(1024):
                        if not chunk:
                            break

                        sse_buffer += decoder.decode(chunk)
                        sse_buffer = sse_buffer.replace("\r\n", "\n")

                        while "\n\n" in sse_buffer:
                            event, sse_buffer = sse_buffer.split("\n\n", 1)
                            data_lines = [l for l in event.split("\n")
                                          if l.startswith("data:")]
                            if not data_lines:
                                continue
                            data_str = "\n".join(l[5:].strip()
                                                 for l in data_lines).strip()
                            if not data_str:
                                continue
                            if data_str == "[DONE]":
                                if not finish_reason:
                                    finish_reason = "done"
                                sse_buffer = ""
                                break

                            try:
                                import json as _json
                                data = _json.loads(data_str)
                            except Exception:
                                # 不再静默 continue —— 静默正是过去吞字查不出来的原因
                                logger.warning(
                                    f"[流式] 事件 JSON 解析失败，跳过 {len(data_str)} 字节")
                                continue

                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            choice0 = choices[0]
                            if choice0.get("finish_reason"):
                                finish_reason = choice0["finish_reason"]
                            delta = choice0.get("delta") or {}

                            # 思考模式：DeepSeek 会先流式输出 reasoning_content，
                            # 此时 content 键存在但值为 None。
                            # reasoning_content 是模型的内部思考，**不应混入对话正文**，
                            # 这里只记日志与字符数，不向 UI 推送。
                            reasoning = delta.get("reasoning_content")
                            if isinstance(reasoning, str) and reasoning:
                                reasoning_chars += len(reasoning)
                                logger.debug(f"[思考] {reasoning}")

                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                # 剥离模型内联在正文里的思考过程
                                # （<!--<think>...</think>--> 或 <think>...</think>）
                                safe_text = _stripper.feed(content)
                                if safe_text:
                                    import base64 as _b64
                                    b64 = _b64.b64encode(
                                        safe_text.encode('utf-8')).decode('ascii')
                                    yield f"data: {b64}\n\n"

                        if finish_reason == "done":
                            break

                    # 服务端若未以空行收尾，缓冲区里可能还剩最后一个事件
                    if sse_buffer.strip():
                        for l in sse_buffer.strip().split("\n"):
                            if not l.startswith("data: "):
                                continue
                            ds = l[6:].strip()
                            if not ds or ds == "[DONE]":
                                continue
                            try:
                                import json as _json
                                d2 = _json.loads(ds)
                                c0 = (d2.get("choices") or [{}])[0]
                                if c0.get("finish_reason"):
                                    finish_reason = c0["finish_reason"]
                                ct = (c0.get("delta") or {}).get("content")
                                if isinstance(ct, str) and ct:
                                    st = _stripper.feed(ct)
                                    if st:
                                        import base64 as _b64
                                        yield ("data: " + _b64.b64encode(
                                            st.encode('utf-8')).decode('ascii') + "\n\n")
                            except Exception:
                                pass
            # 流结束后输出缓冲中剩余内容，避免丢字
            tail = _stripper.flush()
            if tail:
                import base64 as _b64
                yield "data: " + _b64.b64encode(tail.encode('utf-8')).decode('ascii') + "\n\n"

            # ---------- 收尾如实上报截断 ----------
            # 官方明确要求：finish_reason != 'stop' 表示生成未完成，必须让调用方知道。
            # 过去完全不看这个字段，于是被 token 上限截断的回复（content 可能为空或
            # 只吐了一半）会静默当成「正常完成」写进历史 —— 用户看到的就是吞字/残缺。
            if finish_reason and finish_reason not in ("stop", "done"):
                if finish_reason == "length":
                    msg = ("回复被截断：已达 max_tokens 上限。注意思考模式的推理 token "
                           "也计入 max_tokens，可调高 api.max_tokens 或降低 reasoning_effort")
                elif finish_reason == "content_filter":
                    msg = "回复被内容过滤中断"
                else:
                    msg = f"生成未正常结束（finish_reason={finish_reason}）"
                logger.warning(
                    f"[流式] {msg}；本次推理内容约 {reasoning_chars} 字符")
                yield f"data: [WARN] {msg}\n\n"

        except Exception as e:
            logger.error(f"流式聊天调用失败: {e}")
            yield f"data: 流式调用出错: {str(e)}\n\n"

    async def stream_with_tools(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
    ):
        """带工具定义的流式调用，产出**结构化事件**而不是 SSE 文本。

        与 `stream_chat_with_context` 的区别：

        * 后者产出 ``data: <base64>`` 的 SSE 分片，直接给前端用；
        * 本方法产出 ``(kind, payload)`` 元组，供 agentic loop 内部消费。
          这样工具调用事件不会泄漏到前端 —— 前端只看到最终回答。

        Yields:
            ``("content", str)``      正文增量（已剥离内联思考标签）
            ``("reasoning", str)``    思考过程增量（不发给前端）
            ``("tool_calls", list)``  本轮完整工具调用，格式::

                [{"id": "call_x", "name": "mcp__svc__1", "arguments": "{\\"q\\":\\"x\\"}"}]

            ``("finish", str)``       结束原因（stop / tool_calls / length …）

        为什么单独写一个方法而不是复用 SSE 方法：SSE 方法的输出格式被前端
        （``ui/utils/simple_http_client.py``）写死了，改它的返回值会连带改 UI。
        新增一个内部方法对现有链路零影响。
        """
        if not self.async_client:
            self._initialize_client()
        if not self.async_client:
            yield ("error", "LLM服务不可用: 客户端初始化失败")
            return

        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=180, connect=60, sock_read=120)
            params = self._request_params(messages, temperature, stream=True, tools=tools)
            stripper = _ThinkTagStripper()
            finish_reason: Optional[str] = None
            # 累积器：tool_calls 是**增量**推送的（先给 name，再一点点给 arguments）
            pending: Dict[int, Dict[str, str]] = {}

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{config.api.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.api.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                    json=params,
                ) as resp:
                    if resp.status != 200:
                        raw = await resp.text()
                        yield ("error", f"LLM API 调用失败 (HTTP {resp.status}): {raw[:300]}")
                        return

                    import codecs

                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    buf = ""

                    async for chunk in resp.content.iter_chunked(1024):
                        if not chunk:
                            break
                        buf += decoder.decode(chunk)
                        buf = buf.replace("\r\n", "\n")

                        # 只在收到**完整事件**后解析：网络分片不按事件边界对齐，
                        # 逐片 split 会让跨界的半行两头落空（正文随机吞字）
                        while "\n\n" in buf:
                            event, buf = buf.split("\n\n", 1)
                            data_lines = [l for l in event.split("\n")
                                          if l.startswith("data:")]
                            if not data_lines:
                                continue
                            data_str = "\n".join(l[5:].strip() for l in data_lines).strip()
                            if not data_str or data_str == "[DONE]":
                                continue

                            try:
                                data = json.loads(data_str)
                            except Exception:
                                continue

                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            choice = choices[0]
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
                            delta = choice.get("delta") or {}

                            reasoning = delta.get("reasoning_content")
                            if isinstance(reasoning, str) and reasoning:
                                yield ("reasoning", reasoning)

                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                safe = stripper.feed(content)
                                if safe:
                                    yield ("content", safe)

                            # ---- 关键：tool_calls 增量拼接 ----
                            tc_deltas = delta.get("tool_calls")
                            if tc_deltas:
                                for tc in tc_deltas:
                                    idx = tc.get("index", 0)
                                    slot = pending.setdefault(
                                        idx, {"id": "", "name": "", "arguments": ""}
                                    )
                                    if tc.get("id"):
                                        slot["id"] = tc["id"]
                                    fn = tc.get("function") or {}
                                    if fn.get("name"):
                                        slot["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        # 必须累加，不能赋值 —— arguments 是流式片段
                                        slot["arguments"] += fn["arguments"]

            tail = stripper.flush()
            if tail:
                yield ("content", tail)

            if pending:
                calls = [pending[i] for i in sorted(pending)]
                # 丢掉没有名字的残片（理论上不会出现）
                calls = [c for c in calls if c.get("name")]
                if calls:
                    logger.info(
                        f"[LLM] 模型发起 {len(calls)} 个工具调用: "
                        f"{[c['name'] for c in calls]}"
                    )
                    yield ("tool_calls", calls)

            yield ("finish", finish_reason or "stop")

        except Exception as exc:
            logger.error(f"[LLM] stream_with_tools 失败: {type(exc).__name__}: {exc}")
            yield ("error", f"流式调用出错: {type(exc).__name__}: {exc}")


# 全局LLM服务实例
_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """获取全局LLM服务实例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

# 创建独立的LLM服务API
llm_app = FastAPI(
    title="LLM Service API",
    description="LLM服务API",
    version="1.0.0"
)

@llm_app.post("/llm/chat")
async def llm_chat(request: Dict[str, Any]):
    """LLM聊天接口 - 为其他模块提供LLM调用服务"""
    try:
        prompt = request.get("prompt", "")
        temperature = request.get("temperature", 0.7)
        
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt参数不能为空")
        
        llm_service = get_llm_service()
        response = await llm_service.get_response(prompt, temperature)
        
        return {
            "status": "success",
            "response": response,
            "temperature": temperature
        }
        
    except Exception as e:
        logger.error(f"LLM聊天接口异常: {e}")
        raise HTTPException(status_code=500, detail=f"LLM服务异常: {str(e)}")

