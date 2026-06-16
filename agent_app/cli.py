"""命令行交互入口。"""

from agent_app.file_inputs import build_human_message, parse_user_input
from agent_app.config import CLI_INPUT_HISTORY_FILE, CLI_STREAM, CLI_STREAM_PROGRESS, OUTPUT_DEBUG, SESSION_AUTO_SAVE
from agent_app import cli_stream
from agent_app.cli_cancel import TaskCancelled, run_with_esc_cancel
from agent_app.graph import get_app, resume_confirmed_tool
from agent_app.rag import (
    KnowledgeBaseError,
    add_document,
    clear_knowledge_base,
    delete_document,
    list_documents,
    rebuild_knowledge_base,
    sync_knowledge_base,
)
from agent_app.session_store import create_session, delete_session, list_sessions, load_session_state, save_session_state, session_exists
from agent_app.state import create_initial_state, ensure_state_defaults, reset_turn_state


_stream_chunk_type = cli_stream.stream_chunk_type
_stream_chunk_data = cli_stream.stream_chunk_data
_message_chunk_text = cli_stream.message_chunk_text
_custom_progress_message = cli_stream.custom_progress_message
_update_progress_message = cli_stream.update_progress_message
_print_progress = cli_stream.print_progress
_print_debug_tail = cli_stream.print_debug_tail


def run_cli():
    """启动命令行 Agent。"""
    print("🧠 LangGraph Agent 启动 (输入 'quit' 退出，任务运行中按 Esc 取消)\n")
    session = create_session()
    state = create_initial_state()
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
                    state = create_initial_state()
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
                state = reset_turn_state(state)
                try:
                    state = _run_turn_cancellable(state)
                except TaskCancelled:
                    state = reset_turn_state(state)
                    _save_current_session(session.session_id, state)
                    continue
                _save_current_session(session.session_id, state)
                continue
            if user_input.lower() in {"no", "n"}:
                state = resume_confirmed_tool(state, approved=False)
                state = reset_turn_state(state)
                _print_response(state)
                _save_current_session(session.session_id, state)
                continue
            print("请输入 yes 确认执行，或 no 取消。\n")
            continue

        # 保留多轮上下文，让工具调用和模型回复都在消息历史中连续出现
        text, file_results = parse_user_input(user_input)
        message_count_before_turn = len(state.get("messages", []))
        state["messages"].append(build_human_message(text, file_results))
        state = reset_turn_state(state)
        try:
            state = _run_turn_cancellable(state)
        except TaskCancelled:
            state["messages"] = state.get("messages", [])[:message_count_before_turn]
            state = reset_turn_state(state)
            _save_current_session(session.session_id, state)
            continue
        _save_current_session(session.session_id, state)


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
    """处理 CLI 命令。"""
    text = user_input.strip()
    if not text.startswith("/"):
        return False, state, session_id, ""

    command, _, arg = text.partition(" ")
    arg = arg.strip()
    if command == "/rag":
        try:
            _handle_rag_command(arg)
        except TaskCancelled:
            pass
        return True, state, session_id, ""

    if command == "/sessions":
        _print_sessions()
        return True, state, session_id, ""

    if command == "/current":
        _print_current_session(session_id)
        return True, state, session_id, ""

    if command == "/new":
        session = create_session()
        new_state = create_initial_state()
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
        resumed_state = ensure_state_defaults(load_session_state(arg))
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

    print("未知命令。可用命令：/rag、/sessions、/resume <session_id>、/new、/delete <session_id>、/current\n")
    return True, state, session_id, ""


def _handle_rag_command(arg: str) -> None:
    """处理 RAG 知识库命令。"""
    subcommand, _, value = arg.partition(" ")
    subcommand = subcommand.strip()
    value = value.strip()

    if subcommand == "add":
        if not value:
            print("用法：/rag add <文件路径>\n")
            return
        _run_cancellable(lambda: _rag_add(value))
        return

    if subcommand == "list":
        _rag_list()
        return

    if subcommand == "delete":
        if not value:
            print("用法：/rag delete <document_id>\n")
            return
        _rag_delete(value)
        return

    if subcommand == "clear":
        _run_cancellable(_rag_clear)
        return

    if subcommand == "sync":
        _run_cancellable(_rag_sync)
        return

    if subcommand == "rebuild":
        _run_cancellable(_rag_rebuild)
        return

    print("RAG 命令：/rag add <文件路径>、/rag list、/rag delete <document_id>、/rag clear、/rag sync、/rag rebuild\n")


def _rag_add(path: str) -> None:
    """导入知识库文档。"""
    path = path.strip().removeprefix("@").strip("\"'")
    try:
        result = add_document(path)
    except KnowledgeBaseError as exc:
        print(f"导入失败：{exc}\n")
        return
    document = result["document"]
    status = "已更新" if result["status"] == "updated" else "已导入"
    if result["status"] == "unchanged":
        status = "内容未变化"
    print(f"{status}：{document['document_id']} | {document['title']} | {document['chunk_count']} 个片段\n")


def _rag_list() -> None:
    """打印知识库文档列表。"""
    documents = list_documents()
    if not documents:
        print("知识库暂无文档。\n")
        return

    print("知识库文档：")
    for item in documents:
        print(f"- {item['document_id']} | {item['title']} | {item['chunk_count']} 个片段 | {item['path']}")
    print()


def _rag_delete(document_id: str) -> None:
    """删除知识库文档。"""
    if delete_document(document_id):
        print(f"已删除知识库文档：{document_id}\n")
    else:
        print(f"知识库文档不存在：{document_id}\n")


def _rag_clear() -> None:
    """清空知识库。"""
    count = clear_knowledge_base()
    print(f"已清空知识库，共删除 {count} 个文档。\n")


def _rag_sync() -> None:
    """同步知识库文档。"""
    summary = sync_knowledge_base()
    print(
        "知识库同步完成："
        f"检查 {summary['checked']} 个，"
        f"更新 {summary['updated']} 个，"
        f"未变化 {summary['unchanged']} 个，"
        f"缺失 {summary['missing']} 个，"
        f"失败 {summary['failed']} 个。\n"
    )


def _rag_rebuild() -> None:
    """重建知识库索引。"""
    summary = rebuild_knowledge_base()
    print(
        "知识库重建完成："
        f"检查 {summary['checked']} 个，"
        f"重建 {summary['rebuilt']} 个，"
        f"缺失 {summary['missing']} 个，"
        f"失败 {summary['failed']} 个。\n"
    )


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
    cli_stream.print_response(state)


def _run_turn(state: dict) -> dict:
    """按配置执行单轮对话。"""
    if not CLI_STREAM:
        result = get_app().invoke(state)
        _print_response(result)
        return result

    return _stream_response(state)


def _run_turn_cancellable(state: dict) -> dict:
    """执行可取消的单轮任务。"""
    return _run_cancellable(lambda: _run_turn(state))


def _run_cancellable(fn):
    """执行可取消任务。"""
    return run_with_esc_cancel(fn)


def _stream_response(state: dict) -> dict:
    """流式执行 LangGraph 并渲染 CLI 输出。"""
    cli_stream.CLI_STREAM_PROGRESS = CLI_STREAM_PROGRESS
    cli_stream.OUTPUT_DEBUG = OUTPUT_DEBUG
    return cli_stream.stream_response(get_app(), state)
