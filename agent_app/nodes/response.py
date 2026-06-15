"""响应与错误节点。"""

import time

from langchain_core.messages import AIMessage

from agent_app.nodes.common import emit_progress, node_run
from agent_app.orchestrator import error_state
from agent_app.output import build_response
from agent_app.state import AgentState


def error_node(state: AgentState):
    """统一错误响应节点。"""
    start_time = time.perf_counter()
    emit_progress("生成错误响应...", node="error")
    last_error = state.get("last_error") or error_state("未知编排错误")
    message = AIMessage(content=f"执行失败：{last_error.get('message', '未知错误')}")
    return {"messages": [message], "node_runs": [node_run("error", start_time)]}


def response_node(state: AgentState):
    """统一输出结构节点。"""
    start_time = time.perf_counter()
    emit_progress("整理响应...", node="response")
    reflection = state.get("reflection") or {}
    if reflection.get("next_action") == "response" and reflection.get("status") in {"ask_user", "insufficient"}:
        message = AIMessage(content=_reflection_response_text(reflection))
        response_state = {**state, "messages": [message], "last_error": {}, "tool_errors": []}
        return {
            "messages": [message],
            "final_response": build_response(response_state),
            "node_runs": [node_run("response", start_time)],
        }
    response = build_response(state)
    return {"final_response": response, "node_runs": [node_run("response", start_time)]}


def _reflection_response_text(reflection: dict) -> str:
    """把反思决策转换为面向用户的追问或说明。"""
    status = reflection.get("status")
    missing_info = reflection.get("missing_info") or "必要信息"
    reason = reflection.get("reason") or ""
    if status == "ask_user":
        return f"我还需要你补充{missing_info}后才能继续。"
    if status == "insufficient":
        if missing_info in {"必要信息", "可靠信息", "可用工具结果", "有效工具结果", "相关搜索结果"}:
            return "我这次没有获取到足够可靠的信息。你可以补充更具体的范围或关键词，我再帮你查。"
        if missing_info:
            return f"我这次没有获取到足够可靠的{missing_info}。你可以补充更具体的范围或关键词，我再帮你查。"
        return "我这次没有获取到足够可靠的信息。你可以补充更具体的范围或关键词，我再帮你查。"
    return reason or "暂时无法完成这次请求。"
