#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统环境检测模块
检测Python版本、虚拟环境、依赖包等系统环境
更新时间: 2025-10-04
"""

import sys
import subprocess
import importlib
import platform
import socket
import psutil
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# 允许直接运行本文件（`python core/system/system_checker.py ...`）：
# 它以脚本方式启动时 __package__ 为空，相对导入会失败，因此先把仓库根
# 加入 sys.path，再用绝对路径导入同级模块。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.system.json_config import dump_config_json, load_config_json

class SystemChecker:
    """系统环境检测器"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent  # 指向项目根目录
        # 虚拟环境目录：项目约定是 `.venv`（scripts/setup.py 创建的就是它），
        # 同时兼容手工创建的 `venv/`。
        _dot_venv = self.project_root / ".venv"
        _plain_venv = self.project_root / "venv"
        self.venv_path = (_dot_venv if _dot_venv.exists() or not _plain_venv.exists()
                          else _plain_venv)
        self.requirements_file = self.project_root / "requirements.txt"
        self.config_file = self.project_root / "config.json"
        self.pyproject_file = self.project_root / "pyproject.toml"
        self.results = {}

        # 需要检测的端口 - 从config读取
        from core.system.config import get_all_server_ports
        all_ports = get_all_server_ports()
        self.required_ports = [
            all_ports["api_server"],
            all_ports["agent_server"], 
            all_ports["mcp_server"],
            all_ports["tts_server"]
        ]
        
        # 镜像源配置
        self.pip_mirrors = [
            "https://pypi.tuna.tsinghua.edu.cn/simple/",
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.douban.com/simple/",
            "https://pypi.org/simple/"
        ]

        # 核心依赖包（已展开：原先集中在外部 nagaagent-core 垫片包中）
        # 只保留源码实际 import 的包：
        #   - torch / pandas / matplotlib 全仓库 0 处导入，原先只是垫片的传递依赖
        #   - openai_agents 为可选浏览器 Agent SDK，且与 langchain-openai 的 openai 版本互斥
        self.core_dependencies = [
            "fastapi",
            "openai",
            "html2text",
            "requests",
            "PyQt5",
            "numpy",
            "markdown",
            "charset_normalizer",
            "pydantic",
            "aiohttp",
            "mcp",
        ]

        # 重要可选依赖
        # 注：onnxruntime 已从依赖中移除 —— 没有代码导入它（VAD 是能量检测），
        # 且与 PyQt5 存在 DLL 冲突。详见 pyproject.toml 语音段的说明。
        self.optional_dependencies = [
            ("sounddevice", "音频设备"),
            ("pyaudio", "音频录制"),
            ("edge_tts", "TTS语音合成"),
            ("playwright", "浏览器自动化"),
            ("crawl4ai", "网页爬取"),
            ("pyautogui", "屏幕控制"),
            ("opencv_python", "计算机视觉"),
            ("librosa", "音频分析"),
            ("torch", "深度学习框架"),
            ("pystray", "系统托盘"),
            ("live2d", "Live2D虚拟形象"),
            #("paho_mqtt", "MQTT通信"),
            ("jmcomic", "漫画下载"),
            ("bilibili_api", "B站视频"),
            ("python_docx", "Word文档处理")
        ]
        
    def check_all(self, auto_setup: bool = False) -> Dict[str, bool]:
        """执行所有检测项目"""
        print("[搜索] 开始系统环境检测...")
        print("=" * 50)
        
        # 检查是否首次运行且需要自动配置
        if auto_setup and not self.venv_path.exists():
            print("[目标] 检测到首次运行，开始自动环境配置...")
            if self.auto_setup_environment():
                print("[OK] 自动环境配置完成！")
            else:
                print("[FAIL] 自动环境配置失败，请手动配置")
                return {"自动配置": False}
        
        checks = [
            ("Python版本", self.check_python_version),
            ("虚拟环境", self.check_virtual_environment),
            ("依赖文件", self.check_requirements_file),
            ("核心依赖", self.check_core_dependencies),
            ("可选依赖", self.check_optional_dependencies),
            ("配置文件", self.check_config_files),
            ("目录结构", self.check_directory_structure),
            ("权限检查", self.check_permissions),
            ("端口可用性", self.check_port_availability),
            ("系统资源", self.check_system_resources),
            ("图存储后端", self.check_neo4j_connection),
            #("环境变量", self.check_environment_variables)
        ]
        
        all_passed = True
        for name, check_func in checks:
            print(f" 检测 {name}...")
            try:
                result = check_func()
                self.results[name] = result
                if result:
                    print(f"[OK] {name}: 通过")
                else:
                    print(f"[FAIL] {name}: 失败")
                    all_passed = False
            except Exception as e:
                print(f"[WARN] {name}: 检测异常 - {e}")
                self.results[name] = False
                all_passed = False
            print()
        
        print("=" * 50)
        if all_passed:
            print("[完成] 系统环境检测全部通过！")
        else:
            print("[WARN] 系统环境检测发现问题，请查看上述信息")
        
        return self.results
    
    def check_python_version(self) -> bool:
        """检测Python版本"""
        version = sys.version_info
        print(f"   当前Python版本: {version.major}.{version.minor}.{version.micro}")

        # 要求Python 3.11+（根据requirements.txt推荐）
        if version.major < 3 or (version.major == 3 and version.minor < 11):
            print(f"   [WARN] Python版本建议3.11+，当前{version.major}.{version.minor}")
            print(f"   [TIP] 推荐升级到Python 3.11以获得最佳兼容性")
            return False

        print(f"   [OK] Python版本符合要求")
        return True
    
    def check_virtual_environment(self) -> bool:
        """检测虚拟环境"""
        # 检查是否在虚拟环境中
        in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        
        if not in_venv:
            print(f"   [WARN] 未检测到虚拟环境")
            
            # 检查是否存在venv目录
            if self.venv_path.exists():
                print(f"   [INFO] 发现venv目录: {self.venv_path}")
                print(f"   [TIP] 请运行: {self.venv_path.name}\\Scripts\\activate (Windows) 或 source {self.venv_path.name}/bin/activate (Linux/Mac)")
                return False
            else:
                print(f"   [TIP] 建议创建虚拟环境: python -m venv .venv")
                return False
        
        print(f"   [OK] 虚拟环境: {sys.prefix}")
        return True
    
    def check_requirements_file(self) -> bool:
        """检测依赖文件"""
        if not self.requirements_file.exists():
            print(f"   [ERROR] 未找到requirements.txt文件: {self.requirements_file}")
            return False

        print(f"   [OK] 依赖文件存在: {self.requirements_file}")

        # 检查pyproject.toml
        if self.pyproject_file.exists():
            print(f"   [OK] pyproject.toml存在: {self.pyproject_file}")
        else:
            print(f"   [WARN] pyproject.toml不存在（可选）")

        return True
    
    def check_core_dependencies(self) -> bool:
        """检测核心依赖包"""
        missing_deps = []

        for dep in self.core_dependencies:
            # 特殊处理某些包名
            module_name = dep
            if dep == "openai_agents":
                module_name = "agents"
            elif dep == "opencv_python":
                module_name = "cv2"
            elif dep == "pydantic":
                module_name = "pydantic"
            elif dep == "edge_tts":
                module_name = "edge_tts"

            try:
                importlib.import_module(module_name)
                print(f"   [OK] {dep}")
            except ImportError:
                print(f"   [ERROR] {dep}: 未安装")
                missing_deps.append(dep)

        if missing_deps:
            print(f"   [TIP] 请安装缺失的依赖: pip install {' '.join(missing_deps)}")
            print(f"   [TIP] 或使用完整安装命令: pip install -r requirements.txt")
            return False

        return True
    
    def check_optional_dependencies(self) -> bool:
        """检测可选依赖包"""
        missing_optional = []

        for dep, desc in self.optional_dependencies:
            # 特殊处理某些包名
            module_name = dep
            if dep == "opencv_python":
                module_name = "cv2"
            elif dep == "edge_tts":
                module_name = "edge_tts"
            elif dep == "live2d":
                module_name = "live2d"
            elif dep == "bilibili_api":
                module_name = "bilibili_api"
            elif dep == "python_docx":
                module_name = "docx"

            try:
                importlib.import_module(module_name)
                print(f"   [OK] {dep} ({desc})")
            except ImportError:
                print(f"   [WARN] {dep} ({desc}): 未安装")
                missing_optional.append((dep, desc))

        if missing_optional:
            print(f"   [TIP] 可选依赖缺失，某些功能可能不可用:")
            for dep, desc in missing_optional:
                print(f"      - {dep}: {desc}")

        return True  # 可选依赖不影响启动
    
    def check_config_files(self) -> bool:
        """检测配置文件"""
        config_files = [
            ("config.json", "主配置文件"),
            ("config.json.example", "配置示例文件")
        ]
        
        all_exist = True
        for file_name, desc in config_files:
            file_path = self.project_root / file_name
            if file_path.exists():
                print(f"   [OK] {file_name} ({desc})")
            else:
                print(f"   [ERROR] {file_name} ({desc}): 不存在")
                all_exist = False
        
        if not all_exist:
            print(f"   [TIP] 请确保配置文件存在")
        
        return all_exist
    
    def check_directory_structure(self) -> bool:
        """检测目录结构"""
        required_dirs = [
            ("ui", "用户界面"),
            ("apiserver", "API服务器"),
            ("agentserver", "Agent服务器"),
            ("mcpserver", "MCP服务器"),
            ("summer_memory", "记忆系统"),
            ("voice", "语音模块"),
            ("system", "系统核心")
        ]

        all_exist = True
        for dir_name, desc in required_dirs:
            dir_path = self.project_root / dir_name
            if dir_path.exists() and dir_path.is_dir():
                print(f"   [OK] {dir_name}/ ({desc})")
            else:
                print(f"   [FAIL] {dir_name}/ ({desc}): 不存在")
                all_exist = False

        return all_exist
    
    def check_permissions(self) -> bool:
        """检测文件权限"""
        try:
            # 检查项目根目录读写权限
            test_file = self.project_root / ".test_permission"
            test_file.write_text("test")
            test_file.unlink()
            
            # 检查logs目录权限
            logs_dir = self.project_root / "logs"
            if logs_dir.exists():
                test_log = logs_dir / ".test_permission"
                test_log.write_text("test")
                test_log.unlink()
            
            print(f"   [OK] 文件权限正常")
            return True
            
        except Exception as e:
            print(f"   [FAIL] 文件权限异常: {e}")
            return False

    def check_port_availability(self) -> bool:
        """检测端口可用性"""
        print(f"   检测端口: {', '.join(map(str, self.required_ports))}")

        all_available = True
        for port in self.required_ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()

            if result == 0:
                print(f"   [WARN] 端口 {port}: 已被占用")
                all_available = False
            else:
                print(f"   [OK] 端口 {port}: 可用")

        return all_available

    def check_system_resources(self) -> bool:
        """检测系统资源"""
        try:
            # CPU信息
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)
            print(f"   CPU核心数: {cpu_count}")
            print(f"   CPU使用率: {cpu_percent:.1f}%")

            # 内存信息
            memory = psutil.virtual_memory()
            total_gb = memory.total / (1024**3)
            available_gb = memory.available / (1024**3)
            used_percent = memory.percent
            print(f"   总内存: {total_gb:.1f} GB")
            print(f"   可用内存: {available_gb:.1f} GB")
            print(f"   内存使用率: {used_percent:.1f}%")

            # 磁盘空间
            disk = psutil.disk_usage(str(self.project_root))
            total_disk = disk.total / (1024**3)
            free_disk = disk.free / (1024**3)
            print(f"   磁盘空间: {free_disk:.1f} GB 可用 / {total_disk:.1f} GB 总计")

            # 资源检查
            if total_gb < 4:
                print(f"   [WARN] 内存不足4GB，可能影响性能")
                return False

            if free_disk < 1:
                print(f"   [WARN] 磁盘空间不足1GB")
                return False

            print(f"   [OK] 系统资源充足")
            return True

        except Exception as e:
            print(f"   [FAIL] 检测系统资源失败: {e}")
            return False

    def check_neo4j_connection(self) -> bool:
        """检测图存储后端（可插拔：kuzu / neo4j / sqlite）。

        历史实现只看「neo4j 包是否安装」就报成功，与实际使用的后端无关，
        容易给出误导性结论（例如实际用 Kuzu 却显示"Neo4j连接: 成功"）。
        这里改为检查**真实生效的后端**是否就绪。
        """
        try:
            from core.summer_memory.quintuple_graph import get_backend_info

            info = get_backend_info()
            backend = info.get("backend")
            available = bool(info.get("available"))
            counts = info.get("counts") or {}

            if backend is None:
                print("   [WARN] 图存储后端不可用，记忆将退化为本地文件快照")
                print("      (data/logs/knowledge_graph/quintuples.json)")
                return True  # 不影响启动，仅降级

            print(f"   后端: {backend}")
            print(f"   状态: {'就绪' if available else '不可用'}")
            if counts:
                print(f"   知识图谱: {counts.get('entities', 0)} 实体 / {counts.get('relations', 0)} 关系")

            if backend == "neo4j" and not available:
                print("   [WARN] Neo4j 未连接；如需无服务方案可把 grag.graph_backend 改为 kuzu")
            return True

        except Exception as e:
            print(f"   [WARN] 图存储后端检测异常: {e}")
            return True

    '''
    def check_environment_variables(self) -> bool:
        """检测环境变量"""
        important_env_vars = [
            ('PATH', '系统路径'),
            ('PYTHONPATH', 'Python路径（可选）'),
            ('OPENAI_API_KEY', 'OpenAI API密钥（可选）'),
            ('DEEPSEEK_API_KEY', 'DeepSeek API密钥（可选）'),
            ('DASHSCOPE_API_KEY', '阿里云DashScope API密钥（可选）')
        ]

        all_good = True
        for var_name, desc in important_env_vars:
            value = os.getenv(var_name)
            if value:
                # 隐藏敏感信息
                if 'API_KEY' in var_name:
                    display_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "已设置"
                else:
                    display_value = value[:50] + "..." if len(value) > 50 else value
                print(f"   [OK] {var_name}: {display_value}")
            else:
                if '可选' in desc:
                    print(f"   [WARN] {var_name}: 未设置（{desc}）")
                else:
                    print(f"   [FAIL] {var_name}: 未设置（{desc}）")
                    all_good = False

        return all_good
   '''

    def find_python311(self) -> Optional[str]:
        """查找Python 3.11解释器"""
        python_commands = [
            "python3.11",
            "py -3.11",
            "python311",
            "python3.11.exe",
            "python311.exe"
        ]
        
        for cmd in python_commands:
            try:
                result = subprocess.run([cmd, "--version"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and "3.11" in result.stdout:
                    print(f"   [OK] 找到Python 3.11: {cmd}")
                    return cmd
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
        
        return None

    '''
    def download_python311(self) -> Optional[str]:
        """下载Python 3.11（Windows）"""
        if platform.system() != "Windows":
            print("   [WARN] 自动下载Python仅支持Windows系统")
            return None
        
        print("    开始下载Python 3.11...")
        try:
            # Python 3.11.9 下载链接
            python_url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
            temp_dir = tempfile.mkdtemp()
            installer_path = os.path.join(temp_dir, "python-3.11.9-amd64.exe")
            
            print(f"    下载中: {python_url}")
            urllib.request.urlretrieve(python_url, installer_path)
            
            print("   [TOOL] 安装Python 3.11...")
            # 静默安装Python 3.11
            install_cmd = [
                installer_path,
                "/quiet",
                "InstallAllUsers=1",
                "PrependPath=1",
                "Include_test=0"
            ]
            
            result = subprocess.run(install_cmd, timeout=300)
            if result.returncode == 0:
                print("   [OK] Python 3.11安装成功")
                # 清理临时文件
                os.remove(installer_path)
                os.rmdir(temp_dir)
                return "python3.11"
            else:
                print("   [FAIL] Python 3.11安装失败")
                return None
                
        except Exception as e:
            print(f"   [FAIL] 下载Python 3.11失败: {e}")
            return None
    '''
            
    def create_virtual_environment(self) -> bool:
        """创建虚拟环境"""
        try:
            print("   [TOOL] 创建虚拟环境...")
            
            # 查找Python 3.11
            python_cmd = self.find_python311()
            if not python_cmd:
                print("    未找到Python 3.11")
                #python_cmd = self.download_python311()
                return False
            
            # 创建虚拟环境
            venv_cmd = [python_cmd, "-m", "venv", str(self.venv_path)]
            result = subprocess.run(venv_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"   [OK] 虚拟环境创建成功: {self.venv_path}")
                return True
            else:
                print(f"   [FAIL] 虚拟环境创建失败: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"   [FAIL] 创建虚拟环境异常: {e}")
            return False
    
    def install_project_dependencies(self) -> bool:
        """安装本项目依赖（来源为仓库根目录的 requirements.txt）

        历史实现会去 PyPI 安装外部包 nagaagent-core，该包只是一个把第三方库
        重新导出的垫片。依赖现已全部在 requirements.txt / pyproject.toml 中直接声明。
        """
        requirements = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
        if not requirements.exists():
            print(f"   [FAIL] 未找到依赖清单: {requirements}")
            return False

        try:
            print(f"   [包] 安装项目依赖: {requirements}")

            # 确定pip命令
            if platform.system() == "Windows":
                pip_cmd = str(self.venv_path / "Scripts" / "pip.exe")
            else:
                pip_cmd = str(self.venv_path / "bin" / "pip")

            base_cmd = [pip_cmd, "install", "--upgrade", "-r", str(requirements)]

            # 尝试使用镜像源安装
            for mirror in self.pip_mirrors:
                try:
                    print(f"   [刷新] 尝试镜像源: {mirror}")
                    result = subprocess.run(
                        base_cmd + ["--index-url", mirror],
                        capture_output=True, text=True, timeout=900
                    )

                    if result.returncode == 0:
                        print(f"   [OK] 依赖安装成功 (使用镜像: {mirror})")
                        return True
                    else:
                        print(f"   [WARN] 镜像源失败: {result.stderr[:100]}...")
                        continue

                except subprocess.TimeoutExpired:
                    print(f"   [WARN] 镜像源超时: {mirror}")
                    continue
                except Exception as e:
                    print(f"   [WARN] 镜像源异常: {e}")
                    continue

            # 如果所有镜像源都失败，尝试默认源
            print("   [刷新] 尝试默认源...")
            result = subprocess.run(base_cmd, capture_output=True, text=True, timeout=900)

            if result.returncode == 0:
                print("   [OK] 依赖安装成功 (使用默认源)")
                return True
            else:
                print(f"   [FAIL] 依赖安装失败: {result.stderr}")
                return False

        except Exception as e:
            print(f"   [FAIL] 安装项目依赖异常: {e}")
            return False
    
    def auto_setup_environment(self) -> bool:
        """自动配置环境（首次运行）"""
        print("[启动] 开始自动环境配置...")
        print("=" * 50)
        
        # 检查是否已经存在虚拟环境
        if self.venv_path.exists():
            print("   [OK] 虚拟环境已存在，跳过创建")
            return True
        
        # 创建虚拟环境
        if not self.create_virtual_environment():
            return False
        
        # 安装项目依赖
        if not self.install_project_dependencies():
            return False
        
        print("   [OK] 自动环境配置完成！")
        print("   [提示] 请运行以下命令激活虚拟环境:")
        if platform.system() == "Windows":
            print(f"      {self.venv_path.name}\\Scripts\\activate")
        else:
            print(f"      source {self.venv_path.name}/bin/activate")
        
        return True
    
    def get_system_info(self) -> Dict[str, str]:
        """获取系统信息"""
        info = {
            "操作系统": platform.system(),
            "系统版本": platform.version(),
            "架构": platform.machine(),
            "Python版本": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Python路径": sys.executable,
            "项目路径": str(self.project_root),
            "虚拟环境": "是" if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else "否"
        }

        # 添加系统资源信息
        try:
            memory = psutil.virtual_memory()
            info["总内存"] = f"{memory.total / (1024**3):.1f} GB"
            info["CPU核心数"] = str(psutil.cpu_count())
        except:
            pass

        return info
    
    def print_system_info(self):
        """打印系统信息"""
        print("️ 系统信息:")
        print("-" * 30)
        info = self.get_system_info()
        for key, value in info.items():
            print(f"   {key}: {value}")
        print()
    
    def suggest_fixes(self):
        """建议修复方案"""
        print("[TOOL] 修复建议:")
        print("-" * 30)

        if not self.results.get("Python版本", True):
            print("1. 升级Python版本:")
            print("   推荐使用Python 3.11或更高版本")
            print("   下载地址: https://www.python.org/downloads/")
            print()

        if not self.results.get("虚拟环境", True):
            print("2. 创建并激活虚拟环境:")
            print("   # 使用Python 3.11创建虚拟环境:")
            print("   py -3.11 -m venv .venv  # Windows")
            print("   python3.11 -m venv .venv  # Linux/Mac")
            print("   # 激活虚拟环境:")
            print(f"   {self.venv_path.name}\\Scripts\\activate  # Windows")
            print(f"   source {self.venv_path.name}/bin/activate  # Linux/Mac")
            print("   # 安装依赖:")
            print(f"   {self.venv_path.name}\\Scripts\\pip install -r requirements.txt  # Windows")
            print(f"   {self.venv_path.name}/bin/pip install -r requirements.txt  # Linux/Mac")
            print("   # 或用 uv（推荐，见 README）:")
            print("   uv sync")
            print()

        if not self.results.get("核心依赖", True):
            print("3. 安装核心依赖:")
            print("   # 推荐使用 uv（会按 pyproject.toml / uv.lock 安装）:")
            print("   uv sync")
            print("   # 或用 pip（国内可加镜像源）:")
            print("   pip install -r requirements.txt")
            print("   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt")
            print()

        if not self.results.get("配置文件", True):
            print("4. 复制配置文件:")
            print("   copy config.json.example config.json  # Windows")
            print("   cp config.json.example config.json  # Linux/Mac")
            print("   # 编辑config.json并填入API密钥")
            print()

        if not self.results.get("端口可用性", True):
            print("5. 解决端口冲突:")
            print("   # 查找占用端口的进程")
            from core.system.config import get_server_port
            api_port = get_server_port("api_server")
            print(f"   netstat -ano | findstr :{api_port}  # Windows")
            print(f"   lsof -i :{api_port}  # Linux/Mac")
            print("   # 或修改config.json中的端口配置")
            print()

        if not self.results.get("系统资源", True):
            print("6. 系统资源不足:")
            print("   - 建议至少4GB内存")
            print("   - 建议至少1GB可用磁盘空间")
            print("   - 关闭不必要的应用程序")
            print()

        if not self.results.get("图存储后端", True):
            print("7. 配置Neo4j数据库:")
            print("   # 使用Docker启动Neo4j:")
            print("   docker run -d --name naga-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest")
            print("   # 或安装Neo4j Desktop")
            print()

        if not self.results.get("目录结构", True):
            print("8. 检查项目完整性:")
            print("   确保所有必要的目录和文件都存在")
            print("   重新克隆项目可能解决问题")
            print()

    def is_check_passed(self) -> bool:
        """检查是否已经通过过系统检测"""
        if not self.config_file.exists():
            return False

        try:
            config_data = load_config_json(self.config_file)
            system_check = config_data.get('system_check', {})
            return system_check.get('passed', False)
        except Exception:
            return False

    def save_check_status(self, passed: bool):
        """保存检测状态到config.json"""
        try:
            # 读取现有配置（保留其它字段），再写回 system_check
            if self.config_file.exists():
                config_data = load_config_json(self.config_file)
            else:
                config_data = {}

            config_data['system_check'] = {
                'passed': passed,
                'timestamp': datetime.now().isoformat(),
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                'project_path': str(self.project_root),
                'system': platform.system()
            }

            dump_config_json(self.config_file, config_data)
        except Exception as e:
            print(f"[WARN] 保存检测状态失败: {e}")

    def should_skip_check(self) -> bool:
        """判断是否应该跳过检测"""
        return self.is_check_passed()

    def reset_check_status(self):
        """重置检测状态，强制下次启动时重新检测"""
        try:
            if not self.config_file.exists():
                print("[WARN] 配置文件不存在")
                return

            config_data = load_config_json(self.config_file)
            config_data.pop('system_check', None)
            dump_config_json(self.config_file, config_data)
            print("[OK] 检测状态已重置，下次启动时将重新检测")
        except Exception as e:
            print(f"[WARN] 重置检测状态失败: {e}")

def run_system_check(force_check: bool = False, auto_setup: bool = False) -> bool:
    """运行系统检测"""
    checker = SystemChecker()
    
    # 检查是否已经通过过检测（除非强制检测）
    if not force_check and checker.should_skip_check():
        print("[OK] 系统环境检测已通过，跳过检测")
        return True
    
    # 打印系统信息
    checker.print_system_info()
    
    # 执行检测（支持自动配置）
    results = checker.check_all(auto_setup=auto_setup)
    
    # 保存检测结果
    all_passed = all(results.values())
    checker.save_check_status(all_passed)
    
    # 如果有问题，提供修复建议
    if not all_passed:
        checker.suggest_fixes()
        return False
    
    return True

def reset_system_check():
    """重置系统检测状态"""
    checker = SystemChecker()
    checker.reset_check_status()

def run_quick_check() -> bool:
    """运行快速检测（仅检测核心项）"""
    checker = SystemChecker()

    print("快速系统检测...")
    print("=" * 50)

    # 仅检测关键项
    quick_checks = [
        ("Python版本", checker.check_python_version),
        ("核心依赖", checker.check_core_dependencies),
        ("配置文件", checker.check_config_files)
    ]

    all_passed = True
    for name, check_func in quick_checks:
        print(f"[CHECK] 检测 {name}...")
        try:
            result = check_func()
            if result:
                print(f"[OK] {name}: 通过")
            else:
                print(f"[FAIL] {name}: 失败")
                all_passed = False
        except Exception as e:
            print(f"[ERROR] {name}: 检测异常 - {e}")
            all_passed = False
        print()

    if all_passed:
        print("[SUCCESS] 快速检测通过！")
    else:
        print("[WARN] 快速检测发现问题，建议运行完整检测: python system/system_checker.py --force")

    return all_passed

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NagaAgent 系统环境检测工具")
    parser.add_argument("--quick", action="store_true", help="快速检测（仅检测核心项）")
    parser.add_argument("--force", action="store_true", help="强制检测（忽略缓存）")
    parser.add_argument("--auto-setup", action="store_true", help="首次运行自动配置环境")

    args = parser.parse_args()

    if args.quick:
        success = run_quick_check()
    else:
        success = run_system_check(force_check=args.force, auto_setup=args.auto_setup)

    sys.exit(0 if success else 1)
