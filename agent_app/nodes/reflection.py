"""工具结果反思节点。"""

import time

from langchain_core.messages import ToolMessage

from agent_app.nodes.common import emit_progress, join_tool_errors, node_run
from agent_app.orchestrator import error_state
from agent_app.state import AgentState
from agent_app.tools.runtime import (
    ERROR_MISSING_PARAMETER,
    ERROR_TEMPORARY,
    RESULT_ASK_USER,
    RESULT_FAILED,
    RESULT_INSUFFICIENT,
    RESULT_OK,
)


RETRY_LIMIT = 1


def reflection_node(state: AgentState):
    """轻量核对工具结果，决定是否进入总结或错误响应。"""
    start_time = time.perf_counter()
    emit_progress("核对工具结果...", node="reflection")
    latest_tool_messages = _latest_tool_messages(state)
    latest_tool_calls = _latest_tool_calls(state, len(latest_tool_messages))
    latest_tool_errors = [record for record in latest_tool_calls if isinstance(record, dict) and not record.get("success")]
    attempted_tools = _attempted_tools(state, latest_tool_calls)
    retry_count = int((state.get("reflection") or {}).get("retry_count", 0))
    max_steps = int(state.get("max_steps", 0) or 0)
    step_count = int(state.get("step_count", 0) or 0)

    if max_steps and step_count >= max_steps:
        message = f"编排步骤已达到上限：{max_steps}"
        return _failed(start_time, message, stop_reason="max_steps_exceeded")

    structured_decision = _reflect_structured_tool_calls(latest_tool_calls, retry_count, attempted_tools, start_time)
    if structured_decision is not None:
        return structured_decision

    if latest_tool_errors:
        return _reflect_tool_errors(latest_tool_errors, retry_count, attempted_tools, start_time)

    if not latest_tool_calls:
        message = "没有可核对的工具结果。"
        return _failed(start_time, message, stop_reason="no_tool_calls")

    result_text = _latest_tool_text(state, latest_tool_messages, latest_tool_calls)
    if _is_blank_result(result_text):
        return _response_reflection(
            start_time,
            status="insufficient",
            reason="工具调用成功，但没有返回有效内容。",
            next_action="response",
            missing_info="有效工具结果",
            attempted_tools=attempted_tools,
            stop_reason="empty_tool_result",
        )

    return {
        "reflection": _reflection(
            status="passed",
            reason="工具调用成功，进入结果总结。",
            next_action="agent",
            retry_count=retry_count,
            attempted_tools=attempted_tools,
        ),
        "node_runs": [node_run("reflection", start_time)],
    }


def _reflect_tool_errors(tool_errors: list[dict], retry_count: int, attempted_tools: list[str], start_time: float) -> dict:
    """根据工具错误判断是否重试、追问或失败。"""
    message = join_tool_errors(tool_errors)
    return _failed(start_time, message, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason="tool_error")


def _reflect_structured_tool_calls(tool_calls: list[dict], retry_count: int, attempted_tools: list[str], start_time: float) -> dict | None:
    """优先基于结构化 ToolRunRecord 字段做反思决策。"""
    if not tool_calls or not _has_structured_fields(tool_calls):
        return None

    blocking_call = _first_non_ok_tool_call(tool_calls)
    if blocking_call is None:
        return {
            "reflection": _reflection(
                status="passed",
                reason="工具调用成功，进入结果总结。",
                next_action="agent",
                retry_count=retry_count,
                attempted_tools=attempted_tools,
            ),
            "node_runs": [node_run("reflection", start_time)],
        }

    tool_name = str(blocking_call.get("tool_name") or "")
    reason = str(blocking_call.get("error") or blocking_call.get("result") or "工具结果不足。")
    result_status = str(blocking_call.get("result_status") or RESULT_FAILED)
    error_type = str(blocking_call.get("error_type") or "")
    missing_info = str(blocking_call.get("missing_info") or "")
    fallback_tool_name = _first_available_fallback(blocking_call, attempted_tools)

    if result_status == RESULT_ASK_USER or error_type == ERROR_MISSING_PARAMETER:
        return _response_reflection(
            start_time,
            status="ask_user",
            reason=reason,
            next_action="response",
            missing_info=missing_info or "必要参数",
            retry_count=retry_count,
            attempted_tools=attempted_tools,
        )

    if bool(blocking_call.get("is_retryable")) or error_type == ERROR_TEMPORARY:
        if retry_count < RETRY_LIMIT:
            return _retry(start_time, reason, tool_name, retry_count, attempted_tools)
        if fallback_tool_name:
            return _fallback_to_planning(start_time, reason, fallback_tool_name, attempted_tools, "retry_limit_exceeded")
        return _failed(start_time, reason, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason="retry_limit_exceeded")

    if result_status == RESULT_INSUFFICIENT:
        if fallback_tool_name:
            return _fallback_to_planning(start_time, reason, fallback_tool_name, attempted_tools, "insufficient_tool_result")
        return _response_reflection(
            start_time,
            status="insufficient",
            reason=reason,
            next_action="response",
            missing_info=missing_info or "可用工具结果",
            retry_count=retry_count,
            attempted_tools=attempted_tools,
            stop_reason="insufficient_tool_result",
        )

    if result_status == RESULT_FAILED:
        if fallback_tool_name:
            return _fallback_to_planning(start_time, reason, fallback_tool_name, attempted_tools, "tool_error")
        return _failed(start_time, reason, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason=error_type or "tool_error")

    return None


def _has_structured_fields(tool_calls: list[dict]) -> bool:
    """判断工具记录是否包含结构化语义字段。"""
    return any("result_status" in call or "error_type" in call or "is_retryable" in call for call in tool_calls if isinstance(call, dict))


def _first_non_ok_tool_call(tool_calls: list[dict]) -> dict | None:
    """找到第一条非 ok 工具记录。"""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        result_status = call.get("result_status")
        if result_status and result_status != RESULT_OK:
            return call
        if not result_status and call.get("success") is False:
            return call
    return None


def _first_available_fallback(tool_call: dict, attempted_tools: list[str]) -> str:
    """读取第一项尚未尝试的 fallback 工具。"""
    fallback_tool_names = tool_call.get("fallback_tool_names") or []
    if not isinstance(fallback_tool_names, list):
        return ""
    for name in fallback_tool_names:
        if isinstance(name, str) and name and name not in attempted_tools:
            return name
    return ""


def _retry(start_time: float, reason: str, tool_name: str, retry_count: int, attempted_tools: list[str]) -> dict:
    """生成重试决策。"""
    next_retry_count = retry_count + 1
    return {
        "reflection": _reflection(
            status="retry",
            reason=reason,
            next_action="tools",
            retry_tool_name=tool_name,
            retry_count=next_retry_count,
            attempted_tools=attempted_tools,
            loop_reason=f"临时错误，重试工具 {tool_name}",
        ),
        "last_error": {},
        "node_runs": [node_run("reflection", start_time)],
    }


def _fallback_to_planning(start_time: float, reason: str, fallback_tool_name: str, attempted_tools: list[str], stop_reason: str = "") -> dict:
    """生成切换工具并回到 planning 的决策。"""
    return {
        "reflection": _reflection(
            status="insufficient",
            reason=reason,
            next_action="planning",
            fallback_tool_name=fallback_tool_name,
            attempted_tools=attempted_tools,
            loop_reason=f"当前工具结果不足，切换到 {fallback_tool_name}",
            stop_reason=stop_reason,
        ),
        "last_error": {},
        "node_runs": [node_run("reflection", start_time)],
    }


def _failed(start_time: float, reason: str, retry_count: int = 0, attempted_tools: list[str] | None = None, stop_reason: str = "") -> dict:
    """生成不可恢复失败决策。"""
    return {
        "reflection": _reflection(
            status="failed",
            reason=reason,
            next_action="error",
            retry_count=retry_count,
            attempted_tools=attempted_tools or [],
            stop_reason=stop_reason,
        ),
        "last_error": error_state(reason, "reflection_error", "reflection"),
        "node_runs": [node_run("reflection", start_time, success=False, error=reason)],
    }


def _response_reflection(
    start_time: float,
    status: str,
    reason: str,
    next_action: str,
    missing_info: str = "",
    retry_count: int = 0,
    attempted_tools: list[str] | None = None,
    stop_reason: str = "",
) -> dict:
    """生成进入 response 的反思决策。"""
    return {
        "reflection": _reflection(
            status=status,
            reason=reason,
            next_action=next_action,
            missing_info=missing_info,
            retry_count=retry_count,
            attempted_tools=attempted_tools or [],
            stop_reason=stop_reason,
        ),
        "last_error": {},
        "node_runs": [node_run("reflection", start_time)],
    }


def _reflection(
    status: str,
    reason: str,
    next_action: str,
    missing_info: str = "",
    retry_tool_name: str = "",
    fallback_tool_name: str = "",
    retry_count: int = 0,
    attempted_tools: list[str] | None = None,
    loop_reason: str = "",
    stop_reason: str = "",
) -> dict:
    """构造统一 reflection 结构。"""
    return {
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "missing_info": missing_info,
        "retry_tool_name": retry_tool_name,
        "fallback_tool_name": fallback_tool_name,
        "retry_count": retry_count,
        "attempted_tools": attempted_tools or [],
        "loop_reason": loop_reason,
        "stop_reason": stop_reason,
    }


def _attempted_tools(state: AgentState, latest_tool_calls: list[dict]) -> list[str]:
    """合并本轮已尝试工具，保持顺序并去重。"""
    names = []
    for name in state.get("attempted_tools", []):
        if isinstance(name, str) and name:
            names.append(name)
    for record in latest_tool_calls:
        if isinstance(record, dict) and record.get("tool_name"):
            names.append(str(record["tool_name"]))
    return list(dict.fromkeys(names))


def _latest_tool_messages(state: AgentState) -> list[ToolMessage]:
    """提取最近一批连续工具消息。"""
    messages = state.get("messages", [])
    latest_messages = []
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        latest_messages.append(message)
    return list(reversed(latest_messages))


def _latest_tool_calls(state: AgentState, message_count: int) -> list[dict]:
    """根据最近工具消息数量提取对应工具记录。"""
    tool_calls = [record for record in state.get("tool_calls", []) if isinstance(record, dict)]
    if not tool_calls:
        return []
    if message_count <= 0:
        return tool_calls[-1:]
    return tool_calls[-message_count:]


def _latest_tool_text(state: AgentState, latest_messages: list[ToolMessage], latest_tool_calls: list[dict]) -> str:
    """提取最近工具消息文本。"""
    if latest_messages:
        return "\n".join(str(message.content or "").strip() for message in latest_messages).strip()
    for record in reversed(latest_tool_calls):
        if isinstance(record, dict):
            return str(record.get("result") or record.get("error") or "").strip()
    return ""


def _latest_tool_name(records: list[dict]) -> str:
    """提取最近工具名。"""
    for record in reversed(records):
        if isinstance(record, dict) and record.get("tool_name"):
            return str(record["tool_name"])
    return ""


def _is_blank_result(text: str) -> bool:
    """判断工具结果是否为空。"""
    return not str(text or "").strip()
