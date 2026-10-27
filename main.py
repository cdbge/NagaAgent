# pyinstaller适配
# 崩溃日志：faulthandler 在收到致命信号（段错误/Qt qFatal abort）时
# 把 C 层堆栈写进 data/crash.log —— 这是排查「进程无声消失」的关键证据。
try:
    import faulthandler as _fh
    import os as _os

    _os.makedirs("data", exist_ok=True)
    _crash_file = open("data/crash.log", "w", buffering=1, encoding="utf-8", errors="replace")
    _fh.enable(file=_crash_file, all_threads=True)
except Exception:
    pass
# 控制台/重定向输出的编码守卫：
# Windows 默认 GBK，print 到文件时遇到非 GBK 字符会抛 UnicodeEncodeError，
# 直接把进程打死。这里统一转成 UTF-8，别再让输出方式影响能否启动。
try:
    import sys as _sys

    for _stream in (_sys.stdout, _sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import os
import sys
if os.path.exists("_internal"):
    os.chdir("_internal")

# 检测是否在打包环境中
# PyInstaller打包后的程序会设置sys.frozen属性
IS_PACKAGED = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

# 标准库导入
import asyncio
import logging
import socket
import threading
import warnings
import requests

# 过滤弃用警告，提升启动体验
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.legacy.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*WebSocketServerProtocol.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*uvicorn.*")

# 修复Windows socket兼容性问题
if not hasattr(socket, 'EAI_ADDRFAMILY'):
    # Windows系统缺少这些错误码，添加兼容性常量
    socket.EAI_ADDRFAMILY = -9
    socket.EAI_AGAIN = -3
    socket.EAI_BADFLAGS = -1
    socket.EAI_FAIL = -4
    socket.EAI_MEMORY = -10
    socket.EAI_NODATA = -5
    socket.EAI_NONAME = -2
    socket.EAI_OVERFLOW = -12
    socket.EAI_SERVICE = -8
    socket.EAI_SOCKTYPE = -7
    socket.EAI_SYSTEM = -11

# 第三方库导入
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

# 本地模块导入
from core.system.system_checker import run_system_check, run_quick_check
from core.system.config import config, AI_NAME

# V14版本已移除早期拦截器，采用运行时猴子补丁

# conversation_core已删除，相关功能已迁移到apiserver
from core.summer_memory.memory_manager import memory_manager
from core.summer_memory.task_manager import task_manager
from ui.pyqt_chat_window import ChatWindow
from ui.tray.console_tray import integrate_console_tray

# 配置日志（级别与第三方库噪音压制统一在 core/system/logging_setup.py）
from core.system.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("summer_memory")

# 服务管理器类
class ServiceManager:
    """服务管理器 - 统一管理所有后台服务"""
    
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.bg_thread = None
        self.api_thread = None
        self.agent_thread = None
        self.tts_thread = None
        self._services_ready = False  # 服务就绪状态
    
    def start_background_services(self):
        """启动后台服务 - 异步非阻塞"""
        # 启动后台任务管理器
        self.bg_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.bg_thread.start()
        logger.info(f"后台服务线程已启动: {self.bg_thread.name}")
        
        # 移除阻塞等待，改为异步检查
        # time.sleep(1)  # 删除阻塞等待
    
    def _run_event_loop(self):
        """运行事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._init_background_services())
        logger.info("后台服务事件循环已启动")
    
    async def _init_background_services(self):
        """初始化后台服务 - 优化启动流程"""
        logger.info("正在启动后台服务...")
        try:
            # 任务管理器由memory_manager自动启动，无需手动启动
            # await start_task_manager()
            
            # 标记服务就绪
            self._services_ready = True
            logger.info(f"任务管理器状态: running={task_manager.is_running}")
            
            # 保持事件循环活跃
            while True:
                await asyncio.sleep(3600)  # 每小时检查一次
        except Exception as e:
            logger.error(f"后台服务异常: {e}")
    

    @staticmethod
    def _excluded_port_ranges():
        """读 Windows 的 TCP 排除端口段（Hyper-V / WinNAT 动态预留）。

        落在排除段里的端口 bind 会抛 WSAEACCES，和一般意义的被占用不同，
        以前只报端口已被占用，会误导排查方向。
        """
        ranges = []
        try:
            import subprocess

            out = subprocess.run(
                ["netsh", "interface", "ipv4", "show", "excludedportrange",
                 "protocol=tcp"],
                capture_output=True, timeout=5, text=True,
                encoding="utf-8", errors="ignore").stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    ranges.append((int(parts[0]), int(parts[1])))
        except Exception:
            pass
        return ranges

    def _warn_if_excluded(self, name, port):
        """端口落在 Windows 排除段时给出明确提示。"""
        try:
            port = int(port)
        except Exception:
            return False
        for lo, hi in self._excluded_port_ranges():
            if lo <= port <= hi:
                print(
                    f"   [X] {name} 端口 {port} 落在 Windows 排除段 "
                    f"{lo}-{hi} 内（Hyper-V/WinNAT 预留），bind 会失败."
                )
                print("      请把 config.json 里该端口改到排除段外（如 18000 段）。")
                return True
        return False
    def check_port_available(self, host, port):
        """判断端口能否用于启动服务。

        以前只做 `bind()` 然后看有没有异常 —— 这在 Windows 上会**误判**：
        刚退出的进程其监听 socket 会残留在 TIME_WAIT，此时 bind 直接报
        WSAEADDRINUSE，于是被当成"端口被占用"，服务全部跳过启动
        （表现就是重启后只有 TTS 起来，8000/8001/8003 全空）。

        正确判据是"有没有**活的**监听者"，用 connect 探测：
        连得上 = 有服务在听；连不上 = 空闲（TIME_WAIT 不影响新进程 bind，
        因为真实服务启动时都带 SO_REUSEADDR）。
        """
        probe_host = host if host and host not in ("0.0.0.0", "::") else "127.0.0.1"
        try:
            with socket.create_connection((probe_host, int(port)), timeout=0.5):
                return False          # 有活服务在监听
        except OSError:
            return True               # 没人听，可以启动
    
    def start_all_servers(self):
        """并行启动所有服务：API(可选)、MCP、Agent、TTS - 优化版本"""
        print("[启动] 正在并行启动所有服务...")
        print("=" * 50)
        threads = []
        service_status = {}  # 服务状态跟踪
        
        try:
            self._init_proxy_settings()
            # 预检查所有端口，减少重复检查
            from core.system.config import get_server_port
            port_checks = {
                'api': config.api_server.enabled and config.api_server.auto_start and 
                      self.check_port_available(config.api_server.host, config.api_server.port),
                'mcp': self.check_port_available("0.0.0.0", get_server_port("mcp_server")),
                'agent': self.check_port_available("0.0.0.0", get_server_port("agent_server")),
                'tts': self.check_port_available("0.0.0.0", config.tts.port)
            }
            
            # API服务器（可选）
            if port_checks['api']:
                api_thread = threading.Thread(target=self._start_api_server, daemon=True)
                threads.append(("API", api_thread))
                service_status['API'] = "准备启动"
            elif config.api_server.enabled and config.api_server.auto_start:
                print(f"[WARN]  API服务器: 端口 {config.api_server.port} 已被占用，跳过启动")
                service_status['API'] = "端口占用"
            
            # MCP服务器
            if port_checks['mcp']:
                mcp_thread = threading.Thread(target=self._start_mcp_server, daemon=True)
                threads.append(("MCP", mcp_thread))
                service_status['MCP'] = "准备启动"
            else:
                print(f"[WARN]  MCP服务器: 端口 {get_server_port('mcp_server')} 已被占用，跳过启动")
                service_status['MCP'] = "端口占用"
            
            # Agent服务器
            if port_checks['agent']:
                agent_thread = threading.Thread(target=self._start_agent_server, daemon=True)
                threads.append(("Agent", agent_thread))
                service_status['Agent'] = "准备启动"
            else:
                print(f"[WARN]  Agent服务器: 端口 {get_server_port('agent_server')} 已被占用，跳过启动")
                service_status['Agent'] = "端口占用"
            
            # TTS服务器
            if port_checks['tts']:
                tts_thread = threading.Thread(target=self._start_tts_server, daemon=True)
                threads.append(("TTS", tts_thread))
                service_status['TTS'] = "准备启动"
            else:
                print(f"[WARN]  TTS服务器: 端口 {config.tts.port} 已被占用，跳过启动")
                service_status['TTS'] = "端口占用"
            
            # 显示服务启动计划
            print("\n 服务启动计划:")
            for service, status in service_status.items():
                if status == "准备启动":
                    print(f"   [刷新] {service}服务器: 正在启动...")
                else:
                    print(f"   [WARN]  {service}服务器: {status}")
            
            print("\n[启动] 开始启动服务...")
            print("-" * 30)
            
            # 批量启动所有线程
            for name, thread in threads:
                thread.start()
                print(f"[OK] {name}服务器: 启动线程已创建")
            
            print("-" * 30)
            print(f"[完成] 服务启动完成: {len(threads)} 个服务正在后台运行")
            print("=" * 50)

            # 后台做一次连通性诊断：等服务真正监听后跑，不占用启动时间。
            # 它只打日志，不影响启动结果 —— 依赖装齐了但端口不通这类问题，
            # 启动自检发现不了，只有真正探活才能看见。
            threading.Thread(
                target=self._delayed_health_check,
                name="health-check",
                daemon=True,
            ).start()

        except Exception as e:
            print(f"[FAIL] 并行启动服务异常: {e}")

    def _delayed_health_check(self):
        """延迟执行健康检查（等各服务真正监听后再探活）。

        线程里没有现成的事件循环，需要自己起一个跑 asyncio 版本。

        设计参考：API 在慢机器上可能晚于首次检查就绪，因此首次全是
        unhealthy 时再等 12 秒复检一次，避免启动早期误报。
        """
        import asyncio as _asyncio

        try:
            from core.system.health_check import perform_startup_health_check
        except Exception as exc:
            print(f"[健康检查] 模块不可用: {exc}")
            return

        def _run():
            async def _inner():
                # 等服务监听（低性能环境启动更慢，缓冲取长一点）
                await _asyncio.sleep(6)
                results, _summary = await perform_startup_health_check()

                api_result = results.get("api_server")
                api_unhealthy = (
                    api_result is not None
                    and getattr(getattr(api_result, "status", None), "value", "")
                    == "unhealthy"
                )
                if api_unhealthy:
                    print("[健康检查] API 尚未就绪，12 秒后复检一次")
                    await _asyncio.sleep(12)
                    await perform_startup_health_check()

            _asyncio.run(_inner())

        try:
            _run()
        except Exception as exc:
            # 诊断工具自身出错绝不能影响主流程
            print(f"[健康检查] 执行失败（不影响运行）: {exc}")

    def _init_proxy_settings(self):
        """初始化代理设置：若不启用代理，则清空系统代理环境变量"""
        # 检测 applied_proxy 状态
        if not config.api.applied_proxy:  # 当 applied_proxy 为 False 时
            print("检测到不启用代理，正在清空系统代理环境变量...")

            # 清空 HTTP/HTTPS 代理环境变量（跨平台兼容）
            proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]
            for var in proxy_vars:
                if var in os.environ:
                    del os.environ[var]  # 删除环境变量
                    print(f"已清除代理环境变量: {var}")

            # 额外：确保 requests Session 没有全局代理配置
            global_session = requests.Session()
            if global_session.proxies:
                global_session.proxies.clear()
                print("已清空 requests Session 全局代理配置")
    def _start_api_server(self):
        """内部API服务器启动方法"""
        try:
            import uvicorn

            uvicorn.run(
                "servers.apiserver.api_server:app",
                host=config.api_server.host,
                port=config.api_server.port,
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except ImportError as e:
            print(f"   [FAIL] API服务器依赖缺失: {e}")
        except Exception as e:
            print(f"   [FAIL] API服务器启动失败: {e}")
    
    def _start_mcp_server(self):
        """内部MCP服务器启动方法"""
        try:
            import uvicorn
            from servers.mcpserver.mcp_server import app
            from core.system.config import get_server_port
            
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=get_server_port("mcp_server"),
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except Exception as e:
            print(f"   [FAIL] MCP服务器启动失败: {e}")
    
    def _start_agent_server(self):
        """内部Agent服务器启动方法"""
        try:
            import uvicorn
            from servers.agentserver.agent_server import app
            from core.system.config import get_server_port
            
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=get_server_port("agent_server"),
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except Exception as e:
            print(f"   [FAIL] Agent服务器启动失败: {e}")
    
    def _start_tts_server(self):
        """内部TTS服务器启动方法"""
        try:
            from core.voice.output.start_voice_service import start_http_server
            start_http_server()
        except Exception as e:
            print(f"   [FAIL] TTS服务器启动失败: {e}")
    

    
    def _start_mqtt_status_check(self):
        """启动物联网通讯连接并显示状态（异步）"""
        try:
            # 检查是否配置了物联网通讯
            if not config.mqtt.enabled:
                return  # 静默跳过，不输出日志
            
            # 在新线程中异步执行物联网通讯连接
            def run_mqtt_connection():
                try:
                    import sys
                    import os
                    # 添加项目根目录到Python路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    sys.path.insert(0, project_root)
                    
                    try:
                        from core.mqtt_tool.device_switch import device_manager
                        
                        # 尝试连接物联网设备
                        if hasattr(device_manager, 'connect'):
                            success = device_manager.connect()
                            if success:
                                print(" 物联网通讯状态: 已连接")
                            else:
                                print("[WARN] 物联网通讯状态: 连接失败（将在使用时重试）")
                        else:
                            print("[FAIL] 物联网通讯功能不可用")
                            
                    except Exception as e:
                        print(f"[WARN] 物联网通讯连接失败: {e}")
                        
                except Exception as e:
                    print(f"[FAIL] 物联网通讯连接异常: {e}")
            
            # 启动后台线程
            import threading
            mqtt_thread = threading.Thread(target=run_mqtt_connection, daemon=True)
            mqtt_thread.start()
            
        except Exception as e:
            print(f"[FAIL] 物联网通讯连接启动失败: {e}")
    
    
    def _init_voice_system(self):
        """初始化语音处理系统"""
        try:
            if config.system.voice_enabled:
                logger.info("语音功能已启用（语音输入+输出），由UI层管理")
            else:
                logger.info("语音功能已禁用")
        except Exception as e:
            logger.warning(f"语音系统初始化失败: {e}")
    
    def _init_memory_system(self):
        """初始化记忆系统"""
        try:
            if memory_manager and memory_manager.enabled:
                logger.info("夏园记忆系统已初始化")
            else:
                logger.info("夏园记忆系统已禁用")
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")
    
    def _init_mcp_services(self):
        """初始化MCP服务系统"""
        try:
            # MCP服务现在由mcpserver独立管理，这里只需要记录日志
            logger.info("MCP服务系统由mcpserver独立管理")
        except Exception as e:
            logger.error(f"MCP服务系统初始化失败: {e}")
    
    
def show_help():
    print('系统命令: 清屏, 查看索引, 帮助, 退出')

def show_index():
    print('主题分片索引已集成，无需单独索引查看')

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

# 延迟初始化 - 避免启动时阻塞
def _lazy_init_services():
    """延迟初始化服务 - 在需要时才初始化"""
    global service_manager, n
    if not hasattr(_lazy_init_services, '_initialized'):
        # 初始化服务管理器
        service_manager = ServiceManager()
        service_manager.start_background_services()
        
        # conversation_core已删除，相关功能已迁移到apiserver
        n = None
        
        # 初始化各个系统（conversation_core已删除，直接初始化服务）
        service_manager._init_mcp_services()
        service_manager._init_voice_system()
        service_manager._init_memory_system()
        # service_manager._load_persistent_context()  # 删除重复加载，UI渲染时会自动加载
        
        # 初始化进度文件
        #with open('./ui/styles/progress.txt', 'w') as f:
            #f.write('0')
        #何意味？注释了 by Null
        
        # 显示系统状态
        print("=" * 30)
        print(f"GRAG状态: {'启用' if memory_manager.enabled else '禁用'}")
        if memory_manager.enabled:
            stats = memory_manager.get_memory_stats()
            try:
                from core.summer_memory.quintuple_graph import get_backend_info
                info = get_backend_info()
                backend = info.get("backend") or "本地文件"
                counts = info.get("counts") or {}
                state = "就绪" if info.get("available") else "不可用(已降级为本地文件)"
                print(f"图存储后端: {backend} ({state})")
                if counts:
                    print(f"  知识图谱: {counts.get('entities', 0)} 实体 / {counts.get('relations', 0)} 关系")
            except Exception as exc:
                print(f"图存储后端: 状态未知 ({exc})")
        print("=" * 30)
        print(f'{AI_NAME}系统已启动')
        print("=" * 30)
        
        # 启动服务（并行异步）
        service_manager.start_all_servers()

        # 启动物联网通讯连接
        service_manager._start_mqtt_status_check()
        print("⏳ 物联网通讯正在后台初始化连接...")
        
        show_help()
        
        _lazy_init_services._initialized = True

# NagaAgent适配器 - 优化重复初始化
class NagaAgentAdapter:
    def __init__(s):
        # 使用全局实例，避免重复初始化
        _lazy_init_services()  # 确保服务已初始化
        s.naga = n  # 使用全局实例
    
    async def respond_stream(s, txt):
        async for resp in s.naga.process(txt):
            yield AI_NAME, resp, None, True, False

# 主程序入口
if __name__ == "__main__":
    import argparse

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="NagaAgent - 智能对话助手")
    parser.add_argument("--check-env", action="store_true", help="运行系统环境检测")
    parser.add_argument("--quick-check", action="store_true", help="运行快速环境检测")
    parser.add_argument("--force-check", action="store_true", help="强制运行环境检测（忽略缓存）")
    parser.add_argument("--check-api", action="store_true", help="检测 config.json 中的 LLM API 是否可用")

    args = parser.parse_args()

    # 单独检测 LLM API 连通性与鉴权
    if args.check_api:
        import json as _json
        import urllib.request

        print("正在检测 LLM API ...")
        print(f"   base_url : {config.api.base_url}")
        print(f"   model    : {config.api.model}")
        print(f"   api_key  : {config.api.api_key[:7]}...{config.api.api_key[-4:]}"
              f" (len={len(config.api.api_key)})")

        payload = _json.dumps({
            "model": config.api.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 4,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            config.api.base_url.rstrip("/") + "/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {config.api.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
            print(f"   [OK] 调用成功，返回模型: {body.get('model')!r}")
            sys.exit(0)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = _json.loads(detail).get("error", {}).get("message", detail)
            except Exception:
                pass
            print(f"   [ERROR] HTTP {exc.code}: {detail}")
            if exc.code == 401:
                print("      -> API Key 无效或已过期，请到 https://platform.deepseek.com/api_keys 重新申请，")
                print("        并把新 key 填入 config.json 的 api.api_key。")
            elif exc.code == 402:
                print("      -> 账户余额不足，请充值。")
            sys.exit(1)
        except Exception as exc:
            print(f"   [ERROR] 无法连接: {type(exc).__name__}: {exc}")
            sys.exit(1)

    # 处理检测命令
    if args.check_env or args.quick_check:
        if args.quick_check:
            success = run_quick_check()
        else:
            success = run_system_check(force_check=args.force_check)
        sys.exit(0 if success else 1)

    # 系统环境检测
    print("[启动] 正在启动NagaAgent...")
    print("=" * 50)

    # 如果是打包环境，跳过所有环境检测
    if IS_PACKAGED:
        print("[包] 检测到打包环境，跳过系统环境检测...")
    else:
        # 执行系统检测（只在第一次启动时检测）
        if not run_system_check():
            print("\n[FAIL] 系统环境检测失败，程序无法启动")
            print("请根据上述建议修复问题后重新启动")
            i=input("是否无视检测结果继续启动？是则按y，否则按其他任意键退出...")
            if i != "y" and i != "Y":
                sys.exit(1)

    print("\n[完成] 系统环境检测通过，正在启动应用...")
    print("=" * 50)
    
    if not asyncio.get_event_loop().is_running():
        asyncio.set_event_loop(asyncio.new_event_loop())
    
    # 快速启动UI，后台服务延迟初始化
    # QtWebEngine（应用内心智云图 / Markdown-LaTeX 渲染）与 Live2D 的 OpenGL 控件
    # 共存时，必须在创建 QApplication 之前开启共享 OpenGL 上下文，否则两者可能
    # 互相干扰（白屏或上下文创建失败）。该属性必须在 QApplication 之前设置才生效。
    try:
        from PyQt5.QtCore import Qt as _Qt
        QApplication.setAttribute(_Qt.AA_ShareOpenGLContexts, True)
    except Exception as _exc:
        print(f"   [警告] 设置共享 OpenGL 上下文失败（不影响启动）: {_exc}")

    app = QApplication(sys.argv)

    # 注册随包字体（Montserrat / JetBrains Mono）。必须在 QApplication 之后、
    # 任何窗口创建之前 —— 否则控件会用回退字体算好尺寸，换字体后布局不会重算。
    try:
        from ui.fonts import register_bundled_fonts

        register_bundled_fonts()
    except Exception as exc:
        print(f"   [警告] 字体注册失败（将使用系统默认字体）: {exc}")

    # 任务栏图标与系统托盘保持一致（同一个源文件），
    # 否则任务栏会显示 Python 默认图标，和托盘对不上。
    _ui_dir = os.path.join(os.path.dirname(__file__), "ui")
    icon_path = os.path.join(_ui_dir, "img", "window_icon.png")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(_ui_dir, "img", "standby.png")
    _app_icon = QIcon(icon_path)
    app.setWindowIcon(_app_icon)

    # Windows 需要显式 AppUserModelID，任务栏才会用我们设的图标，
    # 否则按 python.exe 归组、显示 Python 图标。
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NagaAgent.Desktop.4")
        except Exception as _icon_exc:
            print(f"   [提示] 设置 AppUserModelID 失败: {_icon_exc}")
    
    # 集成控制台托盘功能
    console_tray = integrate_console_tray()
    
    # 立即显示UI，提升用户体验
    win = ChatWindow()
    win.setWindowTitle("NagaAgent")
    win.show()
    
    # 在UI显示后异步初始化后台服务
    def init_services_async():
        """异步初始化后台服务"""
        try:
            _lazy_init_services()
        except Exception as e:
            print(f"[WARN] 后台服务初始化异常: {e}")
    
    # 使用定时器延迟初始化，避免阻塞UI
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(100, init_services_async)  # 100ms后初始化
    
    sys.exit(app.exec_())
