"""Agent 生成节点。"""

import re
import time
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolCall, ToolMessage

from agent_app.cli_cancel import raise_if_cancelled
from agent_app.llm import get_chat_model, invoke_with_fallback
from agent_app.memory import with_memory_context
from agent_app.nodes.common import emit_progress, merge_attempted_tools, next_step_state, node_run
from agent_app.nodes.planning import current_plan_step
from agent_app.orchestrator import error_state
from agent_app.state import AgentState
from agent_app.tools import tools, tools_by_name
from agent_app.utils.messages import message_text


_chat_llm = None
_llm_with_tools = None
PSEUDO_TOOL_CALL_PATTERN = re.compile(r"<tool_call\b[^>]*>.*?</tool_call>", re.IGNORECASE | re.DOTALL)
PSEUDO_FUNCTION_PATTERN = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.IGNORECASE | re.DOTALL)
PSEUDO_PARAMETER_PATTERN = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.IGNORECASE | re.DOTALL)


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

        is_tool_summary = isinstance(messages[-1], ToolMessage)
        if is_tool_summary:
            emit_progress("正在整理工具结果...", event="summary_started", node="agent")
            response = invoke_with_fallback(
                [
                    SystemMessage(
                        content=(
                            "你正在根据工具返回结果回复用户。"
                            "如果工具结果已经包含答案，必须优先使用工具结果，不要因为工具入参为空而要求用户重复提供信息。"
                            "如果工具结果明确失败，再说明失败原因并给出下一步建议。"
                            "禁止输出 XML、JSON 或 Markdown 形式的工具调用片段，例如 <tool_call>、<function=...>。"
                            "如果还需要更多实时信息，只能用自然语言说明当前工具结果的限制。"
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
                response = invoke_tool_agent(model_messages, state.get("plan") or {}, tags=["nostream"])
                response = fallback_tool_agent_response(response, state)
            elif action == "chat":
                response = invoke_with_fallback(model_messages)
            else:
                response = get_llm_with_tools().invoke(model_messages)

        if not is_tool_summary:
            response = normalize_pseudo_tool_call_response(response)
        state_update = {**step_update, "messages": [response], "node_runs": [node_run("agent", start_time)]}
        if getattr(response, "tool_calls", None):
            state_update["last_tool_request"] = {"tool_calls": response.tool_calls}
            state_update["attempted_tools"] = merge_attempted_tools(state, [tool_call["name"] for tool_call in response.tool_calls])
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


def invoke_tool_agent(model_messages: list, plan: dict, tags: list[str] | None = None):
    """调用绑定候选工具的模型，候选为空时回退到全量工具。"""
    candidate_names = plan.get("candidate_tool_names") if isinstance(plan, dict) else []
    candidate_tools = [tools_by_name[name] for name in candidate_names if name in tools_by_name] if isinstance(candidate_names, list) else []
    if not candidate_tools:
        model = get_llm_with_tools()
    else:
        model = get_chat_llm().bind_tools(candidate_tools)
    if tags:
        model = _with_tags(model, tags)
    raise_if_cancelled()
    response = model.invoke(model_messages)
    raise_if_cancelled()
    return response


def fallback_tool_agent_response(response, state: AgentState):
    """工具模式下模型未调用工具时，生成确定性兜底工具调用。"""
    if getattr(response, "tool_calls", None):
        return response
    pseudo_tool_calls = parse_pseudo_tool_calls(getattr(response, "content", ""))
    if pseudo_tool_calls:
        return AIMessage(content="", tool_calls=pseudo_tool_calls)

    tool_call = fallback_tool_call(state)
    if tool_call:
        return AIMessage(content="", tool_calls=[tool_call])
    return response


def fallback_tool_call(state: AgentState) -> ToolCall | None:
    """根据 plan 候选工具生成安全兜底调用。"""
    plan = state.get("plan") or {}
    candidate_names = plan.get("candidate_tool_names") if isinstance(plan, dict) else []
    if not isinstance(candidate_names, list):
        candidate_names = []
    user_text = _latest_user_text(state)

    if "web_search" in candidate_names:
        return ToolCall(name="web_search", args={"query": user_text}, id="fallback_web_search")
    if "fetch_url" in candidate_names:
        url = _first_url(user_text)
        if url:
            return ToolCall(name="fetch_url", args={"url": url}, id="fallback_fetch_url")
    return None


def normalize_pseudo_tool_call_response(response):
    """把模型误吐的伪工具调用转换为真正的 tool_calls。"""
    if getattr(response, "tool_calls", None):
        return response

    content = getattr(response, "content", "")
    tool_calls = parse_pseudo_tool_calls(content)
    if not tool_calls:
        return response

    return AIMessage(content="", tool_calls=tool_calls)


def parse_pseudo_tool_calls(content: Any) -> list[ToolCall]:
    """从伪 XML 工具调用文本中解析 tool_calls。"""
    text = _message_content_text(content)
    if not text:
        return []

    calls = []
    for block_match in PSEUDO_TOOL_CALL_PATTERN.finditer(text):
        block = block_match.group(0)
        for function_match in PSEUDO_FUNCTION_PATTERN.finditer(block):
            tool_name = function_match.group(1).strip()
            if tool_name not in tools_by_name:
                continue
            tool_args = _parse_pseudo_tool_args(tool_name, function_match.group(2))
            calls.append(ToolCall(name=tool_name, args=tool_args, id=f"pseudo_{tool_name}_{len(calls) + 1}"))
    return calls


def _latest_user_text(state: AgentState) -> str:
    """获取最近用户输入文本。"""
    input_context = state.get("input_context") or {}
    if input_context.get("normalized_text"):
        return str(input_context["normalized_text"])
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", "") == "human":
            return message_text(message)
    return ""


def _first_url(text: str) -> str:
    """提取文本中的第一个 URL。"""
    match = re.search(r"https?://[^\s，。)）]+", text)
    return match.group(0) if match else ""


def _parse_pseudo_tool_args(tool_name: str, body: str) -> dict[str, Any]:
    """解析并按工具 schema 过滤参数。"""
    allowed_args = set((getattr(tools_by_name[tool_name], "args", None) or {}).keys())
    args: dict[str, Any] = {}
    for match in PSEUDO_PARAMETER_PATTERN.finditer(body):
        name = match.group(1).strip()
        if allowed_args and name not in allowed_args:
            continue
        args[name] = match.group(2).strip()
    return args


def _message_content_text(content: Any) -> str:
    """将消息 content 转成纯文本。"""
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
    return str(content or "")


def _with_tags(model, tags: list[str]):
    """为支持配置的模型附加 stream 标签。"""
    if hasattr(model, "with_config"):
        return model.with_config(tags=tags)
    return model


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
