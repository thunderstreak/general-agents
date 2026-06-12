"""命令行交互入口。"""

from agent_app.file_inputs import build_human_message, parse_user_input
from agent_app.config import CLI_INPUT_HISTORY_FILE, CLI_STREAM, CLI_STREAM_PROGRESS, ORCHESTRATOR_MAX_STEPS, OUTPUT_DEBUG, SESSION_AUTO_SAVE
from agent_app.graph import app, resume_confirmed_tool
from agent_app.memory import load_memory, memory_to_state
from agent_app.orchestrator import new_trace_id
from agent_app.output import build_response, render_cli_response
from agent_app.session_store import create_session, delete_session, list_sessions, load_session_state, save_session_state, session_exists


def run_cli():
    """启动命令行 Agent。"""
    print("🧠 LangGraph Agent 启动 (输入 'quit' 退出)\n")
    session = create_session()
    state = _new_state()
    _save_current_session(session.session_id, state)
    pending_delete_session_id = ""

    while True:
        user_input = _read_user_input()
        if user_input.lower() == "quit":
            break

        if pending_delete_session_id:
            if user_input.lower() in {"yes", "y"}:
                deleted_current = pending_delete_session_id == session.session_id
                if delete_session(pending_delete_session_id):
                    print(f"已删除会话：{pending_delete_session_id}\n")
                else:
                    print(f"会话不存在：{pending_delete_session_id}\n")
                pending_delete_session_id = ""
                if deleted_current:
                    session = create_session()
                    state = _new_state()
                    _save_current_session(session.session_id, state)
                    print(f"已切换到新会话：{session.session_id}\n")
                continue
            if user_input.lower() in {"no", "n"}:
                print("已取消删除。\n")
                pending_delete_session_id = ""
                continue
            print("请输入 yes 确认删除，或 no 取消。\n")
            continue

        handled, state, session_id, pending_delete_session_id = _handle_cli_command(user_input, state, session.session_id)
        if handled:
            if session_id != session.session_id:
                session = _session_metadata_or_current(session_id, session)
            continue

        if state.get("pending_confirmation"):
            if user_input.lower() in {"yes", "y"}:
                state = resume_confirmed_tool(state, approved=True)
                state = _reset_turn_state(state)
                state = _run_turn(state)
                _save_current_session(session.session_id, state)
                continue
            if user_input.lower() in {"no", "n"}:
                state = resume_confirmed_tool(state, approved=False)
                state = _reset_turn_state(state)
                _print_response(state)
                _save_current_session(session.session_id, state)
                continue
            print("请输入 yes 确认执行，或 no 取消。\n")
            continue

        # 保留多轮上下文，让工具调用和模型回复都在消息历史中连续出现
        text, file_results = parse_user_input(user_input)
        state["messages"].append(build_human_message(text, file_results))
        state = _reset_turn_state(state)
        state = _run_turn(state)
        _save_current_session(session.session_id, state)


def _new_state() -> dict:
    """创建新的 CLI Agent state。"""
    memory = load_memory()
    return {
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
    }


def _read_user_input() -> str:
    """读取用户输入，优先使用 prompt_toolkit 改善中文编辑体验。"""
    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.history import FileHistory
    except ImportError:
        return input("你: ")

    return prompt(
        "你: ",
        history=FileHistory(CLI_INPUT_HISTORY_FILE),
        complete_while_typing=False,
    )


def _handle_cli_command(user_input: str, state: dict, session_id: str) -> tuple[bool, dict, str, str]:
    """处理会话管理命令。"""
    text = user_input.strip()
    if not text.startswith("/"):
        return False, state, session_id, ""

    command, _, arg = text.partition(" ")
    arg = arg.strip()
    if command == "/sessions":
        _print_sessions()
        return True, state, session_id, ""

    if command == "/current":
        _print_current_session(session_id)
        return True, state, session_id, ""

    if command == "/new":
        session = create_session()
        new_state = _new_state()
        _save_current_session(session.session_id, new_state)
        print(f"已创建并切换到新会话：{session.session_id}\n")
        return True, new_state, session.session_id, ""

    if command == "/resume":
        if not arg:
            print("用法：/resume <session_id>\n")
            return True, state, session_id, ""
        if not session_exists(arg):
            print(f"会话不存在：{arg}\n")
            return True, state, session_id, ""
        resumed_state = _ensure_state_defaults(load_session_state(arg))
        print(f"已恢复会话：{arg}\n")
        return True, resumed_state, arg, ""

    if command == "/delete":
        if not arg:
            print("用法：/delete <session_id>\n")
            return True, state, session_id, ""
        if not session_exists(arg):
            print(f"会话不存在：{arg}\n")
            return True, state, session_id, ""
        print(f"确认删除会话 {arg}？请输入 yes 确认，或 no 取消。\n")
        return True, state, session_id, arg

    print("未知命令。可用命令：/sessions、/resume <session_id>、/new、/delete <session_id>、/current\n")
    return True, state, session_id, ""


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


def _ensure_state_defaults(state: dict) -> dict:
    """补齐旧会话或损坏会话缺失的 state 字段。"""
    defaults = _new_state()
    defaults.update(state)
    defaults["messages"] = state.get("messages", [])
    defaults["long_term_memory"] = state.get("long_term_memory") or defaults["long_term_memory"]
    return defaults


def _save_current_session(session_id: str, state: dict) -> None:
    """按配置保存当前会话。"""
    if not SESSION_AUTO_SAVE:
        return
    save_session_state(session_id, state)


def _print_sessions() -> None:
    """打印会话列表。"""
    sessions = list_sessions()
    if not sessions:
        print("暂无历史会话。\n")
        return

    print("历史会话：")
    for item in sessions:
        title = item.title or "未命名会话"
        last_input = f" | 最后输入：{item.last_user_input}" if item.last_user_input else ""
        print(f"- {item.session_id} | {title} | {item.updated_at} | {item.message_count} 条消息{last_input}")
    print()


def _print_current_session(session_id: str) -> None:
    """打印当前会话。"""
    for item in list_sessions():
        if item.session_id == session_id:
            print(f"当前会话：{item.session_id} | {item.title} | {item.updated_at} | {item.message_count} 条消息\n")
            return
    print(f"当前会话：{session_id}\n")


def _session_metadata_or_current(session_id: str, current_session):
    """命令切换后获取会话元数据，不存在时保留旧对象。"""
    for item in list_sessions():
        if item.session_id == session_id:
            return item
    return current_session


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
