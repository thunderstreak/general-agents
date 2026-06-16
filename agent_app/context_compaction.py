"""会话上下文压缩。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_app.config import (
    CHAT_MODEL_NAME,
    CONTEXT_COMPACT_KEEP_TURNS,
    CONTEXT_COMPACT_SUMMARY_MAX_CHARS,
    CONTEXT_COMPACT_TOKEN_THRESHOLD_PERCENT,
    CONTEXT_RESERVED_OUTPUT_TOKENS,
    CONTEXT_TOKENIZER_MODEL,
    CONTEXT_WINDOW_TOKENS,
)
from agent_app.llm import invoke_with_fallback
from agent_app.utils.messages import message_text


Summarizer = Callable[[list[Any], str, int], str]


@dataclass
class CompactResult:
    """上下文压缩结果。"""

    state: dict[str, Any]
    archived_messages: list[Any]
    summary: str
    kept_messages: list[Any]


@dataclass
class ContextUsage:
    """上下文使用量估算。"""

    mode: str
    message_count: int
    threshold: int
    percent: int
    token_available: bool = False
    used_tokens: int = 0
    context_window_tokens: int = 0
    reserved_output_tokens: int = 0
    available_input_tokens: int = 0
    remaining_tokens: int = 0


def compact_state(
    state: dict[str, Any],
    keep_turns: int = CONTEXT_COMPACT_KEEP_TURNS,
    max_summary_chars: int = CONTEXT_COMPACT_SUMMARY_MAX_CHARS,
    summarizer: Summarizer | None = None,
) -> CompactResult:
    """压缩 state 中的短期消息上下文。"""
    messages = list(state.get("messages", []))
    kept_messages = _recent_turn_messages(messages, keep_turns)
    archive_count = max(0, len(messages) - len(kept_messages))
    archived_messages = messages[:archive_count]
    if not archived_messages:
        return CompactResult(state=state, archived_messages=[], summary=str(state.get("conversation_summary") or ""), kept_messages=kept_messages)

    previous_summary = str(state.get("conversation_summary") or "")
    summary = _summarize_messages(archived_messages, previous_summary, max_summary_chars, summarizer)
    next_state = dict(state)
    next_state["messages"] = kept_messages
    next_state["conversation_summary"] = summary
    next_state["compact_count"] = int(state.get("compact_count", 0) or 0) + 1
    next_state["last_compacted_at"] = datetime.now().isoformat(timespec="seconds")
    return CompactResult(state=next_state, archived_messages=archived_messages, summary=summary, kept_messages=kept_messages)


def should_auto_compact(state: dict[str, Any], threshold: int) -> bool:
    """判断是否需要自动压缩。"""
    messages = state.get("messages", [])
    if isinstance(messages, list) and threshold > 0 and len(messages) >= threshold:
        return True
    usage = estimate_context_usage(state, threshold)
    return (
        usage.token_available
        and CONTEXT_COMPACT_TOKEN_THRESHOLD_PERCENT > 0
        and usage.percent >= CONTEXT_COMPACT_TOKEN_THRESHOLD_PERCENT
    )


def estimate_context_usage(
    state: dict[str, Any],
    threshold: int,
    *,
    context_window_tokens: int = CONTEXT_WINDOW_TOKENS,
    reserved_output_tokens: int = CONTEXT_RESERVED_OUTPUT_TOKENS,
    tokenizer_model: str | None = None,
) -> ContextUsage:
    """估算当前上下文使用量，优先使用 token 统计。"""
    messages = state.get("messages", [])
    message_count = len(messages) if isinstance(messages, list) else 0
    try:
        used_tokens = _estimate_tokens(state, tokenizer_model)
    except Exception:
        return _message_usage(message_count, threshold)

    context_window_tokens = max(0, int(context_window_tokens or 0))
    reserved_output_tokens = max(0, int(reserved_output_tokens or 0))
    available_input_tokens = max(1, context_window_tokens - reserved_output_tokens)
    remaining_tokens = max(0, available_input_tokens - used_tokens)
    percent = round(used_tokens / available_input_tokens * 100)
    return ContextUsage(
        mode="token",
        message_count=message_count,
        threshold=threshold,
        percent=percent,
        token_available=True,
        used_tokens=used_tokens,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        available_input_tokens=available_input_tokens,
        remaining_tokens=remaining_tokens,
    )


def build_summary_context(summary: str) -> SystemMessage | None:
    """构造会话摘要上下文消息。"""
    text = str(summary or "").strip()
    if not text:
        return None
    return SystemMessage(
        content=(
            "[会话摘要]\n"
            "下面是本会话被压缩的历史信息。回答时应把它当作之前对话上下文使用，但不要逐字复述。\n"
            f"{text}"
        )
    )


def _message_usage(message_count: int, threshold: int) -> ContextUsage:
    """生成消息数兜底使用量。"""
    percent = 0 if threshold <= 0 else round(message_count / threshold * 100)
    return ContextUsage(mode="message", message_count=message_count, threshold=threshold, percent=percent)


def _estimate_tokens(state: dict[str, Any], tokenizer_model: str | None = None) -> int:
    """估算发送给模型的上下文 token 数。"""
    encoder = _token_encoder(tokenizer_model)
    parts = []
    summary_message = build_summary_context(str(state.get("conversation_summary") or ""))
    if summary_message is not None:
        parts.append(_message_for_token_count(summary_message))
    memory_text = _memory_context_text(state.get("long_term_memory"))
    if memory_text:
        parts.append(memory_text)
    retrieval_text = _retrieval_context_text(state.get("retrieval_results"))
    if retrieval_text:
        parts.append(retrieval_text)
    for message in state.get("messages", []):
        parts.append(_message_for_token_count(message))
    text = "\n".join(part for part in parts if part)
    return len(encoder.encode(text))


def _token_encoder(tokenizer_model: str | None = None):
    """获取 token encoder。"""
    import tiktoken

    model_name = (tokenizer_model or CONTEXT_TOKENIZER_MODEL or CHAT_MODEL_NAME or "").strip()
    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            pass
    return tiktoken.get_encoding("cl100k_base")


def _message_for_token_count(message: Any) -> str:
    """将消息转换为可估算 token 的文本。"""
    role = _message_role_label(message)
    parts = [f"{role}：{message_text(message)}"]
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append(f"tool_calls：{_json_for_token_count(tool_calls)}")
    message_type = getattr(message, "type", "")
    if message_type == "tool":
        tool_call_id = getattr(message, "tool_call_id", "")
        if tool_call_id:
            parts.append(f"tool_call_id：{tool_call_id}")
    return "\n".join(part for part in parts if part)


def _memory_context_text(memory_state: Any) -> str:
    """生成长期记忆 token 估算文本。"""
    if not isinstance(memory_state, dict) or not memory_state:
        return ""
    parts = []
    summary = str(memory_state.get("summary") or "").strip()
    if summary:
        parts.append(f"历史摘要：{summary}")
    items = memory_state.get("items")
    if isinstance(items, list):
        item_lines = []
        for item in items:
            if isinstance(item, dict):
                content = str(item.get("content") or "").strip()
            else:
                content = str(item or "").strip()
            if content:
                item_lines.append(f"- {content}")
        if item_lines:
            parts.append("长期记忆：\n" + "\n".join(item_lines))
    return "\n".join(parts)


def _retrieval_context_text(retrieval_results: Any) -> str:
    """生成 RAG 检索上下文 token 估算文本。"""
    if not isinstance(retrieval_results, list) or not retrieval_results:
        return ""
    lines = []
    for item in retrieval_results:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "unknown")
        content = item.get("content", "")
        lines.append(f"- 来源：{source}；内容：{content}")
    if not lines:
        return ""
    return "[检索上下文]\n" + "\n".join(lines)


def _json_for_token_count(value: Any) -> str:
    """转换 JSON 文本供 token 估算。"""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _summarize_messages(messages: list[Any], previous_summary: str, max_chars: int, summarizer: Summarizer | None) -> str:
    """生成压缩摘要，失败时回退到规则摘要。"""
    try:
        if summarizer is not None:
            summary = summarizer(messages, previous_summary, max_chars)
        else:
            summary = _llm_summary(messages, previous_summary, max_chars)
    except Exception:
        summary = _fallback_summary(messages, previous_summary, max_chars)
    summary = str(summary or "").strip()
    if not summary:
        summary = _fallback_summary(messages, previous_summary, max_chars)
    return summary[-max_chars:]


def _llm_summary(messages: list[Any], previous_summary: str, max_chars: int) -> str:
    """调用 LLM 生成中文会话摘要。"""
    transcript = _format_messages(messages, max_chars * 2)
    previous = previous_summary.strip() or "无"
    prompt = (
        "请把以下会话历史压缩成中文摘要，用于后续继续对话。\n"
        "必须保留：用户目标、关键决策、已修改文件、工具调用结论、未完成事项、重要约束。\n"
        "不要编造事实，不要输出无关寒暄。\n"
        f"摘要最多 {max_chars} 字。\n\n"
        f"[已有摘要]\n{previous}\n\n"
        f"[待压缩历史]\n{transcript}"
    )
    response = invoke_with_fallback([HumanMessage(content=prompt)], tags=["nostream"])
    return message_text(response)


def _fallback_summary(messages: list[Any], previous_summary: str, max_chars: int) -> str:
    """用规则生成兜底摘要。"""
    lines = []
    if previous_summary.strip():
        lines.append(previous_summary.strip())
    for message in messages:
        role = _message_role_label(message)
        text = _compact_text(message_text(message), 240)
        if text:
            lines.append(f"{role}：{text}")
    return "\n".join(lines)[-max_chars:]


def _recent_turn_messages(messages: list[Any], keep_turns: int) -> list[Any]:
    """保留最近若干轮用户发起的消息。"""
    if keep_turns <= 0:
        return []
    human_indexes = [index for index, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if len(human_indexes) <= keep_turns:
        return messages
    start_index = human_indexes[-keep_turns]
    return messages[start_index:]


def _format_messages(messages: list[Any], max_chars: int) -> str:
    """格式化消息供摘要模型阅读。"""
    lines = []
    for message in messages:
        role = _message_role_label(message)
        text = _compact_text(message_text(message), 800)
        if text:
            lines.append(f"{role}：{text}")
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            lines.append(f"{role} tool_calls：{tool_calls}")
    transcript = "\n".join(lines)
    return transcript[-max_chars:]


def _message_role_label(message: Any) -> str:
    """获取中文消息角色。"""
    if isinstance(message, HumanMessage):
        return "用户"
    if isinstance(message, AIMessage):
        return "助手"
    message_type = getattr(message, "type", "")
    if message_type == "tool":
        return "工具"
    if message_type == "system":
        return "系统"
    return str(message_type or "消息")


def _compact_text(text: str, max_length: int) -> str:
    """压缩单条文本。"""
    compacted = " ".join(str(text or "").split())
    if len(compacted) <= max_length:
        return compacted
    return compacted[:max_length] + "..."
