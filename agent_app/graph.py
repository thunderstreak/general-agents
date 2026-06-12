"""LangGraph 图编排。"""

import operator
import time
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent_app.config import ORCHESTRATOR_MAX_STEPS
from agent_app.llm import get_chat_model, invoke_with_fallback
from agent_app.memory import update_memory_from_turn, with_memory_context
from agent_app.orchestrator import (
    build_response,
    confirmation_state,
    error_state,
    new_trace_id,
    should_retrieve,
    success_node_run,
)
from agent_app.tool_selector import select_tool
from agent_app.tools import tool_metadata_by_name, tools, tools_by_name
from agent_app.tools.runtime import run_tool


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # LangGraph 会自动追加消息
    tool_selection: dict
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


llm = get_chat_model()
llm_with_tools = llm.bind_tools(tools)


def _latest_human_message(messages: list):
    """获取最近一条用户消息。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def _message_text(message) -> str:
    """提取消息中的文本。"""
    if message is None:
        return ""
    if isinstance(message.content, str):
        return message.content

    if isinstance(message.content, list):
        text_parts = []
        for part in message.content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "\n".join(text_parts)

    return str(message.content)


def _next_step_state(state: AgentState, node_name: str):
    """增加编排步骤计数，超过上限时返回错误状态。"""
    step_count = int(state.get("step_count", 0)) + 1
    max_steps = int(state["max_steps"]) if state.get("max_steps") is not None else ORCHESTRATOR_MAX_STEPS
    if step_count > max_steps:
        return {
            "step_count": step_count,
            "last_error": error_state(f"编排步骤超过上限：{max_steps}", "max_steps_exceeded", node_name),
        }
    return {"step_count": step_count}


def _node_run(node_name: str, start_time: float, success: bool = True, error: str = "") -> dict:
    """生成节点运行记录。"""
    if success:
        return success_node_run(node_name, start_time)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {"node_name": node_name, "success": False, "duration_ms": duration_ms, "error": error, "started_at": time.time()}


def retrieval_node(state: AgentState):
    """RAG 检索预留节点。"""
    start_time = time.perf_counter()
    trace_id = state.get("trace_id") or new_trace_id()
    latest_human_message = _latest_human_message(state["messages"])
    user_text = _message_text(latest_human_message)

    retrieval_results = []
    if should_retrieve(user_text):
        retrieval_results.append(
            {
                "source": "local_rag_placeholder",
                "content": "RAG 检索模块尚未接入，当前仅保留编排节点和结果结构。",
                "score": 0.0,
            }
        )

    return {
        "trace_id": trace_id,
        "retrieval_results": retrieval_results,
        "node_runs": [_node_run("retrieval", start_time)],
    }


def agent_node(state: AgentState):
    """调用模型，生成回复或工具调用。"""
    start_time = time.perf_counter()
    step_update = _next_step_state(state, "agent")
    if step_update.get("last_error"):
        return {**step_update, "node_runs": [_node_run("agent", start_time, success=False, error=step_update["last_error"]["message"])]}

    try:
        messages = state["messages"]
        if hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
            return {**step_update, "node_runs": [_node_run("agent", start_time)]}

        memory_state = state.get("long_term_memory", {})
        model_messages = _with_context(messages, memory_state, state.get("retrieval_results", []))

        if isinstance(messages[-1], ToolMessage):
            response = invoke_with_fallback(
                [
                    SystemMessage(
                        content=(
                            "你正在根据工具返回结果回复用户。"
                            "如果工具结果已经包含答案，必须优先使用工具结果，不要因为工具入参为空而要求用户重复提供信息。"
                            "如果工具结果明确失败，再说明失败原因并给出下一步建议。"
                        )
                    ),
                    *model_messages,
                ]
            )
        else:
            latest_human_message = _latest_human_message(messages)
            selection = select_tool(_message_text(latest_human_message)) if latest_human_message else None

            if selection and selection.action == "tool":
                response = _tool_selection_to_message(selection.tool_name, selection.args)
            elif selection and selection.action == "chat":
                response = invoke_with_fallback(model_messages)
            else:
                response = llm_with_tools.invoke(model_messages)

        state_update = {**step_update, "messages": [response], "node_runs": [_node_run("agent", start_time)]}
        if "selection" in locals() and selection:
            state_update["tool_selection"] = selection.to_dict()
        return state_update
    except Exception as exc:
        message = f"Agent 节点执行失败：{exc}"
        return {
            **step_update,
            "last_error": error_state(message, "agent_error", "agent"),
            "node_runs": [_node_run("agent", start_time, success=False, error=message)],
        }


def confirmation_node(state: AgentState):
    """处理需要人工确认的工具调用。"""
    start_time = time.perf_counter()
    last_msg = state["messages"][-1]
    tool_call = last_msg.tool_calls[0]
    pending = confirmation_state(tool_call["name"], tool_call["args"], tool_call["id"])
    message = AIMessage(content=f"{pending['message']} 请输入 yes 确认执行，或 no 取消。")
    return {
        "pending_confirmation": pending,
        "messages": [message],
        "node_runs": [_node_run("confirmation", start_time)],
    }


def tool_node(state: AgentState):
    """执行工具调用，返回 ToolMessage 列表。"""
    start_time = time.perf_counter()
    step_update = _next_step_state(state, "tools")
    if step_update.get("last_error"):
        return {**step_update, "node_runs": [_node_run("tools", start_time, success=False, error=step_update["last_error"]["message"])]}

    messages = state["messages"]
    last_msg = messages[-1]

    tool_messages = []
    tool_call_records = []
    tool_error_records = []
    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        print(f"🛠️ 调用工具: {tool_name}({tool_args})")
        tool_run = run_tool(tool_name, tool_args, tools_by_name, tool_metadata_by_name)
        tool_call_records.append(tool_run.to_dict())
        if not tool_run.success:
            tool_error_records.append(tool_run.to_dict())
        tool_messages.append(ToolMessage(content=tool_run.result, tool_call_id=tc["id"]))

    state_update = {
        **step_update,
        "messages": tool_messages,
        "tool_calls": tool_call_records,
        "tool_errors": tool_error_records,
        "node_runs": [_node_run("tools", start_time, success=not tool_error_records, error=_join_tool_errors(tool_error_records))],
    }
    if tool_error_records:
        state_update["last_error"] = error_state(_join_tool_errors(tool_error_records), "tool_error", "tools")
    return state_update


def memory_node(state: AgentState):
    """在最终回复后更新长期记忆。"""
    start_time = time.perf_counter()
    latest_human_message = _latest_human_message(state["messages"])
    last_message = state["messages"][-1]
    if not latest_human_message or not isinstance(last_message, AIMessage):
        return {"node_runs": [_node_run("memory", start_time)], "memory_updated": False}

    try:
        memory_state = update_memory_from_turn(state.get("long_term_memory", {}), latest_human_message, last_message)
    except Exception as exc:
        message = f"Memory 节点执行失败：{exc}"
        return {
            "last_error": error_state(message, "memory_error", "memory"),
            "node_runs": [_node_run("memory", start_time, success=False, error=message)],
            "memory_updated": False,
        }

    return {"long_term_memory": memory_state, "node_runs": [_node_run("memory", start_time)], "memory_updated": True}


def error_node(state: AgentState):
    """统一错误响应节点。"""
    start_time = time.perf_counter()
    last_error = state.get("last_error") or error_state("未知编排错误")
    message = AIMessage(content=f"执行失败：{last_error.get('message', '未知错误')}")
    return {"messages": [message], "node_runs": [_node_run("error", start_time)]}


def response_node(state: AgentState):
    """统一输出结构节点。"""
    start_time = time.perf_counter()
    response = build_response(state)
    return {"final_response": response, "node_runs": [_node_run("response", start_time)]}


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


def after_tool_router(state: AgentState) -> Literal["agent", "error"]:
    """工具执行后路由。"""
    if state.get("last_error"):
        return "error"
    return "agent"


def after_memory_router(state: AgentState) -> Literal["response", "error"]:
    """记忆写入后路由。"""
    if state.get("last_error"):
        return "error"
    return "response"


def _tool_selection_to_message(tool_name: str, tool_args: dict):
    """把工具选择结果转换为带 tool_calls 的 AIMessage。"""
    tool_call_id = f"selected_{tool_name}"
    tool_call = ToolCall(name=tool_name, args=tool_args, id=tool_call_id)
    return AIMessage(content="", tool_calls=[tool_call])


def _with_context(messages: list, memory_state: dict, retrieval_results: list):
    """给模型消息注入 memory 和 RAG 上下文。"""
    model_messages = with_memory_context(messages, memory_state)
    if not retrieval_results:
        return model_messages

    retrieval_text = "\n".join(
        f"- 来源：{item.get('source', 'unknown')}；内容：{item.get('content', '')}"
        for item in retrieval_results
        if isinstance(item, dict)
    )
    if not retrieval_text:
        return model_messages

    return [
        SystemMessage(content=f"[检索上下文]\n{retrieval_text}\n回答时如使用这些内容，请说明来源。"),
        *model_messages,
    ]


def _join_tool_errors(tool_error_records: list[dict]) -> str:
    """拼接工具错误信息。"""
    return "；".join(record.get("error") or record.get("result", "") for record in tool_error_records)


def build_graph():
    """构建并编译 LangGraph。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("confirm", confirmation_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("memory", memory_node)
    workflow.add_node("error", error_node)
    workflow.add_node("response", response_node)
    workflow.set_entry_point("retrieval")
    workflow.add_edge("retrieval", "agent")
    workflow.add_conditional_edges("agent", router, {"confirm": "confirm", "tools": "tools", "error": "error", "memory": "memory"})
    workflow.add_conditional_edges("tools", after_tool_router, {"agent": "agent", "error": "error"})
    workflow.add_conditional_edges("memory", after_memory_router, {"response": "response", "error": "error"})
    workflow.add_edge("confirm", "response")
    workflow.add_edge("error", "response")
    workflow.add_edge("response", END)
    return workflow.compile()


app = build_graph()
