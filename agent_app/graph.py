"""LangGraph 图编排入口。"""

from typing import Literal

from langgraph.graph import END, StateGraph

from agent_app.nodes import (
    _emit_progress,
    _get_chat_llm,
    _get_llm_with_tools,
    _invoke_tool_agent,
    agent_node,
    confirmation_node,
    error_node,
    memory_node,
    planning_node,
    reflection_node,
    response_node,
    resume_confirmed_tool,
    retrieval_node,
    tool_node,
)
from agent_app.state import AgentState
from agent_app.tools import tool_metadata_by_name


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


def after_reflection_router(state: AgentState) -> Literal["agent", "error"]:
    """反思核对后路由。"""
    if state.get("last_error"):
        return "error"
    return "agent"


def after_memory_router(state: AgentState) -> Literal["response", "error"]:
    """记忆写入后路由。"""
    if state.get("last_error"):
        return "error"
    return "response"


def build_graph():
    """构建并编译 LangGraph。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("confirm", confirmation_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("reflection", reflection_node)
    workflow.add_node("memory", memory_node)
    workflow.add_node("error", error_node)
    workflow.add_node("response", response_node)
    workflow.set_entry_point("retrieval")
    workflow.add_edge("retrieval", "planning")
    workflow.add_edge("planning", "agent")
    workflow.add_conditional_edges("agent", router, {"confirm": "confirm", "tools": "tools", "error": "error", "memory": "memory"})
    workflow.add_conditional_edges("tools", after_tool_router, {"reflection": "reflection", "error": "error"})
    workflow.add_conditional_edges("reflection", after_reflection_router, {"agent": "agent", "error": "error"})
    workflow.add_conditional_edges("memory", after_memory_router, {"response": "response", "error": "error"})
    workflow.add_edge("confirm", "response")
    workflow.add_edge("error", "response")
    workflow.add_edge("response", END)
    return workflow.compile()


app = build_graph()
