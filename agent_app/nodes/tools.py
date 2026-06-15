"""工具执行节点。"""

import time

from langchain_core.messages import ToolMessage

from agent_app.nodes.common import emit_progress, join_tool_errors, next_step_state, node_run
from agent_app.state import AgentState
from agent_app.tools import tool_metadata_by_name, tools_by_name
from agent_app.tools.runtime import run_tool


def tool_node(state: AgentState):
    """执行工具调用，返回 ToolMessage 列表。"""
    start_time = time.perf_counter()
    step_update = next_step_state(state, "tools")
    if step_update.get("last_error"):
        return {**step_update, "node_runs": [node_run("tools", start_time, success=False, error=step_update["last_error"]["message"])]}

    messages = state["messages"]
    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if not tool_calls and (state.get("reflection") or {}).get("next_action") == "tools":
        tool_calls = (state.get("last_tool_request") or {}).get("tool_calls", [])

    tool_messages = []
    tool_call_records = []
    tool_error_records = []
    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        emit_progress(f"调用工具 {tool_name}...", event="tool_started", node="tools", tool_name=tool_name)
        tool_run = run_tool(tool_name, tool_args, tools_by_name, tool_metadata_by_name)
        tool_call_records.append(tool_run.to_dict())
        if not tool_run.success:
            tool_error_records.append(tool_run.to_dict())
            emit_progress(f"工具 {tool_name} 调用失败。", event="tool_failed", node="tools", tool_name=tool_name)
        else:
            emit_progress(f"工具 {tool_name} 调用完成。", event="tool_succeeded", node="tools", tool_name=tool_name)
        tool_messages.append(ToolMessage(content=tool_run.result, tool_call_id=tc["id"]))

    state_update = {
        **step_update,
        "messages": tool_messages,
        "tool_calls": tool_call_records,
        "tool_errors": tool_error_records,
        "attempted_tools": _merge_attempted_tools(state, [record["tool_name"] for record in tool_call_records]),
        "node_runs": [node_run("tools", start_time, success=not tool_error_records, error=join_tool_errors(tool_error_records))],
    }
    return state_update


def _merge_attempted_tools(state: AgentState, tool_names: list[str]) -> list[str]:
    """合并本轮已尝试工具。"""
    names = [name for name in state.get("attempted_tools", []) if isinstance(name, str) and name]
    names.extend(name for name in tool_names if isinstance(name, str) and name)
    return list(dict.fromkeys(names))
