#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""非标准 JSON 解析与意图分析。

原实现位于外部包 ``nagaagent_core.stable.parsing``。该包只是一个转发层，
此处将其真实逻辑（约 260 行）吸收进本仓库，以移除对 nagaagent_core 的依赖。

对外提供：
    parse_non_standard_json(text) -> List[Dict]
    validate_tool_call(tool_call) -> bool
    extract_json_blocks(text) -> List[str]
    normalize_json_format(text) -> str
    IntentAnalyzer
"""

import json
import re
from typing import Any, Dict, List

# 工具调用必须包含的字段
_REQUIRED_TOOL_CALL_FIELDS = ("agentType", "service_name", "tool_name")

# 标准 JSON 块（支持一层嵌套）
_STANDARD_JSON_PATTERN = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
# 中文全角括号包裹的块
_CJK_JSON_PATTERN = r"｛([^｝]*)｝"


def validate_tool_call(tool_call: Dict[str, Any]) -> bool:
    """校验工具调用是否包含必要字段。"""
    if not isinstance(tool_call, dict):
        return False
    return all(tool_call.get(field) for field in _REQUIRED_TOOL_CALL_FIELDS)


def _parse_standard_json_blocks(text: str) -> List[Dict[str, Any]]:
    """方法一：按标准 JSON 解析。"""
    tool_calls: List[Dict[str, Any]] = []
    for json_str in re.findall(_STANDARD_JSON_PATTERN, text, re.DOTALL):
        try:
            tool_call = json.loads(json_str)
        except json.JSONDecodeError:
            continue
        if validate_tool_call(tool_call):
            tool_calls.append(tool_call)
    return tool_calls


def _parse_cjk_bracket_blocks(text: str) -> List[Dict[str, Any]]:
    """方法二：解析中文全角括号 ｛｝ 包裹的非标准 JSON。"""
    tool_calls: List[Dict[str, Any]] = []

    for match in re.findall(_CJK_JSON_PATTERN, text, re.DOTALL):
        try:
            json_str = "{" + match + "}"
            tool_call: Dict[str, Any] = {}

            for line in json_str.split("\n"):
                line = line.strip()
                if ":" not in line or line.startswith("{") or line.startswith("}"):
                    continue

                if '"' in line:
                    # 带引号的键值对
                    key_match = re.search(r'"([^"]*)"\s*:\s*"([^"]*)"', line)
                    if key_match:
                        tool_call[key_match.group(1)] = key_match.group(2)
                else:
                    # 简单键值对
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        tool_call[parts[0].strip().strip('"')] = (
                            parts[1].strip().strip('"')
                        )

            if validate_tool_call(tool_call):
                tool_calls.append(tool_call)
        except Exception:
            continue

    return tool_calls


def parse_non_standard_json(text: str) -> List[Dict[str, Any]]:
    """解析文本中的工具调用。

    先尝试标准 JSON，失败再回退到中文全角括号格式。
    """
    try:
        tool_calls = _parse_standard_json_blocks(text)
    except Exception:
        tool_calls = []

    if not tool_calls:
        tool_calls = _parse_cjk_bracket_blocks(text)

    return tool_calls


def extract_json_blocks(text: str) -> List[str]:
    """提取文本中所有标准与中文括号 JSON 块（原文）。"""
    blocks = re.findall(_STANDARD_JSON_PATTERN, text, re.DOTALL)
    blocks.extend(re.findall(r"｛[^｝]*｝", text, re.DOTALL))
    return blocks


def normalize_json_format(text: str) -> str:
    """把中文全角括号换成标准括号。"""
    return text.replace("｛", "{").replace("｝", "}")


class IntentAnalyzer:
    """意图分析器：从对话文本中提取工具调用意图。"""

    def analyze_conversation(self, conversation: str) -> Dict[str, Any]:
        try:
            tool_calls = parse_non_standard_json(conversation)

            mcp_calls = [c for c in tool_calls if c.get("agentType") == "mcp"]
            agent_calls = [c for c in tool_calls if c.get("agentType") == "agent"]

            return {
                "has_tasks": len(tool_calls) > 0,
                "tool_calls": tool_calls,
                "mcp_calls": mcp_calls,
                "agent_calls": agent_calls,
                "total_count": len(tool_calls),
            }
        except Exception as exc:
            return {
                "has_tasks": False,
                "error": str(exc),
                "tool_calls": [],
                "mcp_calls": [],
                "agent_calls": [],
                "total_count": 0,
            }

    def extract_mcp_tools(self, conversation: str) -> List[Dict[str, Any]]:
        return self.analyze_conversation(conversation).get("mcp_calls", [])

    def extract_agent_tasks(self, conversation: str) -> List[Dict[str, Any]]:
        return self.analyze_conversation(conversation).get("agent_calls", [])

    def validate_tool_call_format(self, tool_call: Dict[str, Any]) -> bool:
        return validate_tool_call(tool_call)

    def get_tool_call_summary(
        self, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total": len(tool_calls),
            "mcp_count": 0,
            "agent_count": 0,
            "services": set(),
            "tools": set(),
        }

        for tool_call in tool_calls:
            agent_type = tool_call.get("agentType", "")
            if agent_type == "mcp":
                summary["mcp_count"] += 1
            elif agent_type == "agent":
                summary["agent_count"] += 1

            if tool_call.get("service_name"):
                summary["services"].add(tool_call["service_name"])
            if tool_call.get("tool_name"):
                summary["tools"].add(tool_call["tool_name"])

        summary["services"] = list(summary["services"])
        summary["tools"] = list(summary["tools"])
        return summary


__all__ = [
    "parse_non_standard_json",
    "validate_tool_call",
    "extract_json_blocks",
    "normalize_json_format",
    "IntentAnalyzer",
]
