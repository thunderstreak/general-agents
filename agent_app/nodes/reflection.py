"""工具结果反思节点。"""

import re
import time

from langchain_core.messages import HumanMessage, ToolCall, ToolMessage

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
WEB_SEARCH_MAX_ATTEMPTS = 3
WEB_SEARCH_NOISE_KEYWORDS = ("今日头条", "今日 热榜", "今日热榜", "热点 - 今日", "toutiao.com", "tophub.today")
WEB_SEARCH_DOMAIN_KEYWORDS = ("黄金", "金价", "现货", "伦敦金", "xau", "价格", "gold", "贵金属")
WEB_SEARCH_GENERIC_QUERY_TERMS = ("今日", "今天", "实时", "查询", "最新", "2026", "2025", "2024")


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

    structured_decision = _reflect_structured_tool_calls(latest_tool_calls, retry_count, attempted_tools, start_time)
    if structured_decision is not None and not _is_latest_web_search_success(latest_tool_calls):
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

    web_search_decision = _reflect_web_search_relevance(state, latest_tool_calls, latest_tool_messages, start_time)
    if web_search_decision is not None:
        return web_search_decision

    if max_steps and step_count >= max_steps:
        message = f"编排步骤已达到上限：{max_steps}"
        return _failed(start_time, message, stop_reason="max_steps_exceeded")

    if structured_decision is not None:
        return structured_decision

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


def _reflect_web_search_relevance(
    state: AgentState,
    latest_tool_calls: list[dict],
    latest_tool_messages: list[ToolMessage],
    start_time: float,
) -> dict | None:
    """判断 web_search 结果是否与用户问题相关。"""
    latest_call = _latest_web_search_call(latest_tool_calls)
    if not latest_call or not latest_call.get("success"):
        return None

    query = str((latest_call.get("tool_args") or {}).get("query") or "").strip()
    result_text = _latest_tool_text(state, latest_tool_messages, [latest_call])
    if _is_web_search_relevant(query, result_text):
        return None

    attempts = _web_search_attempt_count(state)
    user_text = _latest_human_text(state)
    reason = "web_search 返回结果与用户问题不匹配。"
    if attempts >= WEB_SEARCH_MAX_ATTEMPTS:
        return _response_reflection(
            start_time,
            status="insufficient",
            reason=f"已尝试搜索 {attempts} 次，但没有找到与问题匹配的可靠结果。",
            next_action="response",
            missing_info="相关搜索结果",
            attempted_tools=_attempted_tools(state, latest_tool_calls),
            stop_reason="web_search_irrelevant_limit",
        )

    next_attempt = attempts + 1
    refined_query = _build_refined_search_query(user_text, query, attempts)
    emit_progress(
        f"已搜索 {attempts} 次，但结果不匹配，正在调整关键词重试...",
        event="tool_retry",
        node="reflection",
        tool_name="web_search",
    )
    tool_call = ToolCall(name="web_search", args={"query": refined_query}, id=f"retry_web_search_{next_attempt}")
    return {
        "reflection": _reflection(
            status="retry",
            reason=reason,
            next_action="tools",
            retry_tool_name="web_search",
            retry_count=next_attempt - 1,
            attempted_tools=_attempted_tools(state, latest_tool_calls),
            loop_reason=f"搜索结果不匹配，调整关键词重试 web_search",
            stop_reason="web_search_irrelevant",
        ),
        "last_error": {},
        "last_tool_request": {"tool_calls": [tool_call]},
        "node_runs": [node_run("reflection", start_time)],
    }


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


def _latest_web_search_call(records: list[dict]) -> dict | None:
    """提取最近的 web_search 记录。"""
    for record in reversed(records):
        if isinstance(record, dict) and record.get("tool_name") == "web_search":
            return record
    return None


def _is_latest_web_search_success(records: list[dict]) -> bool:
    """判断最近工具记录是否是成功的 web_search。"""
    latest_record = records[-1] if records else {}
    return (
        isinstance(latest_record, dict)
        and latest_record.get("tool_name") == "web_search"
        and bool(latest_record.get("success"))
    )


def _web_search_attempt_count(state: AgentState) -> int:
    """统计本轮 web_search 调用次数。"""
    return sum(
        1
        for record in state.get("tool_calls", [])
        if isinstance(record, dict) and record.get("tool_name") == "web_search"
    )


def _latest_human_text(state: AgentState) -> str:
    """提取最近用户文本。"""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def _is_web_search_relevant(query: str, result_text: str) -> bool:
    """用本地启发式判断搜索结果是否匹配查询意图。"""
    if _is_blank_result(result_text):
        return False

    normalized_result = _normalize_text(result_text)
    if any(_normalize_text(keyword) in normalized_result for keyword in WEB_SEARCH_NOISE_KEYWORDS):
        if not any(_normalize_text(keyword) in normalized_result for keyword in WEB_SEARCH_DOMAIN_KEYWORDS):
            return False

    query_terms = _important_search_terms(query)
    if not query_terms:
        return True

    matched_terms = [term for term in query_terms if term in normalized_result]
    if any(term in normalized_result for term in _domain_terms_for_query(query_terms)):
        return True
    return len(matched_terms) >= min(2, len(query_terms))


def _important_search_terms(text: str) -> list[str]:
    """提取搜索相关性关键词。"""
    normalized = _normalize_text(text)
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized)
    useful_terms = []
    for term in terms:
        if term in WEB_SEARCH_GENERIC_QUERY_TERMS:
            continue
        if term.isdigit():
            continue
        useful_terms.append(term)
    return list(dict.fromkeys(useful_terms))


def _domain_terms_for_query(query_terms: list[str]) -> list[str]:
    """根据查询词推导领域关键词。"""
    gold_terms = {"黄金", "金价", "xau", "gold", "贵金属"}
    if any(gold_term in term for term in query_terms for gold_term in gold_terms):
        return [_normalize_text(term) for term in WEB_SEARCH_DOMAIN_KEYWORDS]
    return []


def _build_refined_search_query(user_text: str, query: str, attempts: int) -> str:
    """构造更具体的 web_search 查询词。"""
    base = " ".join(part for part in (user_text.strip(), query.strip()) if part)
    if not base:
        base = query.strip() or user_text.strip() or "用户问题相关信息"

    additions = ["权威", "实时", "价格"]
    if attempts >= 2:
        additions.extend(["黄金", "金价", "XAU"])
    refined = " ".join([base, *additions])
    return " ".join(dict.fromkeys(refined.split()))[:200]


def _normalize_text(text: str) -> str:
    """标准化文本用于关键词匹配。"""
    return re.sub(r"\s+", "", str(text or "").lower())


def _is_blank_result(text: str) -> bool:
    """判断工具结果是否为空。"""
    return not str(text or "").strip()
