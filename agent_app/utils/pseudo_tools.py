"""伪工具调用解析与清理。"""

import re
from typing import Any

from langchain_core.messages import ToolCall


PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(r"<tool_call\b[^>]*>.*?</tool_call>", re.IGNORECASE | re.DOTALL)
PSEUDO_TOOL_CALL_START_PATTERN = re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE)
PSEUDO_FUNCTION_PATTERN = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.IGNORECASE | re.DOTALL)
PSEUDO_PARAMETER_PATTERN = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.IGNORECASE | re.DOTALL)
PSEUDO_FUNCTION_BLOCK_PATTERN = re.compile(r"<function=[^>]+>.*?</function>", re.IGNORECASE | re.DOTALL)
PSEUDO_TOOL_CALL_TAG_PATTERN = re.compile(r"</?tool_call\b[^>]*>", re.IGNORECASE)
PSEUDO_PARAMETER_TAG_PATTERN = re.compile(r"</?parameter\b[^>]*>", re.IGNORECASE)
PSEUDO_TOOL_MARKERS = ("<tool_call", "</tool_call", "<function=", "</function", "<parameter", "</parameter")
PSEUDO_TOOL_NAME_ALIASES = {"search_internet": "web_search"}


def sanitize_pseudo_tool_content(content: Any) -> str:
    """清理模型误输出的伪工具调用文本。"""
    text = message_content_text(content)
    text = PSEUDO_TOOL_CALL_BLOCK_PATTERN.sub("", text)
    text = PSEUDO_FUNCTION_BLOCK_PATTERN.sub("", text)
    text = PSEUDO_TOOL_CALL_TAG_PATTERN.sub("", text)
    text = PSEUDO_PARAMETER_TAG_PATTERN.sub("", text)
    return text.strip()


def parse_pseudo_tool_calls(content: Any, tools_by_name: dict[str, Any]) -> list[ToolCall]:
    """从伪 XML 工具调用文本中解析 tool_calls。"""
    text = message_content_text(content)
    if not text:
        return []

    calls = []
    for block_match in PSEUDO_TOOL_CALL_BLOCK_PATTERN.finditer(text):
        block = block_match.group(0)
        for function_match in PSEUDO_FUNCTION_PATTERN.finditer(block):
            tool_name = normalize_pseudo_tool_name(function_match.group(1).strip())
            if tool_name not in tools_by_name:
                continue
            tool_args = parse_pseudo_tool_args(tool_name, function_match.group(2), tools_by_name)
            calls.append(ToolCall(name=tool_name, args=tool_args, id=f"pseudo_{tool_name}_{len(calls) + 1}"))
    return calls


def parse_pseudo_tool_args(tool_name: str, body: str, tools_by_name: dict[str, Any]) -> dict[str, Any]:
    """解析并按工具 schema 过滤参数。"""
    allowed_args = set((getattr(tools_by_name[tool_name], "args", None) or {}).keys())
    args: dict[str, Any] = {}
    for match in PSEUDO_PARAMETER_PATTERN.finditer(body):
        name = match.group(1).strip()
        if allowed_args and name not in allowed_args:
            continue
        args[name] = match.group(2).strip()
    return args


def normalize_pseudo_tool_name(tool_name: str) -> str:
    """兼容历史 prompt 中出现过的工具别名。"""
    return PSEUDO_TOOL_NAME_ALIASES.get(tool_name, tool_name)


def message_content_text(content: Any) -> str:
    """将消息 content 转成纯文本。"""
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
    return str(content or "")


def partial_tool_marker_index(text: str) -> int:
    """查找尾部可能组成伪工具调用标签的位置。"""
    lower_text = text.lower()
    for index in range(len(text) - 1, -1, -1):
        if text[index] != "<":
            continue
        tail = lower_text[index:]
        if tail and any(marker.startswith(tail) for marker in PSEUDO_TOOL_MARKERS):
            return index
    return -1
