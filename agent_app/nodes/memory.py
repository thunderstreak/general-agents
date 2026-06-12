"""长期记忆节点。"""

import time

from langchain_core.messages import AIMessage

from agent_app.memory import update_memory_from_turn
from agent_app.nodes.common import emit_progress, latest_human_message, node_run
from agent_app.orchestrator import error_state
from agent_app.state import AgentState


def memory_node(state: AgentState):
    """在最终回复后更新长期记忆。"""
    start_time = time.perf_counter()
    emit_progress("更新记忆...", node="memory")
    latest_message = latest_human_message(state["messages"])
    last_message = state["messages"][-1]
    if not latest_message or not isinstance(last_message, AIMessage):
        return {"node_runs": [node_run("memory", start_time)], "memory_updated": False}

    try:
        memory_state = update_memory_from_turn(state.get("long_term_memory", {}), latest_message, last_message)
    except Exception as exc:
        message = f"Memory 节点执行失败：{exc}"
        return {
            "last_error": error_state(message, "memory_error", "memory"),
            "node_runs": [node_run("memory", start_time, success=False, error=message)],
            "memory_updated": False,
        }

    return {"long_term_memory": memory_state, "node_runs": [node_run("memory", start_time)], "memory_updated": True}
