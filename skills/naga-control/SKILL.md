---
name: naga-control
description: Naga 自身控制技能。用于查看/修改系统配置、切换模型、运行时开关语音与 Live2D、管理会话与技能。当用户要求修改设置、切换模型、关闭语音或查看自身状态时使用。
version: 1.0.0
author: Naga Team
tags:
  - control
  - config
  - model
  - voice
  - live2d
  - self-management
enabled: true
---

# Naga 自身控制技能

通过 `naga_control__*` 系列工具直接操作 Naga 自身，不需要用户去设置页手动点。

## 可用工具

| 工具 | 用途 | 参数 |
|------|------|------|
| `naga_control__get_config` | 读取配置 | `section?`（节名，如 `api`、`system`、`tts`、`live2d`） |
| `naga_control__update_config` | 修改配置并持久化 | `config`（嵌套对象） |
| `naga_control__get_status` | 运行状态：模型、语音/Live2D 开关、服务端口 | 无 |
| `naga_control__toggle_voice` | 运行时暂停/恢复语音 | `enabled`（bool） |
| `naga_control__toggle_live2d` | 运行时显示/隐藏形象 | `enabled`（bool） |
| `naga_control__set_emotion` | 设置形象表情 | `emotion`、`intensity?` |
| `naga_control__set_model` | 切换对话模型 | `model` |
| `naga_control__list_sessions` | 列出最近会话 | `limit?` |
| `naga_control__clear_session` | 清空指定会话 | `session_id` |
| `naga_control__list_skills` | 列出已安装技能 | 无 |

## 使用规则

- **改配置前先读**：不确定当前值时，先 `get_config` 再 `update_config`
- **凭据不可改**：`api_key`、密码、token 类字段会被拒绝，不要尝试
- **区分"运行时"和"持久化"**：
  - 用户说"暂时别说话" → `toggle_voice`（不写配置）
  - 用户说"以后都别说话" → `update_config` 改 `system.voice_enabled`
- **清空会话不可恢复**，执行前应向用户确认

## 白名单外的配置

只有这些路径允许由模型修改：

```
api.model / api.temperature / api.max_tokens / api.thinking_enabled
api.reasoning_effort / api.function_calling_enabled
system.voice_enabled / system.log_level
ui.font_size / ui.font_name / ui.user_name
live2d.enabled / live2d.model_path / live2d.auto_emotion / live2d.lip_sync_enabled
tts.default_voice / tts.default_speed
voice_realtime.voice_mode
grag.enabled / grag.graph_backend
```
