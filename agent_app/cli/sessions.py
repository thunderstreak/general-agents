"""CLI 会话命令处理。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionOperations:
    """会话命令依赖操作。"""

    create_session: Callable[[], Any]
    create_initial_state: Callable[[], dict]
    ensure_state_defaults: Callable[[dict], dict]
    load_session_state: Callable[[str], dict]
    session_exists: Callable[[str], bool]
    list_sessions: Callable[[], list]
    save_current_session: Callable[..., None]


def handle_session_command(command: str, arg: str, state: dict, session_id: str, operations: SessionOperations) -> tuple[bool, dict, str, str]:
    """处理会话相关 CLI 命令。"""
    if command == "/sessions":
        print_sessions(operations)
        return True, state, session_id, ""

    if command == "/current":
        print_current_session(session_id, operations)
        return True, state, session_id, ""

    if command == "/new":
        session = operations.create_session()
        new_state = operations.create_initial_state()
        operations.save_current_session(session.session_id, new_state)
        print(f"已创建并切换到新会话：{session.session_id}\n")
        return True, new_state, session.session_id, ""

    if command == "/resume":
        if not arg:
            print("用法：/resume <session_id>\n")
            return True, state, session_id, ""
        if not operations.session_exists(arg):
            print(f"会话不存在：{arg}\n")
            return True, state, session_id, ""
        resumed_state = operations.ensure_state_defaults(operations.load_session_state(arg))
        print(f"已恢复会话：{arg}\n")
        return True, resumed_state, arg, ""

    if command == "/delete":
        if not arg:
            print("用法：/delete <session_id>\n")
            return True, state, session_id, ""
        if not operations.session_exists(arg):
            print(f"会话不存在：{arg}\n")
            return True, state, session_id, ""
        print(f"确认删除会话 {arg}？请输入 yes 确认，或 no 取消。\n")
        return True, state, session_id, arg

    return False, state, session_id, ""


def print_sessions(operations: SessionOperations) -> None:
    """打印会话列表。"""
    sessions = operations.list_sessions()
    if not sessions:
        print("暂无历史会话。\n")
        return

    print("历史会话：")
    for item in sessions:
        title = item.title or "未命名会话"
        last_input = f" | 最后输入：{item.last_user_input}" if item.last_user_input else ""
        print(f"- {item.session_id} | {title} | {item.updated_at} | {item.message_count} 条消息{last_input}")
    print()


def print_current_session(session_id: str, operations: SessionOperations) -> None:
    """打印当前会话。"""
    for item in operations.list_sessions():
        if item.session_id == session_id:
            print(f"当前会话：{item.session_id} | {item.title} | {item.updated_at} | {item.message_count} 条消息\n")
            return
    print(f"当前会话：{session_id}\n")


def session_metadata_or_current(session_id: str, current_session, operations: SessionOperations):
    """命令切换后获取会话元数据，不存在时保留旧对象。"""
    for item in operations.list_sessions():
        if item.session_id == session_id:
            return item
    return current_session
