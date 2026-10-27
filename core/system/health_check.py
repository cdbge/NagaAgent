#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务健康检查与连通性诊断。

用途
====

启动自检（`system_checker.py`）回答的是「**能不能启动**」——Python 版本、
依赖装没装、配置文件在不在。

本模块回答的是另一个问题：「**跑起来之后，各个服务到底通不通**」。
两者不能互相替代：依赖全都装了但 TTS 端口被 Windows 保留段占掉，
启动自检是绿的，实际却不能用。这类问题只能靠端口/HTTP 探活发现。

检查项
------

**服务连通性**（并发探测，返回 HEALTHY / DEGRADED / UNHEALTHY / UNKNOWN）

====================  ============================================
服务                  判定方式
====================  ============================================
api_server            端口 + ``GET /health``
agent_server          端口 + ``GET /health``
mcp_server            端口 + ``GET /status``
tts_server            端口（TTS 只提供 POST ``/v1/audio/speech``，
                      没有可用的 GET 探活端点，因此只测端口）
asr_server            端口（仅在启用语音输入时检查）
====================  ============================================

**环境诊断**（不依赖服务是否在跑）

* ``dependencies`` —— 关键依赖能否 import。区分「必需」与「可选」：
  可选依赖缺失只记为降级，不影响整体判定。
* ``storage`` —— 数据目录可写性。日志/音频临时目录不可写会导致
  运行中静默失败（TTS 生成了音频却写不出去）。

设计取舍
--------

* 探测全部**并发**执行，总耗时取决于最慢的一项（通常 2–3 秒）。
* 启动早期服务可能还在监听中，因此 api_server 用 ``wait_port_ready``
  做有限重试；其余服务不重试（启动流程里它们先于 API 就绪）。
* 可选能力缺失记为 DEGRADED 而不是 UNHEALTHY —— 否则「没装 dashscope」
  会被当成致命故障，把真正的问题淹没掉。
* 任何单项检查内部异常都被捕获并转成 UNKNOWN，绝不向外抛 ——
  健康检查本身不能成为新的故障源。

用法
----

    # 程序内
    from core.system.health_check import get_health_checker, perform_startup_health_check
    results, summary = await perform_startup_health_check()

    # 命令行（打印摘要后退出，非全绿时退出码 1，便于脚本/CI 判断）
    python -m core.system.health_check
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """服务状态。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """单个检查项的结果。"""

    service_name: str
    status: ServiceStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# 依赖清单：区分必需与可选
#
# 这份清单来自实际踩过的坑，不是从依赖文件抄的：
#   * dashscope 是被移除的 nagaagent-core 垫片顺带装上的，删掉后漏声明，
#     导致实时语音初始化直接崩 —— 但它只影响语音输入，不该判整体不健康。
#   * edge_tts / gevent 缺了 TTS 服务根本起不来，属于必需。
#   * live2d / OpenGL 缺了只是 Live2D 不可用，应降级而非致命。
# ---------------------------------------------------------------------------
_REQUIRED_DEPS = [
    ("fastmcp", "MCP 工具服务"),
    ("kuzu", "默认图存储后端"),
    ("edge_tts", "TTS 语音合成"),
    ("gevent", "TTS HTTP 服务器"),
    ("httpx", "服务间 HTTP 调用"),
]

_OPTIONAL_DEPS = [
    ("dashscope", "实时语音输入（云）"),
    ("live2d", "Live2D 模型渲染"),
    ("OpenGL", "Live2D 底层渲染"),
    ("playwright", "浏览器 Agent"),
]


class HealthChecker:
    """健康检查器。"""

    def __init__(self) -> None:
        from core.system.config import config, get_server_port

        self.ports = {
            "api_server": get_server_port("api_server"),
            "agent_server": get_server_port("agent_server"),
            "mcp_server": get_server_port("mcp_server"),
            "tts_server": get_server_port("tts_server"),
            "asr_server": get_server_port("asr_server"),
        }
        self.api_enabled = bool(
            getattr(config.api_server, "enabled", True)
            and getattr(config.api_server, "auto_start", True)
        )
        # 语音输入是否启用：决定要不要检查 ASR 端口
        self.voice_input_enabled = bool(
            getattr(config, "system", None)
            and getattr(config.system, "voice_enabled", False)
        )

    # -- 通用探针 ---------------------------------------------------------

    async def check_port(self, host: str, port: int, timeout: float = 2.0) -> bool:
        """TCP 端口是否可连接。"""
        if not port:
            return False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False

    async def wait_port_ready(
        self,
        host: str,
        port: int,
        retries: int = 6,
        interval_seconds: float = 0.5,
        timeout: float = 2.0,
    ) -> bool:
        """等待端口就绪（用于启动阶段的抖动）。"""
        for i in range(max(1, retries)):
            if await self.check_port(host, port, timeout=timeout):
                return True
            if i < retries - 1:
                await asyncio.sleep(interval_seconds)
        return False

    async def check_http_endpoint(
        self, url: str, timeout: float = 5.0, method: str = "GET"
    ) -> Dict[str, Any]:
        """请求一个 HTTP 端点，返回结构化结果（不抛异常）。"""
        try:
            import httpx
        except ImportError:
            return {
                "success": False,
                "error": "httpx 未安装，无法进行 HTTP 探活",
                "error_type": "missing_dependency",
            }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url)
                latency_ms = (time.time() - start) * 1000
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "latency_ms": round(latency_ms, 2),
                    "ok": 200 <= resp.status_code < 300,
                }
        except Exception as exc:  # 连接拒绝 / 超时 / 其它
            name = type(exc).__name__
            if "Connect" in name:
                return {"success": False, "error": "无法连接",
                        "error_type": "connection_refused"}
            if "Timeout" in name:
                return {"success": False, "error": "连接超时",
                        "error_type": "timeout"}
            return {"success": False, "error": str(exc), "error_type": "unknown"}

    @staticmethod
    def _grade(checks: List[Dict[str, Any]], healthy_msg: str,
               degraded_msg: str, unhealthy_msg: str) -> ServiceStatus:
        """按通过比例给出状态。"""
        passed = sum(1 for c in checks if c.get("passed"))
        if checks and passed == len(checks):
            return ServiceStatus.HEALTHY
        if passed > 0:
            return ServiceStatus.DEGRADED
        return ServiceStatus.UNHEALTHY

    async def _check_http_service(
        self,
        name: str,
        port_key: str,
        path: str,
        wait_ready: bool = False,
        extra_checks: Optional[List[Dict[str, Any]]] = None,
    ) -> HealthCheckResult:
        """通用「端口 + HTTP 端点」检查。"""
        port = self.ports[port_key]
        checks: List[Dict[str, Any]] = []

        if wait_ready:
            port_ok = await self.wait_port_ready(
                "127.0.0.1", port, retries=8, interval_seconds=0.5, timeout=1.5
            )
        else:
            port_ok = await self.check_port("127.0.0.1", port)

        checks.append({
            "name": "port_connectivity",
            "passed": port_ok,
            "message": f"端口 {port} {'可连接' if port_ok else '不可连接'}",
        })
        if not port_ok:
            return HealthCheckResult(
                service_name=name,
                status=ServiceStatus.UNHEALTHY,
                message=f"{name} 端口 {port} 不可用",
                checks=checks,
                details={"port": port},
            )

        http = await self.check_http_endpoint(f"http://127.0.0.1:{port}{path}")
        checks.append({
            "name": f"endpoint{path}",
            "passed": bool(http.get("success") and http.get("ok")),
            "details": http,
        })
        if extra_checks:
            checks.extend(extra_checks)

        passed = sum(1 for c in checks if c.get("passed"))
        if passed == len(checks):
            status, msg = ServiceStatus.HEALTHY, f"{name} 健康 ({port})"
        elif passed > 0:
            status = ServiceStatus.DEGRADED
            msg = f"{name} 部分功能可用 ({passed}/{len(checks)})"
        else:
            status, msg = ServiceStatus.UNHEALTHY, f"{name} 不健康"

        return HealthCheckResult(
            service_name=name,
            status=status,
            message=msg,
            checks=checks,
            details={"port": port},
            latency_ms=http.get("latency_ms"),
        )

    # -- 各服务 -----------------------------------------------------------

    async def check_api_server(self) -> HealthCheckResult:
        """检查 API 服务器（端口 + /health）。"""
        if not self.api_enabled:
            return HealthCheckResult(
                service_name="api_server",
                status=ServiceStatus.HEALTHY,
                message="API Server 已禁用，跳过检查",
                details={"enabled": False},
            )
        return await self._check_http_service(
            "api_server", "api_server", "/health", wait_ready=True
        )

    async def check_agent_server(self) -> HealthCheckResult:
        """检查 Agent 服务器（端口 + /health）。"""
        return await self._check_http_service("agent_server", "agent_server", "/health")

    async def check_mcp_server(self) -> HealthCheckResult:
        """检查 MCP 服务器（端口 + /status）。"""
        return await self._check_http_service("mcp_server", "mcp_server", "/status")

    async def check_tts_server(self) -> HealthCheckResult:
        """检查 TTS 服务器（只探端口）。

        TTS 是 Flask 应用且只注册了 ``POST /v1/audio/speech``，
        没有可用于 GET 探活的端点。真正的「能不能合成」需要发起一次
        合成请求，代价是一个网络往返 + 磁盘写入，不适合放进启动检查。
        这里退一步只验证端口 —— 它已经能覆盖最常见的那类故障
        （端口被占 / 服务没起来 / Windows 端口保留段）。
        """
        port = self.ports["tts_server"]
        port_ok = await self.check_port("127.0.0.1", port)
        checks = [{
            "name": "port_connectivity",
            "passed": port_ok,
            "message": f"端口 {port} {'可连接' if port_ok else '不可连接'}",
        }]
        return HealthCheckResult(
            service_name="tts_server",
            status=ServiceStatus.HEALTHY if port_ok else ServiceStatus.UNHEALTHY,
            message=(f"TTS Server 端口可用 ({port})" if port_ok
                     else f"TTS Server 端口 {port} 不可用"),
            checks=checks,
            details={"port": port, "note": "未做合成验证，仅端口探活"},
        )

    async def check_asr_server(self) -> HealthCheckResult:
        """检查本地 ASR 服务。

        只有 ``voice_mode = "local"`` 时才真的依赖本地 FunASR：

        * ``local``    —— 本地 FunASR，端口不通就是功能不可用；
        * ``hybrid``   —— 通义千问 ASR + API，**不用本地服务**；
        * ``end2end``  —— 端到端云端，更不需要本地服务；
        * ``auto``     —— 启动时按可用性自动挑，本地服务只是候选之一。

        因此非 local 模式下本地 ASR 没在跑是**正常状态**，报 HEALTHY，
        否则每次检查都是 degraded，把真正的问题淹没掉。
        """
        if not self.voice_input_enabled:
            return HealthCheckResult(
                service_name="asr_server",
                status=ServiceStatus.HEALTHY,
                message="语音输入未启用，跳过检查",
                details={"enabled": False},
            )

        mode = "auto"
        try:
            from core.system.config import config
            mode = str(getattr(config.voice_realtime, "voice_mode", "auto") or "auto").lower()
        except Exception:
            pass

        port = self.ports["asr_server"]
        port_ok = await self.check_port("127.0.0.1", port, timeout=1.0)
        checks = [{
            "name": "port_connectivity",
            "passed": port_ok,
            "message": f"端口 {port} {'可连接' if port_ok else '不可连接'}",
        }]

        if mode != "local":
            # 当前模式不用本地 ASR —— 端口不通属于预期
            return HealthCheckResult(
                service_name="asr_server",
                status=ServiceStatus.HEALTHY,
                message=(f"当前语音模式为 {mode}，不依赖本地 ASR"
                         + ("（本地服务在跑）" if port_ok else "（本地服务未运行，属正常）")),
                checks=checks,
                details={"port": port, "mode": mode, "required": False},
            )

        return HealthCheckResult(
            service_name="asr_server",
            status=ServiceStatus.HEALTHY if port_ok else ServiceStatus.UNHEALTHY,
            message=(f"本地 ASR 服务可用 ({port})" if port_ok
                     else f"语音模式为 local，但本地 ASR 未运行 ({port})"),
            checks=checks,
            details={"port": port, "mode": mode, "required": True},
        )

    # -- 环境诊断 ---------------------------------------------------------

    async def check_dependencies(self) -> HealthCheckResult:
        """检查关键依赖能否 import（同步操作，包一层保持接口一致）。"""
        import importlib.util

        checks: List[Dict[str, Any]] = []
        missing_required: List[str] = []
        missing_optional: List[str] = []

        for mod, desc in _REQUIRED_DEPS:
            ok = importlib.util.find_spec(mod) is not None
            checks.append({
                "name": f"dep:{mod}",
                "passed": ok,
                "message": f"{desc}（{mod}）{'已就绪' if ok else '**缺失**'}",
            })
            if not ok:
                missing_required.append(mod)

        for mod, desc in _OPTIONAL_DEPS:
            try:
                ok = importlib.util.find_spec(mod) is not None
            except (ImportError, ValueError):
                ok = False
            checks.append({
                "name": f"dep:{mod}",
                "passed": ok,
                "message": f"{desc}（{mod}）{'已就绪' if ok else '未安装（功能受限）'}",
                "optional": True,
            })
            if not ok:
                missing_optional.append(mod)

        if missing_required:
            status = ServiceStatus.UNHEALTHY
            msg = f"缺失必需依赖: {', '.join(missing_required)}（请运行 uv sync）"
        elif missing_optional:
            status = ServiceStatus.DEGRADED
            msg = f"缺失可选依赖: {', '.join(missing_optional)}（对应功能不可用）"
        else:
            status = ServiceStatus.HEALTHY
            msg = "关键依赖齐备"

        return HealthCheckResult(
            service_name="dependencies",
            status=status,
            message=msg,
            checks=checks,
            details={"missing_required": missing_required,
                     "missing_optional": missing_optional},
        )

    async def check_storage(self) -> HealthCheckResult:
        """检查数据目录可写性。

        日志目录 / TTS 音频临时目录不可写时会**静默失败**：服务照常响应，
        但日志和音频都落不了盘，排查时看不到任何线索。
        """
        from pathlib import Path

        checks: List[Dict[str, Any]] = []
        targets = []

        try:
            from core.system.config import get_data_dir  # type: ignore
            targets.append(("data", Path(get_data_dir()) / "logs"))
        except Exception:
            pass

        repo_root = Path(__file__).resolve().parent.parent.parent
        targets.append(("logs", repo_root / "data" / "logs"))
        targets.append(("audio_temp", repo_root / "data" / "logs" / "audio_temp"))

        ok_count = 0
        for label, p in targets:
            try:
                p.mkdir(parents=True, exist_ok=True)
                probe = p / ".health_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                writable = True
            except Exception as exc:
                writable = False
                checks.append({
                    "name": f"write:{label}",
                    "passed": False,
                    "message": f"{p} 不可写: {type(exc).__name__}",
                })
                continue
            ok_count += 1
            checks.append({
                "name": f"write:{label}",
                "passed": writable,
                "message": f"{label} 目录可写",
            })

        status = (ServiceStatus.HEALTHY if ok_count == len(targets)
                  else ServiceStatus.DEGRADED)
        return HealthCheckResult(
            service_name="storage",
            status=status,
            message=f"存储目录 {ok_count}/{len(targets)} 可写",
            checks=checks,
        )

    # -- 汇总 -------------------------------------------------------------

    async def check_all(self) -> Dict[str, HealthCheckResult]:
        """并发检查所有项目。单项异常降级为 UNKNOWN，绝不向外抛。"""
        tasks = {
            "api_server": self.check_api_server(),
            "agent_server": self.check_agent_server(),
            "mcp_server": self.check_mcp_server(),
            "tts_server": self.check_tts_server(),
            "asr_server": self.check_asr_server(),
            "dependencies": self.check_dependencies(),
            "storage": self.check_storage(),
        }

        results: Dict[str, HealthCheckResult] = {}
        for service_name, task in tasks.items():
            try:
                results[service_name] = await task
            except Exception as exc:
                logger.error(f"[HealthCheck] 检查 {service_name} 失败: {exc}")
                results[service_name] = HealthCheckResult(
                    service_name=service_name,
                    status=ServiceStatus.UNKNOWN,
                    message=f"检查失败: {type(exc).__name__}: {exc}",
                )
        return results

    def get_summary(self, results: Dict[str, HealthCheckResult]) -> Dict[str, Any]:
        """把逐项结果汇总成总体状态。"""
        counts = {
            ServiceStatus.HEALTHY: 0,
            ServiceStatus.DEGRADED: 0,
            ServiceStatus.UNHEALTHY: 0,
            ServiceStatus.UNKNOWN: 0,
        }
        for r in results.values():
            counts[r.status] = counts.get(r.status, 0) + 1

        total = len(results)
        health_percent = (counts[ServiceStatus.HEALTHY] / total * 100) if total else 0.0

        if counts[ServiceStatus.UNHEALTHY] > 0 or counts[ServiceStatus.UNKNOWN] > 0:
            overall = ServiceStatus.UNHEALTHY
        elif counts[ServiceStatus.DEGRADED] > 0:
            overall = ServiceStatus.DEGRADED
        else:
            overall = ServiceStatus.HEALTHY

        return {
            "overall_status": overall.value,
            "overall_health_percent": round(health_percent, 2),
            "total_services": total,
            "healthy": counts[ServiceStatus.HEALTHY],
            "degraded": counts[ServiceStatus.DEGRADED],
            "unhealthy": counts[ServiceStatus.UNHEALTHY],
            "unknown": counts[ServiceStatus.UNKNOWN],
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """获取健康检查器单例。"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


async def perform_startup_health_check():
    """执行一次健康检查并打日志，返回 (results, summary)。

    注意：**不抛异常**。健康检查是诊断工具，它的失败不应该阻止程序启动。
    """
    logger.info("[HealthCheck] 开始服务健康检查...")

    checker = get_health_checker()
    results = await checker.check_all()
    summary = checker.get_summary(results)

    logger.info(
        f"[HealthCheck] 完成: 总体 {summary['overall_status']}，"
        f"健康度 {summary['overall_health_percent']}%"
    )

    for service_name, result in results.items():
        symbol = {
            ServiceStatus.HEALTHY: "OK",
            ServiceStatus.DEGRADED: "WARN",
            ServiceStatus.UNHEALTHY: "FAIL",
            ServiceStatus.UNKNOWN: "UNKNOWN",
        }[result.status]
        log = logger.info if result.status == ServiceStatus.HEALTHY else logger.warning
        log(f"[HealthCheck]   [{symbol}] {service_name}: {result.message}")
        for check in result.checks:
            if not check.get("passed"):
                logger.warning(
                    f"[HealthCheck]       - {check.get('name')}: "
                    f"{check.get('message', '失败')}"
                )

    return results, summary


# ---------------------------------------------------------------------------
# 命令行入口：python -m core.system.health_check
# ---------------------------------------------------------------------------
def _main() -> int:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    results, summary = asyncio.run(perform_startup_health_check())

    print()
    print("=" * 66)
    print(f"总体状态 : {summary['overall_status']}")
    print(f"健康度   : {summary['overall_health_percent']}%")
    print(f"服务统计 : 健康 {summary['healthy']} / 降级 {summary['degraded']} "
          f"/ 异常 {summary['unhealthy']} / 未知 {summary['unknown']}")
    print("=" * 66)

    # 非全绿时退出码 1，便于脚本/CI 判断
    return 0 if summary["overall_status"] == ServiceStatus.HEALTHY.value else 1


if __name__ == "__main__":
    raise SystemExit(_main())
