"""工具确认节点。"""

import time

from langchain_core.messages import AIMessage, ToolCall

from agent_app.nodes.common import emit_progress, node_run
from agent_app.orchestrator import confirmation_state
from agent_app.state import AgentState


def confirmation_node(state: AgentState):
    """处理需要人工确认的工具调用。"""
    start_time = time.perf_counter()
    emit_progress("等待人工确认...", node="confirmation")
    last_msg = state["messages"][-1]
    tool_call = last_msg.tool_calls[0]
    pending = confirmation_state(tool_call["name"], tool_call["args"], tool_call["id"])
    message = AIMessage(content=f"{pending['message']} 请输入 yes 确认执行，或 no 取消。")
    return {
        "pending_confirmation": pending,
        "messages": [message],
        "node_runs": [node_run("confirmation", start_time)],
    }


def resume_confirmed_tool(state: AgentState, approved: bool) -> dict:
    """根据用户确认结果恢复或取消待确认工具。"""
    pending = state.get("pending_confirmation") or {}
    if not pending:
        return state

    next_state = {**state, "pending_confirmation": {}}
    if not approved:
        next_state["messages"].append(AIMessage(content=f"已取消执行工具：{pending.get('tool_name', '')}。"))
        return next_state

    tool_call = ToolCall(name=pending["tool_name"], args=pending.get("tool_args", {}), id=pending["tool_call_id"])
    approved_tool_call_ids = list(next_state.get("approved_tool_call_ids", []))
    approved_tool_call_ids.append(pending["tool_call_id"])
    next_state["approved_tool_call_ids"] = approved_tool_call_ids
    next_state["messages"].append(AIMessage(content="", tool_calls=[tool_call]))
    return next_state
