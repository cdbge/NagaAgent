# data — 运行时数据

本目录存放程序运行期产生的数据，**不需要手动维护**，Git 只跟踪目录骨架与说明文件
实际内容（日志、导出、临时音频）均被 `.gitignore` 忽略

## 目录

```
data/
└── logs/
    ├── *.log                 每日运行日志（如 2026-02-10.log）
    ├── audio_temp/           TTS / 语音临时音频
    ├── knowledge_graph/      GRAG 导出：quintuples.json、graph.html
    ├── prompts/              提示词留存（system.save_prompts 开启时）
    ├── learning_patterns/    学习模式缓存
    ├── query_context/        查询上下文缓存
    ├── user_model/           用户模型数据
    └── full_flow_test/       全流程测试产物
```

## 路径来源

日志根目录由配置系统给出，不在代码里硬编码：

```python
from core.system.config import config
config.system.log_dir      # -> <repo>/data/logs
```

知识图谱与音频临时文件的写入点见：

- `core/summer_memory/quintuple_graph.py`（`data/logs/knowledge_graph/quintuples.json`）
- `core/summer_memory/quintuple_visualize_v2.py`（导出 `graph.html`）
- `core/voice/output/voice_integration.py`（`data/logs/audio_temp`）

## 清理

本目录内容可安全删除，程序会在下次启动时按需重建：

```bash
# 仅清日志
Remove-Item data/logs/*.log

# 清空全部运行时数据（保留目录骨架）
Get-ChildItem data/logs -Exclude README.md,__init__.py,.gitkeep | Remove-Item -Recurse -Force
```

> 运行时数据统一放在 `data/` 下，不在仓库根目录另建日志目录
> 历史日志已一并迁移
