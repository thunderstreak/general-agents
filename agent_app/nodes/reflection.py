"""工具结果反思节点。"""

import time

from langchain_core.messages import ToolMessage

from agent_app.nodes.common import emit_progress, join_tool_errors, node_run
from agent_app.orchestrator import error_state
from agent_app.state import AgentState


RETRY_LIMIT = 1
TEMPORARY_ERROR_KEYWORDS = (
    "timeout",
    "timed out",
    "超时",
    "temporarily",
    "temporary",
    "connection",
    "网络",
    "502",
    "503",
    "504",
    "5xx",
)
PARAMETER_ERROR_KEYWORDS = (
    "没有提供城市",
    "请提供城市",
    "缺少 hostname",
    "缺少 url",
    "缺少 URL",
    "请提供",
    "missing",
    "required",
)
NON_RETRYABLE_ERROR_KEYWORDS = (
    "仅支持 http:// 或 https://",
    "禁止访问 localhost",
    "内网地址",
    "metadata 地址",
    "工具未注册",
    "不在白名单",
    "需要人工确认",
    "api key",
    "API key",
    "权限",
    "permission",
    "forbidden",
    "unauthorized",
)
INSUFFICIENT_RESULT_KEYWORDS = (
    "未提取到正文文本",
    "不支持正文抓取",
    "无搜索结果",
    "没有搜索结果",
    "未找到",
    "结果为空",
    "empty result",
    "no results",
)


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

    if latest_tool_errors:
        return _reflect_tool_errors(latest_tool_errors, retry_count, attempted_tools, start_time)

    if not latest_tool_calls:
        message = "没有可核对的工具结果。"
        return _failed(start_time, message, stop_reason="no_tool_calls")

    result_text = _latest_tool_text(state, latest_tool_messages, latest_tool_calls)
    if _is_blank_result(result_text):
        fallback_tool_name = _fallback_tool_for_insufficient(_latest_tool_name(latest_tool_calls), attempted_tools)
        if fallback_tool_name:
            return _fallback_to_planning(
                start_time,
                reason="工具调用成功，但没有返回有效内容。",
                fallback_tool_name=fallback_tool_name,
                attempted_tools=attempted_tools,
                stop_reason="empty_tool_result",
            )
        return _response_reflection(
            start_time,
            status="insufficient",
            reason="工具调用成功，但没有返回有效内容。",
            next_action="response",
            missing_info="有效工具结果",
            attempted_tools=attempted_tools,
            stop_reason="empty_tool_result",
        )

    if _contains_any(result_text, PARAMETER_ERROR_KEYWORDS):
        return _response_reflection(
            start_time,
            status="ask_user",
            reason=result_text,
            next_action="response",
            missing_info=_missing_info_from_text(result_text),
            attempted_tools=attempted_tools,
        )

    if _contains_any(result_text, INSUFFICIENT_RESULT_KEYWORDS):
        fallback_tool_name = _fallback_tool_for_insufficient(_latest_tool_name(latest_tool_calls), attempted_tools)
        if fallback_tool_name:
            return _fallback_to_planning(
                start_time,
                reason=result_text,
                fallback_tool_name=fallback_tool_name,
                attempted_tools=attempted_tools,
                stop_reason="insufficient_tool_result",
            )
        return _response_reflection(
            start_time,
            status="insufficient",
            reason=result_text,
            next_action="response",
            missing_info="可用工具结果",
            attempted_tools=attempted_tools,
            stop_reason="insufficient_tool_result",
        )

    if _looks_like_tool_failure(result_text):
        if _contains_any(result_text, PARAMETER_ERROR_KEYWORDS):
            return _response_reflection(
                start_time,
                status="ask_user",
                reason=result_text,
                next_action="response",
                missing_info=_missing_info_from_text(result_text),
                attempted_tools=attempted_tools,
            )
        if _contains_any(result_text, TEMPORARY_ERROR_KEYWORDS) and retry_count < RETRY_LIMIT:
            return _retry(start_time, result_text, _latest_tool_name(latest_tool_calls), retry_count, attempted_tools)
        fallback_tool_name = _fallback_tool_for_error(_latest_tool_name(latest_tool_calls), attempted_tools)
        if fallback_tool_name:
            return _fallback_to_planning(start_time, result_text, fallback_tool_name, attempted_tools, "tool_result_failure")
        return _failed(start_time, result_text, attempted_tools=attempted_tools, stop_reason="tool_result_failure")

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
    tool_name = _latest_tool_name(tool_errors)

    if _contains_any(message, PARAMETER_ERROR_KEYWORDS):
        return _response_reflection(
            start_time,
            status="ask_user",
            reason=message,
            next_action="response",
            missing_info=_missing_info_from_text(message),
            retry_count=retry_count,
            attempted_tools=attempted_tools,
        )

    if _contains_any(message, NON_RETRYABLE_ERROR_KEYWORDS):
        return _failed(start_time, message, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason="non_retryable_tool_error")

    if _contains_any(message, TEMPORARY_ERROR_KEYWORDS):
        if retry_count < RETRY_LIMIT:
            return _retry(start_time, message, tool_name, retry_count, attempted_tools)
        fallback_tool_name = _fallback_tool_for_error(tool_name, attempted_tools)
        if fallback_tool_name:
            return _fallback_to_planning(start_time, message, fallback_tool_name, attempted_tools, "retry_limit_exceeded")
        return _failed(start_time, message, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason="retry_limit_exceeded")

    fallback_tool_name = _fallback_tool_for_error(tool_name, attempted_tools)
    if fallback_tool_name:
        return _fallback_to_planning(start_time, message, fallback_tool_name, attempted_tools, "tool_error")
    return _failed(start_time, message, retry_count=retry_count, attempted_tools=attempted_tools, stop_reason="tool_error")


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


def _fallback_tool_for_error(tool_name: str, attempted_tools: list[str]) -> str:
    """根据失败工具选择 fallback 工具。"""
    if tool_name == "fetch_url" and "web_search" not in attempted_tools:
        return "web_search"
    return ""


def _fallback_tool_for_insufficient(tool_name: str, attempted_tools: list[str]) -> str:
    """根据不足结果选择 fallback 工具。"""
    if tool_name == "fetch_url" and "web_search" not in attempted_tools:
        return "web_search"
    return ""


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


def _looks_like_tool_failure(text: str) -> bool:
    """判断成功记录中的文本是否实际表达失败。"""
    lowered = str(text or "").lower()
    return "失败" in lowered or "error" in lowered or "failed" in lowered


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """判断文本是否包含任一关键词。"""
    lowered = str(text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _missing_info_from_text(text: str) -> str:
    """根据错误文本推断缺失信息。"""
    lowered = str(text or "").lower()
    if "城市" in lowered:
        return "城市"
    if "url" in lowered or "hostname" in lowered or "链接" in lowered:
        return "URL"
    if "query" in lowered or "查询" in lowered or "搜索" in lowered:
        return "查询词"
    return "必要参数"
