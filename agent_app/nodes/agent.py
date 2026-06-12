"""Agent 生成节点。"""

import time

from langchain_core.messages import AIMessage, SystemMessage, ToolCall, ToolMessage

from agent_app.llm import get_chat_model, invoke_with_fallback
from agent_app.memory import with_memory_context
from agent_app.nodes.common import emit_progress, next_step_state, node_run
from agent_app.nodes.planning import current_plan_step
from agent_app.orchestrator import error_state
from agent_app.state import AgentState
from agent_app.tools import tools, tools_by_name


_chat_llm = None
_llm_with_tools = None


def agent_node(state: AgentState):
    """调用模型，生成回复或工具调用。"""
    start_time = time.perf_counter()
    step_update = next_step_state(state, "agent")
    if step_update.get("last_error"):
        return {**step_update, "node_runs": [node_run("agent", start_time, success=False, error=step_update["last_error"]["message"])]}

    try:
        messages = state["messages"]
        if hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
            return {**step_update, "node_runs": [node_run("agent", start_time)]}

        memory_state = state.get("long_term_memory", {})
        model_messages = with_context(messages, memory_state, state.get("retrieval_results", []))

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
            step = current_plan_step(state.get("plan") or {})
            action = step.get("action", "auto")

            if action == "tool" and step.get("tool_name"):
                response = tool_selection_to_message(step["tool_name"], step.get("args") or {})
            elif action == "tool_agent":
                emit_progress("需要外部信息，准备调用工具...", node="agent")
                response = invoke_tool_agent(model_messages, state.get("plan") or {})
            elif action == "chat":
                response = invoke_with_fallback(model_messages)
            else:
                response = get_llm_with_tools().invoke(model_messages)

        state_update = {**step_update, "messages": [response], "node_runs": [node_run("agent", start_time)]}
        if getattr(response, "tool_calls", None):
            state_update["last_tool_request"] = {"tool_calls": response.tool_calls}
        return state_update
    except Exception as exc:
        message = f"Agent 节点执行失败：{exc}"
        return {
            **step_update,
            "last_error": error_state(message, "agent_error", "agent"),
            "node_runs": [node_run("agent", start_time, success=False, error=message)],
        }


def tool_selection_to_message(tool_name: str, tool_args: dict):
    """把工具选择结果转换为带 tool_calls 的 AIMessage。"""
    tool_call_id = f"selected_{tool_name}"
    tool_call = ToolCall(name=tool_name, args=tool_args, id=tool_call_id)
    return AIMessage(content="", tool_calls=[tool_call])


def invoke_tool_agent(model_messages: list, plan: dict):
    """调用绑定候选工具的模型，候选为空时回退到全量工具。"""
    candidate_names = plan.get("candidate_tool_names") if isinstance(plan, dict) else []
    candidate_tools = [tools_by_name[name] for name in candidate_names if name in tools_by_name] if isinstance(candidate_names, list) else []
    if not candidate_tools:
        return get_llm_with_tools().invoke(model_messages)
    return get_chat_llm().bind_tools(candidate_tools).invoke(model_messages)


def get_chat_llm():
    """延迟获取主聊天模型，避免导入节点时初始化模型。"""
    global _chat_llm
    if _chat_llm is None:
        _chat_llm = get_chat_model()
    return _chat_llm


def get_llm_with_tools():
    """延迟获取绑定全量工具的模型。"""
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm_with_tools = get_chat_llm().bind_tools(tools)
    return _llm_with_tools


def with_context(messages: list, memory_state: dict, retrieval_results: list):
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
