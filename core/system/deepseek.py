#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek 官方端点与模型名的唯一来源。

依据官方文档（https://api-docs.deepseek.com/ 与 /quick_start/pricing）：

===========================  ==========================================
base_url (OpenAI 兼容)        https://api.deepseek.com
base_url (Anthropic 兼容)     https://api.deepseek.com/anthropic
模型                          deepseek-flash / deepseek-v4-pro
===========================  ==========================================

要点：

* 官方给出的 OpenAI 兼容地址**不带** ``/v1`` 后缀
  （``/v1`` 只是历史兼容写法，官方文档已不再列出）。
* 旧模型名 ``deepseek-chat`` / ``deepseek-reasoner`` 已不在官方模型表中。
  官方当前模型为 ``deepseek-flash``（DeepSeek-V4.1-Flash，便宜、快、支持工具调用）
  与 ``deepseek-v4-pro``（DeepSeek-V4-Pro，能力更强、更贵）。
* 两个模型都支持 thinking 模式（默认开启）、JSON 输出、工具调用与 Responses API；
  仅 ``deepseek-flash`` 支持视觉输入。

用户可在 ``config.json`` 的 ``api.base_url`` / ``api.model`` 覆盖这里的默认值。
"""

# OpenAI 兼容端点（官方当前形式，无 /v1）
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Anthropic 兼容端点（供 Claude Code 等使用）
DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"

# 官方当前模型
DEEPSEEK_MODEL_FLASH = "deepseek-flash"      # DeepSeek-V4.1-Flash：默认，性价比高
DEEPSEEK_MODEL_PRO = "deepseek-v4-pro"       # DeepSeek-V4-Pro：能力更强

# 默认模型
DEEPSEEK_DEFAULT_MODEL = DEEPSEEK_MODEL_FLASH

# 历史模型名（官方模型表中已不再列出，保留仅用于识别旧配置并给出提示）
DEEPSEEK_LEGACY_MODELS = ("deepseek-chat", "deepseek-reasoner")

__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_ANTHROPIC_BASE_URL",
    "DEEPSEEK_MODEL_FLASH",
    "DEEPSEEK_MODEL_PRO",
    "DEEPSEEK_DEFAULT_MODEL",
    "DEEPSEEK_LEGACY_MODELS",
]
