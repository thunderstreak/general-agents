"""LangGraph 图编排入口。"""

from typing import Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agent_app.nodes import (
    agent_node,
    aggregate_evidence_node,
    analyst_node,
    confirmation_node,
    critic_node,
    error_node,
    memory_node,
    perception_node,
    planning_node,
    reflection_node,
    response_node,
    resume_confirmed_tool,
    retrieval_node,
    subagent_worker_node,
    supervisor_node,
    tool_node,
    writer_node,
)
from agent_app.orchestrator import should_retrieve
from agent_app.state import AgentState
from agent_app.tools import tool_metadata_by_name

_app = None


def router(state: AgentState) -> Literal["confirm", "tools", "error", "memory"]:
    """根据最后一条消息决定下一步。"""
    if state.get("last_error"):
        return "error"

    last_msg = state["messages"][-1]
    approved_tool_call_ids = set(state.get("approved_tool_call_ids", []))
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tool_call in last_msg.tool_calls:
            metadata = tool_metadata_by_name.get(tool_call["name"])
            if metadata and metadata.requires_confirmation and tool_call["id"] not in approved_tool_call_ids:
                return "confirm"
        return "tools"
    return "memory"


def after_tool_router(state: AgentState) -> Literal["reflection", "error"]:
    """工具执行后路由。"""
    if state.get("last_error", {}).get("type") == "max_steps_exceeded":
        return "error"
    return "reflection"


def after_reflection_router(state: AgentState) -> Literal["agent", "tools", "planning", "response", "error"]:
    """反思核对后路由。"""
    if state.get("last_error"):
        return "error"
    reflection = state.get("reflection") or {}
    next_action = reflection.get("next_action") or "agent"
    if next_action in {"agent", "tools", "planning", "response", "error"}:
        return next_action
    return "agent"


def after_planning_router(state: AgentState) -> Literal["retrieval", "supervisor", "agent"]:
    """规划后按任务模式分流。"""
    plan = state.get("plan") or {}
    if should_retrieve_after_planning(state):
        return "retrieval"
    if plan.get("mode") == "collaboration":
        return "supervisor"
    return "agent"


def after_retrieval_router(state: AgentState) -> Literal["supervisor", "agent"]:
    """检索后按既定 plan 继续执行。"""
    plan = state.get("plan") or {}
    if plan.get("mode") == "collaboration":
        return "supervisor"
    return "agent"


def should_retrieve_after_planning(state: AgentState) -> bool:
    """根据 plan 判断是否需要执行 RAG 检索。"""
    plan = state.get("plan") or {}
    if plan.get("mode") not in {"chat", "collaboration"}:
        return False
    input_context = state.get("input_context") or {}
    user_text = str(input_context.get("normalized_text") or "")
    return bool(input_context.get("should_retrieve") or should_retrieve(user_text))


def dispatch_subagent_tasks(state: AgentState) -> list[Send]:
    """使用 Send 并行分发 sub-agent map 任务。"""
    tasks = state.get("subagent_tasks") or []
    sends = []
    for task in tasks:
        if isinstance(task, dict):
            sends.append(Send("subagent_worker", {**state, "active_subagent_task": task}))
    return sends


def after_critic_router(state: AgentState) -> Literal["writer", "memory", "error"]:
    """critic 后决定是否修订或结束。"""
    if state.get("last_error"):
        return "error"
    critic = (state.get("collaboration_summary") or {}).get("critic") or {}
    if critic.get("status") == "revise":
        return "writer"
    return "memory"


def after_memory_router(state: AgentState) -> Literal["response", "error"]:
    """记忆写入后路由。"""
    if state.get("last_error"):
        return "error"
    return "response"


def build_graph():
    """构建并编译 LangGraph。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("perception", perception_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("subagent_worker", subagent_worker_node)
    workflow.add_node("aggregate_evidence", aggregate_evidence_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("writer", writer_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("confirm", confirmation_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("reflection", reflection_node)
    workflow.add_node("memory", memory_node)
    workflow.add_node("error", error_node)
    workflow.add_node("response", response_node)
    workflow.set_entry_point("perception")
    workflow.add_edge("perception", "planning")
    workflow.add_conditional_edges("planning", after_planning_router, {"retrieval": "retrieval", "supervisor": "supervisor", "agent": "agent"})
    workflow.add_conditional_edges("retrieval", after_retrieval_router, {"supervisor": "supervisor", "agent": "agent"})
    workflow.add_conditional_edges("supervisor", dispatch_subagent_tasks)
    workflow.add_edge("subagent_worker", "aggregate_evidence")
    workflow.add_edge("aggregate_evidence", "analyst")
    workflow.add_edge("analyst", "writer")
    workflow.add_edge("writer", "critic")
    workflow.add_conditional_edges("critic", after_critic_router, {"writer": "writer", "memory": "memory", "error": "error"})
    workflow.add_conditional_edges("agent", router, {"confirm": "confirm", "tools": "tools", "error": "error", "memory": "memory"})
    workflow.add_conditional_edges("tools", after_tool_router, {"reflection": "reflection", "error": "error"})
    workflow.add_conditional_edges(
        "reflection",
        after_reflection_router,
        {"agent": "agent", "tools": "tools", "planning": "planning", "response": "response", "error": "error"},
    )
    workflow.add_conditional_edges("memory", after_memory_router, {"response": "response", "error": "error"})
    workflow.add_edge("confirm", "response")
    workflow.add_edge("error", "response")
    workflow.add_edge("response", END)
    return workflow.compile()


def get_app():
    """获取缓存后的 LangGraph 应用。"""
    global _app
    if _app is None:
        _app = build_graph()
    return _app
