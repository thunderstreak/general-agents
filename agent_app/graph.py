"""LangGraph 图编排。"""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent_app.llm import get_chat_model, invoke_with_fallback
from agent_app.memory import update_memory_from_turn, with_memory_context
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


llm = get_chat_model()
llm_with_tools = llm.bind_tools(tools)


def _latest_human_message(messages: list):
    """获取最近一条用户消息。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def _message_text(message: HumanMessage) -> str:
    """提取 HumanMessage 中可供工具选择器使用的文本。"""
    if isinstance(message.content, str):
        return message.content

    if isinstance(message.content, list):
        text_parts = []
        for part in message.content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "\n".join(text_parts)

    return str(message.content)


def agent_node(state: AgentState):
    """调用模型，生成回复或工具调用。"""
    messages = state["messages"]
    memory_state = state.get("long_term_memory", {})

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
                *with_memory_context(messages, memory_state),
            ]
        )
    else:
        latest_human_message = _latest_human_message(messages)
        selection = select_tool(_message_text(latest_human_message)) if latest_human_message else None

        if selection and selection.action == "tool":
            response = _tool_selection_to_message(selection.tool_name, selection.args)
        elif selection and selection.action == "chat":
            response = invoke_with_fallback(with_memory_context(messages, memory_state))
        else:
            response = llm_with_tools.invoke(with_memory_context(messages, memory_state))

    state_update = {"messages": [response]}
    if "selection" in locals() and selection:
        state_update["tool_selection"] = selection.to_dict()

    return state_update


def memory_node(state: AgentState):
    """在最终回复后更新长期记忆。"""
    latest_human_message = _latest_human_message(state["messages"])
    last_message = state["messages"][-1]
    if not latest_human_message or not isinstance(last_message, AIMessage):
        return {}

    memory_state = update_memory_from_turn(state.get("long_term_memory", {}), latest_human_message, last_message)
    return {"long_term_memory": memory_state}


def _tool_selection_to_message(tool_name: str, tool_args: dict):
    """把工具选择结果转换为带 tool_calls 的 AIMessage。"""
    tool_call_id = f"selected_{tool_name}"
    tool_call = ToolCall(name=tool_name, args=tool_args, id=tool_call_id)
    return AIMessage(content="", tool_calls=[tool_call])


def tool_node(state: AgentState):
    """执行工具调用，返回 ToolMessage 列表。"""
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

    return {"messages": tool_messages, "tool_calls": tool_call_records, "tool_errors": tool_error_records}


def router(state: AgentState) -> Literal["tools", "__end__"]:
    """根据最后一条消息是否有 tool_calls 决定下一步。"""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "__end__"


def build_graph():
    """构建并编译 LangGraph。"""
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("memory", memory_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "__end__": "memory"})
    workflow.add_edge("tools", "agent")
    workflow.add_edge("memory", END)
    return workflow.compile()


app = build_graph()
