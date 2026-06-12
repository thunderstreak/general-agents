"""LangGraph 图编排。"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent_app.config import BASE_URL, MODEL_NAME, OPENAI_API_KEY
from agent_app.intent import classify_intent
from agent_app.tools import get_location, get_weather, web_search, tools, tools_by_name


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # LangGraph 会自动追加消息


llm = ChatOpenAI(model=MODEL_NAME, base_url=BASE_URL, openai_api_key=OPENAI_API_KEY)
llm_with_tools = llm.bind_tools(tools)
llm_with_location = llm.bind_tools([get_location], tool_choice="get_location")
llm_with_weather = llm.bind_tools([get_weather], tool_choice="get_weather")
llm_with_web_search = llm.bind_tools([web_search], tool_choice="web_search")


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
        response = llm.invoke(messages)
    else:
        latest_human_message = _latest_human_message(messages)
        intent_decision = classify_intent(latest_human_message.content) if latest_human_message else None

        if intent_decision and intent_decision.intent == "location":
            response = llm_with_location.invoke(messages)
        elif intent_decision and intent_decision.intent == "weather":
            response = llm_with_weather.invoke(messages)
        elif intent_decision and intent_decision.intent == "web_search":
            response = llm_with_web_search.invoke(messages)
        elif intent_decision and intent_decision.intent == "chat":
            response = llm.invoke(messages)
        else:
            response = llm_with_tools.invoke(messages)

    return {"messages": [response]}


def tool_node(state: AgentState):
    """执行工具调用，返回 ToolMessage 列表。"""
    messages = state["messages"]
    last_msg = messages[-1]

    tool_messages = []
    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        print(f"🛠️ 调用工具: {tool_name}({tool_args})")
        result = tools_by_name[tool_name].invoke(tool_args)
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
