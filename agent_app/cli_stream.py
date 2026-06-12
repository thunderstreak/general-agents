"""CLI 流式输出渲染。"""

from typing import Any

from agent_app.config import CLI_STREAM_PROGRESS, OUTPUT_DEBUG
from agent_app.output import build_response, render_cli_response


def stream_response(app, state: dict[str, Any]) -> dict[str, Any]:
    """流式执行 LangGraph 并渲染 CLI 输出。"""
    latest_state = state
    printed_token = False
    printed_agent_prefix = False
    printed_progress: set[str] = set()

    for chunk in app.stream(state, stream_mode=["messages", "updates", "custom", "values"], version="v2"):
        chunk_type = stream_chunk_type(chunk)
        data = stream_chunk_data(chunk)

        if chunk_type == "values" and isinstance(data, dict):
            latest_state = data
            continue

        if chunk_type == "custom":
            message = custom_progress_message(data)
            if message and CLI_STREAM_PROGRESS and not printed_token:
                printed_agent_prefix = print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "updates":
            message = update_progress_message(data)
            if message and CLI_STREAM_PROGRESS and not printed_token:
                printed_agent_prefix = print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "messages":
            token = message_chunk_text(data)
            if not token:
                continue
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


def custom_progress_message(data) -> str:
    """从 custom stream 事件中提取进度文本。"""
    if isinstance(data, dict):
        return str(data.get("message") or "")
    if isinstance(data, str):
        return data
    return ""


def update_progress_message(data) -> str:
    """根据必要状态类节点 update 生成兜底进度文本。"""
    if not isinstance(data, dict) or len(data) != 1:
        return ""

    node_name = next(iter(data))
    labels = {
        "confirm": "等待人工确认...",
        "tools": "执行工具中...",
        "reflection": "核对工具结果...",
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
