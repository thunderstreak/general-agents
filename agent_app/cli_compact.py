"""CLI 上下文压缩命令处理。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_app.cli_cancel import TaskCancelled


@dataclass(frozen=True)
class CompactOperations:
    """上下文压缩依赖操作。"""

    compact_state: Callable[..., Any]
    estimate_context_usage: Callable[[dict, int], Any]
    should_auto_compact: Callable[[dict, int], bool]
    save_current_session: Callable[..., None]
    run_cancellable: Callable[[Callable[[], object]], object]
    enabled: bool
    keep_turns: int
    message_threshold: int


def handle_compact_command(arg: str, state: dict, session_id: str, operations: CompactOperations) -> tuple[bool, dict, str, str]:
    """处理上下文压缩命令。"""
    subcommand = arg.strip()
    if subcommand in {"status", "usage"}:
        print(f"{format_context_usage(state, operations)}\n")
        return True, state, session_id, ""

    if subcommand == "show":
        print(format_context_usage(state, operations))
        summary = str(state.get("conversation_summary") or "").strip()
        if summary:
            print(f"当前会话摘要：\n{summary}\n")
        else:
            print("当前会话暂无压缩摘要。\n")
        return True, state, session_id, ""

    if subcommand == "clear":
        state = dict(state)
        state["conversation_summary"] = ""
        state["compact_count"] = 0
        state["last_compacted_at"] = ""
        operations.save_current_session(session_id, state)
        print("已清空当前会话摘要。已压缩移除的短期上下文不会自动恢复。\n")
        return True, state, session_id, ""

    if subcommand:
        print("用法：/compact、/compact status、/compact show、/compact clear\n")
        return True, state, session_id, ""

    before_usage = operations.estimate_context_usage(state, operations.message_threshold)
    print(format_context_usage(state, operations))
    try:
        result = operations.run_cancellable(lambda: operations.compact_state(state, keep_turns=operations.keep_turns))
    except TaskCancelled:
        return True, state, session_id, ""
    if not result.archived_messages:
        print("当前上下文无需压缩。\n")
        return True, result.state, session_id, ""

    operations.save_current_session(session_id, result.state, archived_messages=result.archived_messages)
    after_usage = operations.estimate_context_usage(result.state, operations.message_threshold)
    print(
        f"已压缩上下文：保留最近 {operations.keep_turns} 轮，"
        f"消息数 {before_usage.message_count} -> {after_usage.message_count}，"
        f"{format_usage_delta(before_usage, after_usage)}，"
        f"摘要长度 {len(result.summary)} 字。\n"
    )
    return True, result.state, session_id, ""


def auto_compact_if_needed(state: dict, session_id: str, operations: CompactOperations) -> dict:
    """按阈值自动压缩上下文。"""
    if not operations.enabled or not operations.should_auto_compact(state, operations.message_threshold):
        return state

    before_usage = operations.estimate_context_usage(state, operations.message_threshold)
    try:
        result = operations.run_cancellable(lambda: operations.compact_state(state, keep_turns=operations.keep_turns))
    except TaskCancelled:
        return state
    if not result.archived_messages:
        return state

    operations.save_current_session(session_id, result.state, archived_messages=result.archived_messages)
    after_usage = operations.estimate_context_usage(result.state, operations.message_threshold)
    print(
        f"已自动压缩上下文：保留最近 {operations.keep_turns} 轮，"
        f"消息数 {before_usage.message_count} -> {after_usage.message_count}，"
        f"{format_usage_delta(before_usage, after_usage)}，"
        f"摘要长度 {len(result.summary)} 字。\n"
    )
    return result.state


def format_context_usage(state: dict, operations: CompactOperations) -> str:
    """格式化上下文使用量提示。"""
    usage = operations.estimate_context_usage(state, operations.message_threshold)
    if usage.token_available:
        return (
            f"当前上下文使用率：约 {usage.percent}%"
            f"（{usage.used_tokens}/{usage.context_window_tokens} tokens，"
            f"预留输出 {usage.reserved_output_tokens}，"
            f"剩余约 {usage.remaining_tokens} tokens）。"
        )
    if usage.threshold <= 0:
        return f"当前上下文使用率：未启用阈值统计（当前 {usage.message_count} 条消息，token 统计不可用）。"
    return f"当前上下文使用率：约 {usage.percent}%（{usage.message_count}/{usage.threshold} 条消息，token 统计不可用）。"


def format_usage_delta(before_usage, after_usage) -> str:
    """格式化压缩前后使用率变化。"""
    if before_usage.token_available and after_usage.token_available:
        return (
            f"token 使用率 {before_usage.percent}% -> {after_usage.percent}%"
            f"（{before_usage.used_tokens} -> {after_usage.used_tokens} tokens）"
        )
    return f"使用率 {before_usage.percent}% -> {after_usage.percent}%"
