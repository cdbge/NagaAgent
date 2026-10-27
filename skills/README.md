# skills — 技能目录

这里的每个子目录就是一个**技能**，由 `SKILL.md` 声明。技能的元数据会自动注入到
每次对话的系统提示词里，模型因此知道自己具备哪些能力；技能正文按需加载。

框架实现：`core/system/skill_manager.py`（来自 Naga 5.0，已适配本仓库分层结构）

## 添加一个技能（三步）

1. 新建目录：`skills/<你的技能名>/`
2. 写 `SKILL.md`，开头是 YAML 前置元数据，`---` 之后是正文指令：

```markdown
---
name: my-skill
description: 一句话说明这个技能做什么、什么时候用。这句话会出现在系统提示词里。
version: 1.0.0
author: 你
tags:
  - 自定义
enabled: true
---

# 我的技能

这里写给模型看的**具体操作指令**：步骤、格式要求、注意事项。

## 示例

用户问什么时，你应该怎么做。
```

3. 重启应用即可 —— 启动时会扫描 `skills/`，无需改任何代码。

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 技能标识，建议与目录名一致 |
| `description` | 是 | **最关键**：模型靠它判断何时该用这个技能。要写清"做什么 + 何时用" |
| `version` | 否 | 版本号 |
| `author` | 否 | 作者 |
| `tags` | 否 | 标签列表 |
| `enabled` | 否 | 设为 `false` 可临时停用该技能 |

## 当前内置技能

| 技能 | 用途 |
|---|---|
| `code-review` | 代码审查与质量分析 |
| `document-writer` | 技术文档 / README / API 文档撰写 |
| `file-manager` | 文件与目录整理、批量处理 |
| `summarize` | 长文本精炼总结 |
| `translate` | 中英互译 |
| `solve` | 分步骤问题解决 |
| `system-info` | 电脑硬件 / 系统状态 / 进程查询 |
| `verify-authenticity` | 信息真实性判断（识别虚假、AI 生成内容） |
| `web-search` | 联网搜索与实时信息检索 |

> 已刻意剔除 Naga 5.0 里与商业服务/外部平台绑定的技能
> （`naga_control`、`naga-config`、`openclaw-control`、`travel-explore`），
> 以及 `live2d-control`（本仓库用 `ui/live2d/emotion_binding.py` 原生实现情绪→表情，避免两套机制冲突）。

## 分层加载（为什么这样设计）

| 层级 | 内容 | 何时加载 |
|---|---|---|
| Level 1 | YAML 元数据（name/description/tags） | **每次对话**都注入系统提示词，轻量 |
| Level 2 | `SKILL.md` 正文指令 | 需要时按需读取，避免占满上下文 |
| Level 3 | 技能目录下的其它资源文件 | 需要时按需读取 |

因此技能可以写得很详细，而不会一上来就吃掉大量上下文。

## 目录示例

```
skills/
├── code-review/
│   └── SKILL.md
├── translate/
│   └── SKILL.md
└── my-skill/            ← 你的技能
    ├── SKILL.md
    └── templates/       ← 可选：Level 3 资源
        └── report.md
```
