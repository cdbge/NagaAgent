---
name: live2d-control
description: 虚拟形象表情控制技能。当你判断回复内容带有明显情绪时，调用 set_emotion 让形象做出对应表情，增强表达效果。中性陈述无需调用。
version: 1.0.0
author: Naga Team
tags:
  - live2d
  - emotion
  - expression
enabled: true
---

# 虚拟形象表情控制

调用 `naga_control__set_emotion` 设置形象表情。

## 可选情绪

| 情绪 | 说明 | 触发场景 |
|------|------|----------|
| `happy` | 喜悦 | 肯定、同意、确认（"好的"、"没问题"、"可以"） |
| `enjoy` | 享受 | 愉快、赞叹（"很棒"、"有趣"、"太好了"） |
| `sad` | 悲伤 | 否定、拒绝、做不到（"不行"、"抱歉"） |
| `surprise` | 惊讶 | 意外、出乎意料（"没想到"、"竟然"） |
| `angry` | 生气 | 不满、被冒犯 |
| `shy` | 害羞 | 被夸奖、不好意思 |
| `normal` | 中性 | 普通陈述、说明事实 |

## 触发规则

- **有明确情绪时才调用**：中性陈述、技术说明、代码输出都不用调
- **一句话最多调一次**：在开始回答时调用，不要在长回复里反复切换
- **强度**：默认 1.0；轻微情绪可取 0.4–0.6
- **失败不影响回答**：形象没加载时工具会返回失败，忽略即可

## 示例

用户："今天心情不错，陪我聊会天" → `set_emotion(emotion="happy", intensity=0.8)`

用户："这个 bug 到底是为什么" → `set_emotion(emotion="normal")`

用户："你居然猜对了！" → `set_emotion(emotion="surprise")`
