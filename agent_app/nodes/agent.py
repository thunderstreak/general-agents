"""Agent 生成节点。"""

import re
import time
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolCall, ToolMessage

from agent_app.cancel import raise_if_cancelled
from agent_app.context_compaction import build_summary_context
from agent_app.llm import get_chat_model, invoke_with_fallback
from agent_app.memory import with_memory_context
from agent_app.nodes.common import emit_progress, merge_attempted_tools, next_step_state, node_run
from agent_app.nodes.planning import current_plan_step
from agent_app.orchestrator import error_state
from agent_app.rag import KnowledgeBaseError, list_documents
from agent_app.state import AgentState
from agent_app.tools import tools, tools_by_name
from agent_app.utils.messages import message_text
from agent_app.utils.pseudo_tools import parse_pseudo_tool_calls as _parse_pseudo_tool_calls
from agent_app.utils.pseudo_tools import sanitize_pseudo_tool_content


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
        model_messages = with_context(messages, memory_state, state.get("retrieval_results", []), state.get("conversation_summary", ""))

        action = ""
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
                raw_model_response = response
                response = fallback_tool_agent_response(response, state)
            elif action == "clarification":
                response = clarification_to_message(state.get("plan") or {})
            elif action == "rag_list":
                response = rag_list_to_message()
            elif action == "chat":
                response = invoke_with_fallback(model_messages)
            else:
                response = get_llm_with_tools().invoke(model_messages)

        model_outputs = []
        if _is_model_response(action, is_tool_summary):
            model_outputs.append(model_output_record("agent", _response_purpose(action, is_tool_summary), locals().get("raw_model_response", response), attempt=1))

        if not is_tool_summary:
            response = normalize_pseudo_tool_call_response(response)
        response, ensure_outputs = ensure_visible_response(response, state, action, is_tool_summary)
        model_outputs.extend(ensure_outputs)
        state_update = {**step_update, "messages": [response], "node_runs": [node_run("agent", start_time)]}
        if model_outputs:
            state_update["model_outputs"] = model_outputs
        if getattr(response, "tool_calls", None):
            state_update["last_tool_request"] = {"tool_calls": response.tool_calls}
            state_update["attempted_tools"] = merge_attempted_tools(state, [tool_call["name"] for tool_call in response.tool_calls])
        if action == "clarification":
            state_update["clarification"] = clarification_state(state.get("plan") or {}, response.content)
        return state_update
    except Exception as exc:
        message = f"Agent 节点执行失败：{exc}"
        return {
            **step_update,
            "last_error": error_state(message, "agent_error", "agent"),
            "node_runs": [node_run("agent", start_time, success=False, error=message)],
        }


def ensure_visible_response(response, state: AgentState, action: str = "", is_tool_summary: bool = False):
    """确保非工具调用响应有可展示内容。"""
    model_outputs = []
    if getattr(response, "tool_calls", None):
        return response, model_outputs
    content = visible_response_text(getattr(response, "content", ""))
    if content:
        return response, model_outputs

    retry_response = retry_empty_response(state, action, is_tool_summary)
    model_outputs.append(model_output_record("agent", f"{_response_purpose(action, is_tool_summary)}_retry", retry_response, attempt=2, retry_count=1))
    retry_response = normalize_pseudo_tool_call_response(retry_response)
    if getattr(retry_response, "tool_calls", None):
        return retry_response, model_outputs
    retry_content = visible_response_text(getattr(retry_response, "content", ""))
    if retry_content:
        return retry_response, model_outputs

    fallback = AIMessage(content=empty_response_fallback_text(state, action, is_tool_summary))
    model_outputs.append(
        {
            "node": "agent",
            "purpose": f"{_response_purpose(action, is_tool_summary)}_fallback",
            "attempt": 3,
            "retry_count": 1,
            "raw_content": "",
            "visible_content": fallback.content,
            "tool_calls": [],
            "error": "模型连续返回空可见内容，使用本地兜底回答。",
        }
    )
    return fallback, model_outputs


def model_output_record(node: str, purpose: str, response, attempt: int, retry_count: int = 0) -> dict[str, Any]:
    """构造模型输出调试记录。"""
    raw_content = getattr(response, "content", "")
    tool_calls = getattr(response, "tool_calls", []) or []
    return {
        "node": node,
        "purpose": purpose,
        "attempt": attempt,
        "retry_count": retry_count,
        "raw_content": stringify_model_content(raw_content),
        "visible_content": visible_response_text(raw_content),
        "tool_calls": _safe_tool_call_names(tool_calls),
        "error": "",
    }


def stringify_model_content(content: Any) -> str:
    """把模型 content 转成可记录文本。"""
    if isinstance(content, str):
        return content
    return str(content or "")


def _safe_tool_call_names(tool_calls: list) -> list[str]:
    """提取 tool_call 名称用于日志。"""
    names = []
    for call in tool_calls:
        if isinstance(call, dict):
            name = call.get("name") or call.get("tool_name") or ""
        else:
            name = getattr(call, "name", "")
        if name:
            names.append(str(name))
    return names


def _is_model_response(action: str, is_tool_summary: bool) -> bool:
    """判断当前响应是否来自模型。"""
    return is_tool_summary or action in {"chat", "tool_agent", "auto", ""}


def _response_purpose(action: str, is_tool_summary: bool) -> str:
    """生成模型输出用途标签。"""
    if is_tool_summary:
        return "tool_summary"
    if action == "tool_agent":
        return "tool_agent"
    if action == "chat":
        return "chat"
    return action or "auto"


def visible_response_text(content: Any) -> str:
    """提取最终可展示文本。"""
    return sanitize_pseudo_tool_content(content).strip()


def retry_empty_response(state: AgentState, action: str, is_tool_summary: bool):
    """模型空回答时用明确指令重试一次。"""
    if is_tool_summary:
        prompt = "上一次根据工具结果生成回答时返回了空内容。请用中文总结工具结果；若结果不足，请说明缺少什么。"
    elif state.get("retrieval_results"):
        prompt = (
            "上一次回答为空，且知识库检索已经完成。"
            "请只能基于[检索上下文]直接用中文回答用户问题；"
            "禁止输出任何工具调用、XML、JSON、<tool_call> 或 <function=...> 片段。"
            "如果检索内容不足，请先总结已检索到的相关信息，再说明缺少什么。"
        )
    elif action == "tool_agent":
        prompt = "上一次工具模式没有生成工具调用，也没有生成可展示回答。请直接用中文回答，或说明需要补充哪些信息。"
    else:
        prompt = "上一次回答为空。请直接用中文回答用户问题；如果问题不明确，请提出一个具体澄清问题。"

    try:
        return invoke_with_fallback(
            [
                SystemMessage(content=prompt),
                *with_context(state["messages"], state.get("long_term_memory", {}), state.get("retrieval_results", []), state.get("conversation_summary", "")),
            ]
        )
    except Exception:
        return AIMessage(content="")


def empty_response_fallback_text(state: AgentState, action: str, is_tool_summary: bool) -> str:
    """生成模型连续空回答时的兜底文本。"""
    user_text = _latest_user_text(state)
    if is_tool_summary:
        return "工具已经返回结果，但模型没有生成总结。请打开 debug 查看工具结果，或换个更具体的问题再试。"
    if state.get("retrieval_results"):
        return retrieval_fallback_text(state.get("retrieval_results", []))
    if action == "tool_agent":
        return "我没能生成有效的工具调用或回答。请补充更具体的目标、对象或上下文后再试。"
    if user_text:
        return f"我这次没有生成有效回答。请把“{user_text}”再具体一点，比如补充目标环境、版本或你希望我给出的步骤。"
    return "我这次没有生成有效回答。请换个更具体的说法再试。"


def retrieval_fallback_text(retrieval_results: list) -> str:
    """根据检索结果生成可见兜底回答。"""
    snippets = []
    for item in retrieval_results[:3]:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content", "")).split())
        if not content:
            continue
        source = item.get("title") or item.get("source") or "知识库"
        snippets.append(f"- 来源：{source}\n  内容：{content[:500]}")

    if not snippets:
        return "知识库检索已完成，但没有可用于回答的文本片段。请检查导入文档是否包含相关内容。"

    return (
        "知识库检索已完成，但模型连续输出了无效工具调用。"
        "我先把检索到的相关内容整理如下：\n"
        + "\n".join(snippets)
        + "\n\n请根据这些片段继续追问具体环境或版本，我可以再整理成安装步骤。"
    )


def tool_selection_to_message(tool_name: str, tool_args: dict):
    """把工具选择结果转换为带 tool_calls 的 AIMessage。"""
    tool_call_id = f"selected_{tool_name}"
    tool_call = ToolCall(name=tool_name, args=tool_args, id=tool_call_id)
    return AIMessage(content="", tool_calls=[tool_call])


def clarification_to_message(plan: dict) -> AIMessage:
    """把 clarification plan 转换为追问消息。"""
    question = str(plan.get("clarification_question") or "").strip()
    if not question:
        question = "我还需要你补充更多信息后才能继续。"
    return AIMessage(content=question)


def clarification_state(plan: dict, question: str) -> dict:
    """构造 clarification state。"""
    return {
        "question": question,
        "missing_info": plan.get("missing_info", ""),
        "reason": plan.get("clarification_reason", ""),
    }


def rag_list_to_message() -> AIMessage:
    """把知识库文档列表转换为回答消息。"""
    try:
        documents = list_documents()
    except KnowledgeBaseError as exc:
        return AIMessage(content=f"读取知识库失败：{exc}")
    if not documents:
        return AIMessage(content="知识库暂无文档。")

    lines = [f"知识库当前共有 {len(documents)} 个文档："]
    for item in documents:
        document_id = item.get("document_id", "未知 ID")
        title = item.get("title") or item.get("source") or document_id
        chunk_count = item.get("chunk_count", 0)
        path = item.get("path") or item.get("source") or ""
        lines.append(f"- {document_id} | {title} | {chunk_count} 个片段 | {path}")
    return AIMessage(content="\n".join(lines))


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
    return _parse_pseudo_tool_calls(content, tools_by_name)


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


def with_context(messages: list, memory_state: dict, retrieval_results: list, conversation_summary: str = ""):
    """给模型消息注入 memory 和 RAG 上下文。"""
    model_messages = with_memory_context(messages, memory_state)
    summary_message = build_summary_context(conversation_summary)
    if summary_message is not None:
        model_messages = [summary_message, *model_messages]
    if not retrieval_results:
        return model_messages

    retrieval_text = retrieval_context_text(retrieval_results)
    if not retrieval_text:
        return model_messages

    return [
        SystemMessage(
            content=(
                "[检索上下文]\n"
                f"{retrieval_text}\n"
                "知识库检索已经完成，你现在必须基于这些片段直接回答用户。"
                "禁止输出任何工具调用、XML、JSON、<tool_call> 或 <function=...> 片段。"
                "系统不存在 search_knowledge_base 工具。"
                "如使用这些内容，请说明来源；如果内容不足，请说明缺少的信息。"
            )
        ),
        *model_messages,
    ]


def retrieval_context_text(retrieval_results: list) -> str:
    """生成检索上下文文本。"""
    return "\n".join(
        f"- 来源：{item.get('source', 'unknown')}；内容：{item.get('content', '')}"
        for item in retrieval_results
        if isinstance(item, dict)
    )
