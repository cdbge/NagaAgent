# NagaAgent 系统环境检测器

## 🎯 功能概述

启动自检工具，检查运行 NagaAgent 所需的环境，并在缺项时给出可操作的修复步骤：

- ✅ **环境检测**：Python 版本、虚拟环境、依赖包、配置、目录结构、权限、端口、系统资源
- ✅ **图存储后端检测**：报告实际生效的后端（kuzu / neo4j / sqlite）
- ✅ **修复建议**：针对未通过项逐条给出命令
- ✅ **首次自动配置**：`--auto-setup` 可在缺少虚拟环境时创建并安装依赖

## 🚀 使用方法

```bash
# 完整检测
python core/system/system_checker.py

# 快速检测（仅 Python 版本 / 核心依赖 / 配置文件）
python core/system/system_checker.py --quick

# 强制重新检测（忽略缓存结果）
python core/system/system_checker.py --force

# 首次运行：缺少虚拟环境时自动创建并安装依赖
python core/system/system_checker.py --auto-setup
```

应用启动时也会自动调用（可在 `main.py --check-env` 中查看结果）

### 在代码中使用

```python
from core.system.system_checker import SystemChecker, run_system_check

checker = SystemChecker()
results = checker.check_all()          # 返回 {检测项: 是否通过}

success = run_system_check(force_check=True, auto_setup=False)
```

## 📋 检测项目

`check_all()` 依次执行：

| 检测项 | 方法 |
|---|---|
| Python 版本 | `check_python_version` |
| 虚拟环境 | `check_virtual_environment` |
| `requirements.txt` | `check_requirements_file` |
| 核心依赖 | `check_core_dependencies` |
| 可选依赖 | `check_optional_dependencies` |
| 配置文件 | `check_config_files` |
| 目录结构 | `check_directory_structure` |
| 文件权限 | `check_permissions` |
| 端口可用性 | `check_port_availability` |
| 系统资源 | `check_system_resources` |
| 图存储后端 | `check_neo4j_connection`（报告实际后端，非仅 Neo4j） |
| 环境变量 | `check_environment_variables` |

检测结果缓存到 `config.json` 的 `system_check` 段；`--force` 可忽略缓存重跑

## 🔧 虚拟环境

项目约定使用 **`.venv`**（`scripts/setup.py` 创建的就是它），同时兼容手工创建的 `venv/`
两者都存在时优先 `.venv`

```bash
# 创建并激活（Windows）
py -3.11 -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3.11 -m venv .venv
source .venv/bin/activate

# 安装依赖
uv sync                      # 推荐，按 pyproject.toml / uv.lock
pip install -r requirements.txt
```

### 镜像源

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt
```

## 🛠️ 修复建议

检测器对未通过项会直接打印修复命令，涵盖：

- Python 版本过低 → 下载地址
- 缺少虚拟环境 → 创建与激活命令
- 核心依赖缺失 → `uv sync` / `pip install -r requirements.txt`
- 缺 `config.json` → 从 `config.json.example` 复制并填入 API key
- 端口被占用 → 按当前配置端口打印 `netstat` / `lsof` 命令

## 📁 相关文件

```
core/system/
├── system_checker.py    # 本检测器
├── config.py            # 配置模型与端口唯一来源
├── json_config.py       # 带注释 JSON 解析
├── deepseek.py          # DeepSeek 端点与模型名唯一来源
└── timeutil.py          # UTC 时间工具
```

项目根目录：`.venv/`、`requirements.txt`、`pyproject.toml`、`config.json`（由模板生成）

## 🐛 故障排除

1. **Python 3.11 未找到**
   自动安装仅支持 Windows；Linux / macOS 请手动安装 Python 3.11

2. **网络连接问题**
   安装依赖时会尝试镜像源；全部失败时才回落到官方源

3. **权限问题**
   确保对项目目录有读写权限；Windows 下可能需要在管理员终端运行 `--auto-setup`

4. **图存储后端不可用**
   Kuzu 是单写入者模型，同一数据库文件同一时刻只能被一个进程打开
   若提示数据库被占用，先确认没有第二个 NagaAgent 实例在运行；
   需要零依赖可把 `config.json` 的 `grag.graph_backend` 改为 `sqlite`
