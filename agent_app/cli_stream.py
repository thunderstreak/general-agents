"""CLI 流式输出渲染。"""

import re
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

from agent_app.config import CLI_STREAM_PROGRESS, OUTPUT_DEBUG
from agent_app.output import build_response, render_cli_response

PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(r"<tool_call\b[^>]*>.*?</tool_call>", re.IGNORECASE | re.DOTALL)
PSEUDO_TOOL_CALL_START_PATTERN = re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE)
PSEUDO_PARAMETER_PATTERN = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.IGNORECASE | re.DOTALL)
PSEUDO_TOOL_MARKERS = ("<tool_call", "</tool_call", "<function=", "</function", "<parameter", "</parameter")


def stream_response(app, state: dict[str, Any]) -> dict[str, Any]:
    """流式执行 LangGraph 并渲染 CLI 输出。"""
    latest_state = state
    printed_token = False
    printed_agent_prefix = False
    printed_progress: set[str] = set()
    display_filter = PseudoToolCallDisplayFilter()

    for chunk in app.stream(state, stream_mode=["messages", "updates", "custom", "values"], version="v2"):
        chunk_type = stream_chunk_type(chunk)
        data = stream_chunk_data(chunk)

        if chunk_type == "values" and isinstance(data, dict):
            latest_state = data
            continue

        if chunk_type == "custom":
            message = custom_progress_message(data)
            if message and should_print_custom_progress(data) and CLI_STREAM_PROGRESS:
                printed_agent_prefix = print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "updates":
            message = update_progress_message(data)
            if message and CLI_STREAM_PROGRESS and not printed_token:
                printed_agent_prefix = print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "messages":
            token, tool_call_preview = display_filter.feed(message_chunk_text(data))
            if tool_call_preview and CLI_STREAM_PROGRESS:
                printed_agent_prefix = print_progress(tool_call_preview, printed_agent_prefix, printed_progress)
            if not token:
                continue
            if not printed_agent_prefix:
                print("Agent: ", end="", flush=True)
                printed_agent_prefix = True
            print(token, end="", flush=True)
            printed_token = True

    token, tool_call_preview = display_filter.flush()
    if tool_call_preview and CLI_STREAM_PROGRESS:
        printed_agent_prefix = print_progress(tool_call_preview, printed_agent_prefix, printed_progress)
    if token:
        if not printed_agent_prefix:
            print("Agent: ", end="", flush=True)
            printed_agent_prefix = True
        print(token, end="", flush=True)
        printed_token = True

    if printed_token:
        print()
        print_debug_tail(latest_state)
        print()
        return latest_state

    print_response(latest_state)
    return latest_state


def print_response(state: dict[str, Any]) -> None:
    """打印统一响应。"""
    response = state.get("final_response") or build_response(state)
    print(f"{render_cli_response(response, debug=OUTPUT_DEBUG)}\n")


def stream_chunk_type(chunk) -> str:
    """获取 LangGraph stream chunk 类型。"""
    if isinstance(chunk, dict):
        return str(chunk.get("type", ""))
    if isinstance(chunk, tuple) and chunk:
        return str(chunk[0])
    return ""


def stream_chunk_data(chunk):
    """获取 LangGraph stream chunk 数据。"""
    if isinstance(chunk, dict):
        return chunk.get("data")
    if isinstance(chunk, tuple) and len(chunk) >= 2:
        return chunk[1]
    return None


def message_chunk_text(data) -> str:
    """提取可展示给用户的模型 token。"""
    message = None
    metadata = {}
    if isinstance(data, tuple) and data:
        message = data[0]
        if len(data) > 1 and isinstance(data[1], dict):
            metadata = data[1]
    else:
        message = data

    tags = set(metadata.get("tags") or [])
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, dict):
        tags.update(nested_metadata.get("tags") or [])
    if "nostream" in tags:
        return ""

    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return ""

    if getattr(message, "tool_call_chunks", None) or getattr(message, "tool_calls", None):
        return ""

    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
        return "".join(text_parts)

    return ""


class PseudoToolCallDisplayFilter:
    """把流式伪工具调用转换为可读展示文本。"""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, token: str) -> tuple[str, str]:
        """处理一个 token，返回普通回答文本和工具调用预览。"""
        if not token:
            return "", ""

        self._pending += token
        return self._drain(keep_partial=True)

    def flush(self) -> tuple[str, str]:
        """流结束时输出剩余文本。"""
        text, preview = self._drain(keep_partial=False)
        if self._pending:
            text += self._pending
            self._pending = ""
        return text, preview

    def _drain(self, keep_partial: bool) -> tuple[str, str]:
        """尽量消费缓冲区中的完整伪工具调用。"""
        visible_parts = []
        preview_parts = []

        while True:
            match = PSEUDO_TOOL_CALL_BLOCK_PATTERN.search(self._pending)
            if not match:
                break
            visible_parts.append(self._pending[: match.start()])
            preview = _pseudo_tool_call_preview(match.group(0))
            if preview:
                preview_parts.append(preview)
            self._pending = self._pending[match.end() :]

        if not self._pending:
            return "".join(visible_parts), "\n".join(preview_parts)

        start_match = PSEUDO_TOOL_CALL_START_PATTERN.search(self._pending) if keep_partial else None
        if start_match:
            visible_parts.append(self._pending[: start_match.start()])
            self._pending = self._pending[start_match.start() :]
            return "".join(visible_parts), "\n".join(preview_parts)

        marker_index = _partial_tool_marker_index(self._pending) if keep_partial else -1
        if marker_index == -1:
            visible_parts.append(self._pending)
            self._pending = ""
        else:
            visible_parts.append(self._pending[:marker_index])
            self._pending = self._pending[marker_index:]

        return "".join(visible_parts), "\n".join(preview_parts)


def _pseudo_tool_call_preview(block: str) -> str:
    """提取伪工具调用中适合展示给用户的参数值。"""
    args = {}
    for match in PSEUDO_PARAMETER_PATTERN.finditer(block):
        args[match.group(1).strip()] = match.group(2).strip()
    for name in ("query", "url", "city"):
        if args.get(name):
            return args[name]
    return next((value for value in args.values() if value), "")


def _partial_tool_marker_index(text: str) -> int:
    """查找尾部可能组成伪工具调用标签的位置。"""
    lower_text = text.lower()
    for index in range(len(text) - 1, -1, -1):
        if text[index] != "<":
            continue
        tail = lower_text[index:]
        if tail and any(marker.startswith(tail) for marker in PSEUDO_TOOL_MARKERS):
            return index
    return -1


def custom_progress_message(data) -> str:
    """从 custom stream 事件中提取进度文本。"""
    if isinstance(data, dict):
        return str(data.get("message") or "")
    if isinstance(data, str):
        return data
    return ""


def should_print_custom_progress(data) -> bool:
    """判断 custom 进度是否适合展示给用户。"""
    if not isinstance(data, dict):
        return True
    event = str(data.get("event") or "")
    node = str(data.get("node") or "")
    if node in {"memory", "response"}:
        return event in {"tool_started", "tool_succeeded", "tool_failed"}
    return True


def update_progress_message(data) -> str:
    """根据必要状态类节点 update 生成兜底进度文本。"""
    if not isinstance(data, dict) or len(data) != 1:
        return ""

    node_name = next(iter(data))
    labels = {
        "confirm": "等待人工确认...",
        "error": "生成错误响应...",
    }
    return labels.get(node_name, "")


def print_progress(message: str, printed_agent_prefix: bool, printed_progress: set[str]) -> bool:
    """打印去重后的进度信息。"""
    if not message or message in printed_progress:
        return printed_agent_prefix
    printed_progress.add(message)
    if printed_agent_prefix:
        print()
    print(message, flush=True)
    return False


def print_debug_tail(state: dict[str, Any]) -> None:
    """流式结束后补充 debug 信息。"""
    if not OUTPUT_DEBUG:
        return

    response = state.get("final_response") or build_response(state)
    debug_text = render_cli_response(response, debug=True)
    lines = debug_text.splitlines()
    try:
        debug_start = lines.index("Debug:")
    except ValueError:
        return
    print("\n" + "\n".join(lines[debug_start:]))
