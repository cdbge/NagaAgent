#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的服务响应契约 —— 让四个服务用同一套信封。

问题
----
四个服务各自发明了成功/失败的表达方式：

===================  ==========================================
服务                 风格
===================  ==========================================
API :18000            ``{"success": bool, "error": str}``（主流）
Agent :18001          同上
MCP :18003            ``{"success": bool}`` + ``{"status": ...}`` 混用
TTS :15048            **没有 success**，只有 ``{"error": ...}``
FastAPI 自身异常      ``{"detail": ...}``
===================  ==========================================

后果（真实发生过）
------------------
客户端判断失败只认一种写法，例如 ``item.get("success") is False``。
当上游返回 ``{"error": ...}`` 而**不带 success 字段**时，
``item.get("success")`` 是 ``None``，``None is False`` 为假 —— **失败被当成成功**。

设计
----
参照 RFC 9457（Problem Details for HTTP APIs）的字段语义，但**不引入依赖**
（``fastapi-faults`` 要求 Python 3.12+，本项目是 3.11）：

* 业务响应：``ok()`` / ``fail()`` —— 统一 ``success`` + 结构化 ``error``；
* HTTP 错误：``problem()`` —— ``type`` / ``title`` / ``status`` / ``detail`` / ``code``；
* 读取一律用 ``is_ok()``，它同时认得上面**所有历史写法**，因此新旧代码可以共存。

向后兼容
--------
``success`` 字段保留为布尔值（这是既有多数派），``error`` 在失败时
**既有字符串也有 ``{code, message}``** 两种读法：

* 老代码 ``resp["error"]`` 仍拿到可读的错误文本；
* 新代码 ``resp["error"]["code"]`` 拿到稳定的机器码。
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ok", "fail", "is_ok", "error_message", "error_code",
    "problem", "install_problem_handlers", "PROBLEM_MEDIA_TYPE",
]

#: RFC 9457 规定的媒体类型
PROBLEM_MEDIA_TYPE = "application/problem+json"


# ---------------------------------------------------------------------------
# 业务响应信封
# ---------------------------------------------------------------------------

def ok(**fields: Any) -> Dict[str, Any]:
    """构造成功响应：``{"success": True, ...}``。

    用法::

        return ok(reply=text, session_id=sid)
    """
    payload: Dict[str, Any] = {"success": True}
    payload.update(fields)
    return payload


def fail(error: Any, code: Optional[str] = None,
         **fields: Any) -> Dict[str, Any]:
    """构造失败响应：``{"success": False, "error": ...}``。

    ``error`` 可以是字符串或异常对象。返回值同时满足两种读法：

    * ``resp["error"]``              -> 可读文本（字符串）
    * ``resp["error_code"]``         -> 稳定机器码

    用法::

        return fail("服务未注册", code="service_not_found", service=name)
    """
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    payload: Dict[str, Any] = {
        "success": False,
        "error": text,
        "error_code": code or "internal_error",
    }
    if code:
        payload["code"] = code
    payload.update(fields)
    return payload


# ---------------------------------------------------------------------------
# 容错读取 —— 认得所有历史写法
# ---------------------------------------------------------------------------

def is_ok(payload: Any, default: bool = False) -> bool:
    """判断一个响应是否表示成功，**兼容全部历史写法**。

    依次识别：

    ==========================================  ======
    形态                                        判定
    ==========================================  ======
    ``{"success": True}``                       成功
    ``{"success": False}``                      失败
    ``{"status": "success"}``                   成功
    ``{"status": "ok" / "completed"}``          成功
    ``{"status": "error" / "failed"}``          失败
    ``{"error": ...}``（无 success 字段）        **失败**
    ``{"detail": ...}``（FastAPI 异常）          失败
    非字典（如 None / str）                      失败
    ==========================================  ======

    ``{"error": ...}`` 这一行正是过去漏判的情形。

    ``default`` 决定**什么信号都没有**时怎么判（上面几行都没命中）。
    默认 ``False``（不假定成功）适用于「服务整体响应」；判断
    ``results`` 列表里的条目时应传 ``default=True`` —— 那里的条目可能
    只带 ``result`` 而从不带 ``success``，缺省视为失败会误报。
    """
    if not isinstance(payload, dict):
        return False

    # 1) 显式 success —— 最高优先级
    if "success" in payload:
        return payload["success"] is True

    # 2) 有错误标识就是失败（FastAPI 的 detail 也算）
    if payload.get("error") or payload.get("detail"):
        return False

    # 3) status 字段
    status = payload.get("status")
    if isinstance(status, str):
        return status.lower() in ("success", "ok", "completed", "done")
    if isinstance(status, int):
        return 200 <= status < 300

    # 4) HTTP 状态码字段
    for key in ("status_code", "code"):
        v = payload.get(key)
        if isinstance(v, int):
            return 200 <= v < 300

    # 5) 什么信号都没有：按调用方给的缺省值
    return default


def error_message(payload: Any, default: str = "") -> str:
    """尽最大努力取出可读的错误文本（兼容 error / detail / message）。"""
    if not isinstance(payload, dict):
        return str(payload) if payload else default
    for key in ("error", "detail", "message"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            inner = v.get("message") or v.get("detail")
            if isinstance(inner, str) and inner:
                return inner
        if isinstance(v, list) and v:  # FastAPI 校验错误是列表
            return "; ".join(str(x) for x in v[:3])
    return default


def error_code(payload: Any, default: str = "unknown") -> str:
    """取出稳定的机器可读错误码。"""
    if not isinstance(payload, dict):
        return default
    for key in ("error_code", "code"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
    if payload.get("detail"):
        return "http_error"
    if payload.get("error"):
        return "error"
    return default


# ---------------------------------------------------------------------------
# HTTP 错误：RFC 9457 Problem Details
# ---------------------------------------------------------------------------

def problem(status: int, code: str, detail: str,
            title: Optional[str] = None,
            type_base: str = "about:blank",
            **extensions: Any) -> Dict[str, Any]:
    """构造 RFC 9457 风格的错误体（同时带上 ``success``/``error`` 以兼容旧客户端）。

    字段语义遵循 RFC 9457：``type``（问题类型 URI）、``title``（简短摘要）、
    ``status``（HTTP 状态码）、``detail``（本次问题的具体说明）；
    ``code`` 是本项目补充的稳定机器码。
    """
    return {
        # --- 兼容既有客户端的字段 ---
        "success": False,
        "error": detail,
        "error_code": code,
        # --- RFC 9457 ---
        "type": f"{type_base.rstrip('/')}/{code}" if type_base != "about:blank"
                else "about:blank",
        "title": title or detail,
        "status": status,
        "detail": detail,
        "code": code,
        **extensions,
    }


def install_problem_handlers(app: Any, type_base: str = "about:blank") -> None:
    """给 FastAPI 应用装上统一异常处理。

    装上之后，**框架自身**产生的错误也遵循同一契约：

    * ``HTTPException``      -> 同状态码的 Problem Details
    * 请求校验失败(422)      -> ``validation_error``
    * 未捕获异常(500)        -> ``internal_error``（不泄露内部细节）

    不调用本函数时，这些错误仍是 FastAPI 默认的 ``{"detail": ...}``；
    但由于读取侧统一走 ``is_ok()``，两种形态都能正确判定。
    """
    try:
        from fastapi import Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        # 必须注册 **Starlette** 的 HTTPException：
        # FastAPI 的 HTTPException 是它的子类，而**路由未匹配的 404**
        # 抛的是 Starlette 的基类实例。只注册子类会接不住路由错误。
        from starlette.exceptions import HTTPException as StarletteHTTPException
    except Exception as e:  # pragma: no cover - fastapi 缺失时静默跳过
        logger.warning("未安装 fastapi，跳过统一异常处理安装: %s", e)
        return

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        body = problem(exc.status_code, "http_error", str(exc.detail),
                       type_base=type_base)
        return JSONResponse(status_code=exc.status_code, content=body,
                            media_type=PROBLEM_MEDIA_TYPE,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        detail = "; ".join(
            f"{'.'.join(str(x) for x in err.get('loc', []))}: {err.get('msg', '')}"
            for err in exc.errors()[:5]
        ) or "请求参数校验失败"
        body = problem(422, "validation_error", detail, type_base=type_base,
                       errors=exc.errors()[:5])
        return JSONResponse(status_code=422, content=body,
                            media_type=PROBLEM_MEDIA_TYPE)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        # 不外泄内部细节，只记日志
        body = problem(500, "internal_error", "服务器内部错误",
                       type_base=type_base)
        return JSONResponse(status_code=500, content=body,
                            media_type=PROBLEM_MEDIA_TYPE)

    logger.info("已安装统一异常处理（RFC 9457 Problem Details）")
