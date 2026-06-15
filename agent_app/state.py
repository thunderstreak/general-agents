"""Agent state 定义与初始化。"""

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from agent_app.config import ORCHESTRATOR_MAX_STEPS
from agent_app.memory import load_memory, memory_to_state
from agent_app.orchestrator import new_trace_id


class AgentState(TypedDict):
    """LangGraph 运行状态。"""

    messages: Annotated[list, add_messages]  # LangGraph 会自动追加消息
    tool_selection: dict
    plan: dict
    reflection: dict
    last_tool_request: dict
    attempted_tools: list
    tool_calls: Annotated[list, operator.add]
    tool_errors: Annotated[list, operator.add]
    retrieval_results: Annotated[list, operator.add]
    user_profile: dict
    long_term_memory: dict
    step_count: int
    max_steps: int
    last_error: dict
    pending_confirmation: dict
    approved_tool_call_ids: list
    final_response: dict
    trace_id: str
    node_runs: Annotated[list, operator.add]
    memory_updated: bool


def create_initial_state(**overrides: Any) -> dict[str, Any]:
    """创建完整 Agent state 初始值。"""
    memory = load_memory()
    state: dict[str, Any] = {
        "messages": [],
        "tool_selection": {},
        "plan": {},
        "reflection": {},
        "last_tool_request": {},
        "attempted_tools": [],
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
        "long_term_memory": memory_to_state(memory),
        "step_count": 0,
        "max_steps": ORCHESTRATOR_MAX_STEPS,
        "last_error": {},
        "pending_confirmation": {},
        "approved_tool_call_ids": [],
        "final_response": {},
        "trace_id": "",
        "node_runs": [],
        "memory_updated": False,
    }
    state.update(overrides)
    return state


def reset_turn_state(state: dict[str, Any]) -> dict[str, Any]:
    """重置单轮编排状态，保留历史消息和长期记忆。"""
    state["step_count"] = 0
    state["max_steps"] = ORCHESTRATOR_MAX_STEPS
    state["last_error"] = {}
    state["plan"] = {}
    state["reflection"] = {}
    state["last_tool_request"] = {}
    state["attempted_tools"] = []
    state["tool_calls"] = []
    state["tool_errors"] = []
    state["retrieval_results"] = []
    state["final_response"] = {}
    state["trace_id"] = new_trace_id()
    state["node_runs"] = []
    state["memory_updated"] = False
    state["approved_tool_call_ids"] = state.get("approved_tool_call_ids", [])
    return state


def ensure_state_defaults(state: dict[str, Any]) -> dict[str, Any]:
    """补齐旧会话或损坏会话缺失的 state 字段。"""
    defaults = create_initial_state()
    defaults.update(state)
    defaults["messages"] = state.get("messages", [])
    defaults["long_term_memory"] = state.get("long_term_memory") or defaults["long_term_memory"]
    return defaults
