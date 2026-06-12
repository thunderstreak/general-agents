"""命令行交互入口。"""

from agent_app.file_inputs import build_human_message, parse_user_input
from agent_app.config import CLI_STREAM, CLI_STREAM_PROGRESS, ORCHESTRATOR_MAX_STEPS, OUTPUT_DEBUG
from agent_app.graph import app, resume_confirmed_tool
from agent_app.memory import load_memory, memory_to_state
from agent_app.orchestrator import new_trace_id
from agent_app.output import build_response, render_cli_response


def run_cli():
    """启动命令行 Agent。"""
    print("🧠 LangGraph Agent 启动 (输入 'quit' 退出)\n")
    memory = load_memory()
    state = {
        "messages": [],
        "tool_selection": {},
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
        "long_term_memory": memory_to_state(memory),
        "step_count": 0,
        "max_steps": ORCHESTRATOR_MAX_STEPS,
        "last_error": {},
        "pending_confirmation": {},
        "approved_tool_call_ids": [],
        "final_response": {},
        "trace_id": "",
        "node_runs": [],
        "memory_updated": False,
    }  # 持久化状态

    while True:
        user_input = input("你: ")
        if user_input.lower() == "quit":
            break

        if state.get("pending_confirmation"):
            if user_input.lower() in {"yes", "y"}:
                state = resume_confirmed_tool(state, approved=True)
                state = _reset_turn_state(state)
                state = _run_turn(state)
                continue
            if user_input.lower() in {"no", "n"}:
                state = resume_confirmed_tool(state, approved=False)
                state = _reset_turn_state(state)
                _print_response(state)
                continue
            print("请输入 yes 确认执行，或 no 取消。\n")
            continue

        # 保留多轮上下文，让工具调用和模型回复都在消息历史中连续出现
        text, file_results = parse_user_input(user_input)
        state["messages"].append(build_human_message(text, file_results))
        state = _reset_turn_state(state)
        state = _run_turn(state)


def _reset_turn_state(state: dict) -> dict:
    """重置单轮编排状态，保留历史消息和长期记忆。"""
    state["step_count"] = 0
    state["max_steps"] = ORCHESTRATOR_MAX_STEPS
    state["last_error"] = {}
    state["retrieval_results"] = []
    state["final_response"] = {}
    state["trace_id"] = new_trace_id()
    state["node_runs"] = []
    state["memory_updated"] = False
    state["approved_tool_call_ids"] = state.get("approved_tool_call_ids", [])
    return state


def _print_response(state: dict) -> None:
    """打印统一响应。"""
    response = state.get("final_response") or build_response(state)
    print(f"{render_cli_response(response, debug=OUTPUT_DEBUG)}\n")


def _run_turn(state: dict) -> dict:
    """按配置执行单轮对话。"""
    if not CLI_STREAM:
        result = app.invoke(state)
        _print_response(result)
        return result

    return _stream_response(state)


def _stream_response(state: dict) -> dict:
    """流式执行 LangGraph 并渲染 CLI 输出。"""
    latest_state = state
    printed_token = False
    printed_agent_prefix = False
    printed_progress: set[str] = set()

    for chunk in app.stream(state, stream_mode=["messages", "updates", "custom", "values"], version="v2"):
        chunk_type = _stream_chunk_type(chunk)
        data = _stream_chunk_data(chunk)

        if chunk_type == "values" and isinstance(data, dict):
            latest_state = data
            continue

        if chunk_type == "custom":
            message = _custom_progress_message(data)
            if message and CLI_STREAM_PROGRESS and not printed_token:
                printed_agent_prefix = _print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "updates":
            message = _update_progress_message(data)
            if message and CLI_STREAM_PROGRESS and not printed_token:
                printed_agent_prefix = _print_progress(message, printed_agent_prefix, printed_progress)
            continue

        if chunk_type == "messages":
            token = _message_chunk_text(data)
            if not token:
                continue
            if not printed_agent_prefix:
                print("Agent: ", end="", flush=True)
                printed_agent_prefix = True
            print(token, end="", flush=True)
            printed_token = True

    if printed_token:
        print()
        _print_debug_tail(latest_state)
        print()
        return latest_state

    _print_response(latest_state)
    return latest_state


def _stream_chunk_type(chunk) -> str:
    """获取 LangGraph stream chunk 类型。"""
    if isinstance(chunk, dict):
        return str(chunk.get("type", ""))
    if isinstance(chunk, tuple) and chunk:
        return str(chunk[0])
    return ""


def _stream_chunk_data(chunk):
    """获取 LangGraph stream chunk 数据。"""
    if isinstance(chunk, dict):
        return chunk.get("data")
    if isinstance(chunk, tuple) and len(chunk) >= 2:
        return chunk[1]
    return None


def _message_chunk_text(data) -> str:
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


def _custom_progress_message(data) -> str:
    """从 custom stream 事件中提取进度文本。"""
    if isinstance(data, dict):
        return str(data.get("message") or "")
    if isinstance(data, str):
        return data
    return ""


def _update_progress_message(data) -> str:
    """根据节点 update 生成兜底进度文本。"""
    if not isinstance(data, dict) or len(data) != 1:
        return ""

    node_name = next(iter(data))
    labels = {
        "retrieval": "检索中...",
        "agent": "思考中...",
        "confirm": "等待人工确认...",
        "tools": "执行工具中...",
        "memory": "更新记忆...",
        "error": "生成错误响应...",
        "response": "整理响应...",
    }
    return labels.get(node_name, "")


def _print_progress(message: str, printed_agent_prefix: bool, printed_progress: set[str]) -> bool:
    """打印去重后的进度信息。"""
    if not message or message in printed_progress:
        return printed_agent_prefix
    printed_progress.add(message)
    if printed_agent_prefix:
        print()
    print(message, flush=True)
    return False


def _print_debug_tail(state: dict) -> None:
    """流式结束后补充 debug 信息。"""
    if not OUTPUT_DEBUG:
        return

    response = state.get("final_response") or build_response(state)
    debug_text = render_cli_response(response, debug=True)
    lines = debug_text.splitlines()
    if len(lines) <= 1:
        return
    print("\n" + "\n".join(lines[1:]))
