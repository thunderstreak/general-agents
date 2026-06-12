"""工具结果反思节点。"""

import time

from agent_app.nodes.common import emit_progress, join_tool_errors, node_run
from agent_app.orchestrator import error_state
from agent_app.state import AgentState


def reflection_node(state: AgentState):
    """轻量核对工具结果，决定是否进入总结或错误响应。"""
    start_time = time.perf_counter()
    emit_progress("核对工具结果...", node="reflection")
    tool_errors = state.get("tool_errors", [])
    tool_calls = state.get("tool_calls", [])
    if tool_errors:
        message = join_tool_errors(tool_errors)
        return {
            "reflection": {"status": "failed", "reason": message, "next_action": "error"},
            "last_error": error_state(message, "reflection_error", "reflection"),
            "node_runs": [node_run("reflection", start_time, success=False, error=message)],
        }

    if not tool_calls:
        message = "没有可核对的工具结果。"
        return {
            "reflection": {"status": "failed", "reason": message, "next_action": "error"},
            "last_error": error_state(message, "reflection_error", "reflection"),
            "node_runs": [node_run("reflection", start_time, success=False, error=message)],
        }

    return {
        "reflection": {"status": "passed", "reason": "工具调用成功，进入结果总结。", "next_action": "agent"},
        "node_runs": [node_run("reflection", start_time)],
    }
