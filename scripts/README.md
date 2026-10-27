# scripts — 构建与启动脚本

所有脚本都可以**从任意工作目录**执行：每个脚本会自行定位到仓库根目录
（脚本位于 `<repo>/scripts/`，根目录是其上一级）

## 启动

| 脚本 | 平台 | 说明 |
|---|---|---|
| `start.bat` | Windows | 检查 `.venv` 后以 `.venv\Scripts\python.exe main.py` 启动，透传所有参数 |
| `start.sh` | Linux / macOS | 同上，使用 `.venv/bin/python` |

```bat
scripts\start.bat
scripts\start.bat --quick-check
```

```bash
./scripts/start.sh
./scripts/start.sh --check-env --force-check
```

## 环境初始化

| 脚本 | 说明 |
|---|---|
| `setup.py` | 检测 Python 版本、创建 `.venv`、安装依赖、生成 `config.json` |
| `setup.bat` / `setup.sh` | 上述脚本的平台包装 |

```bat
scripts\setup.bat
```

```bash
./scripts/setup.sh
```

## 打包

```bash
python scripts/build.py
```

`build.py` 流程：

1. 提示确认 `config.json` 中无隐私数据
2. 检查 `uv` 是否可用
3. 确保 `config.json` 存在（否则从 `config.json.example` 复制）
4. `uv sync --group build` 安装构建依赖
5. `uv run pyinstaller main.spec --clean --noconfirm`
6. 生成使用说明并归档到 `dist/`

> `build.py` 内部会 `os.chdir()` 到仓库根目录，因为 `main.spec`、`dist/`、`config.json`
> 都相对根目录，因此它可以放在 `scripts/` 下而无需任何相对路径参数

## 维护工具

日常维护用的脚本，默认都是「先预演、确认后再写盘」

| 脚本 | 说明 |
|---|---|
| `gen_requirements.py` | 从 `pyproject.toml` 的 `[project].dependencies` 重新生成 `requirements.txt`，保证两者一致 |
| `curate_memory.py` | 清理知识图谱存量数据：经「规则审查 + LLM 自审」两级过滤后重建图谱，并自动备份原文件 |
| `gen_ui_icons.py` | 生成 QSS 用的小图标（如下拉框的白色箭头） |

```bash
# 重新生成 requirements.txt（需先确认 pyproject.toml 是权威来源）
python scripts/gen_requirements.py --apply

# 清理知识图谱：默认只预演，加 --apply 才真正写入
python scripts/curate_memory.py                     # 预演，打印将被保留/剔除的条目
python scripts/curate_memory.py --apply             # 实际写入（自动备份到 data/logs/knowledge_graph/）
python scripts/curate_memory.py --apply --no-llm    # 跳过 LLM 自审，只用规则审查

# 重新生成 UI 图标（改了配色或尺寸时）
python scripts/gen_ui_icons.py
```

> `curate_memory.py` 会先写一份 `quintuples.<时间戳>.bak.json` 再改写原文件，
> 出问题可以直接用备份还原
>
> UI 图标由 `gen_ui_icons.py` 生成，修改配色或尺寸后重新运行即可

## 发布包中的配置

`main.spec` **只打包 `config.json.example`，不打包 `config.json`** ——
避免把你的 API key / Neo4j 密码随发布包分发出去，首次运行时按提示从模板生成

模板中的凭据字段（`api.api_key`、`grag.neo4j_password` 等）均为占位符，
其余配置为可用默认值
