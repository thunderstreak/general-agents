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
    response = build_response(state)
    return {"final_response": response, "node_runs": [node_run("response", start_time)]}
