"""输入感知理解节点。"""

import re
import time

from langchain_core.messages import HumanMessage

from agent_app.nodes.common import latest_human_message, node_run
from agent_app.orchestrator import should_retrieve
from agent_app.state import AgentState
from agent_app.tools import candidate_tool_names_for_text
from agent_app.utils.messages import message_text


FILE_CONTENT_PATTERN = re.compile(r"\[文件内容\]\n路径：(?P<path>.+?)\n类型：(?P<kind>.+?)\n内容：", re.S)
FILE_ERROR_PATTERN = re.compile(r"\[文件解析失败\]\n路径：(?P<path>.+?)\n原因：(?P<error>.+?)(?=\n\n\[|$)", re.S)
IMAGE_FILE_PATTERN = re.compile(r"\[图片文件\]\n路径：(?P<path>.+?)\n说明：(?P<description>.+?)(?=\n\n\[|$)", re.S)


def perception_node(state: AgentState):
    """提取最近用户输入的结构化上下文。"""
    start_time = time.perf_counter()
    latest_message = latest_human_message(state.get("messages", []))
    context = build_input_context(latest_message)
    return {"input_context": context, "node_runs": [node_run("perception", start_time)]}


def build_input_context(message) -> dict:
    """构建单轮输入上下文。"""
    raw_text = message_text(message)
    normalized_text = _normalize_text(raw_text)
    attachments = _extract_attachments(raw_text)
    file_errors = _extract_file_errors(raw_text)
    has_image = _has_image_message(message) or any(item.get("kind") == "image" for item in attachments)
    candidate_tool_names = candidate_tool_names_for_text(normalized_text)

    return {
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "message_text": raw_text,
        "attachments": attachments,
        "file_errors": file_errors,
        "has_image": has_image,
        "requires_vision": has_image,
        "intent_signals": _intent_signals(normalized_text, candidate_tool_names),
        "should_retrieve": should_retrieve(normalized_text),
        "candidate_tool_names": candidate_tool_names,
    }


def _extract_attachments(text: str) -> list[dict]:
    """从 CLI 拼接文本中提取附件摘要。"""
    attachments = []
    for match in FILE_CONTENT_PATTERN.finditer(text):
        attachments.append(
            {
                "path": match.group("path").strip(),
                "kind": match.group("kind").strip(),
                "status": "parsed",
            }
        )
    for match in IMAGE_FILE_PATTERN.finditer(text):
        attachments.append(
            {
                "path": match.group("path").strip(),
                "kind": "image",
                "status": "attached",
                "description": match.group("description").strip(),
            }
        )
    return attachments


def _extract_file_errors(text: str) -> list[dict]:
    """从 CLI 拼接文本中提取文件解析错误。"""
    errors = []
    for match in FILE_ERROR_PATTERN.finditer(text):
        errors.append(
            {
                "path": match.group("path").strip(),
                "error": match.group("error").strip(),
            }
        )
    return errors


def _has_image_message(message) -> bool:
    """判断 HumanMessage 是否包含图片内容块。"""
    if not isinstance(message, HumanMessage):
        return False
    content = getattr(message, "content", "")
    if not isinstance(content, list):
        return False
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            return True
    return False


def _intent_signals(text: str, candidate_tool_names: list[str]) -> list[str]:
    """生成本地意图信号。"""
    signals = []
    if should_retrieve(text):
        signals.append("rag")
    if "fetch_url" in candidate_tool_names:
        signals.append("url")
    if "get_weather" in candidate_tool_names or "get_weather_forecast" in candidate_tool_names:
        signals.append("weather")
    if "web_search" in candidate_tool_names:
        signals.append("search")
    if "get_location" in candidate_tool_names:
        signals.append("location")
    return list(dict.fromkeys(signals))


def _normalize_text(text: str) -> str:
    """标准化输入文本。"""
    return " ".join(str(text or "").split())
