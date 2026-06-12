"""LangGraph 图编排。"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent_app.config import BASE_URL, MODEL_NAME, OPENAI_API_KEY
from agent_app.tool_selector import select_tool
from agent_app.tools import tool_metadata_by_name, tools, tools_by_name
from agent_app.tools.runtime import run_tool


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # LangGraph 会自动追加消息


llm = ChatOpenAI(model=MODEL_NAME, base_url=BASE_URL, openai_api_key=OPENAI_API_KEY)
llm_with_tools = llm.bind_tools(tools)


def _latest_human_message(messages: list):
    """获取最近一条用户消息。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def agent_node(state: AgentState):
    """调用模型，生成回复或工具调用。"""
    messages = state["messages"]

    if isinstance(messages[-1], ToolMessage):
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你正在根据工具返回结果回复用户。"
                        "如果工具结果已经包含答案，必须优先使用工具结果，不要因为工具入参为空而要求用户重复提供信息。"
                        "如果工具结果明确失败，再说明失败原因并给出下一步建议。"
                    )
                ),
                *messages,
            ]
        )
    else:
        latest_human_message = _latest_human_message(messages)
        selection = select_tool(latest_human_message.content) if latest_human_message else None

        if selection and selection.action == "tool":
            response = _tool_selection_to_message(selection.tool_name, selection.args)
        elif selection and selection.action == "chat":
            response = llm.invoke(messages)
        else:
            response = llm_with_tools.invoke(messages)

    return {"messages": [response]}


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
    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        print(f"🛠️ 调用工具: {tool_name}({tool_args})")
        result = run_tool(tool_name, tool_args, tools_by_name, tool_metadata_by_name)
        tool_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    return {"messages": tool_messages}


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
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "__end__": END})
    workflow.add_edge("tools", "agent")
    return workflow.compile()


app = build_graph()
