"""统一输出层。"""

from __future__ import annotations

from typing import Any, Literal

from agent_app.utils.pseudo_tools import sanitize_pseudo_tool_content


ResponseStatus = Literal["success", "error", "confirmation_required"]
ResponseType = Literal["message", "error", "confirmation"]


def build_response(state: dict[str, Any]) -> dict[str, Any]:
    """根据 AgentState 构造统一响应。"""
    last_message = state["messages"][-1] if state.get("messages") else None
    content = getattr(last_message, "content", "") if last_message is not None else ""
    content = sanitize_model_content(content)
    errors = _collect_errors(state)
    pending_confirmation = state.get("pending_confirmation") or {}

    status, response_type = _response_kind(errors, pending_confirmation)
    return {
        "status": status,
        "type": response_type,
        "content": content,
        "tool_calls": state.get("tool_calls", []),
        "tool_summary": _build_tool_summary(state.get("tool_calls", [])),
        "errors": errors,
        "retrieval_sources": _build_retrieval_sources(state.get("retrieval_results", [])),
        "memory_updated": bool(state.get("memory_updated")),
        "confirmation": pending_confirmation if status == "confirmation_required" else {},
        "trace_id": state.get("trace_id", ""),
        "node_runs": state.get("node_runs", []),
        "metadata": {
            "step_count": state.get("step_count", 0),
            "max_steps": state.get("max_steps", 0),
            "reflection": state.get("reflection", {}),
        },
    }


def render_cli_response(response: dict[str, Any], debug: bool = False) -> str:
    """渲染 CLI 输出文本。"""
    lines = [f"Agent: {sanitize_model_content(response.get('content', ''))}"]

    sources = response.get("retrieval_sources", [])
    if sources:
        lines.append("")
        lines.append("来源:")
        for source in sources:
            label = source.get("title") or source.get("source") or "unknown"
            score = source.get("score")
            suffix = f" (score={score})" if score not in (None, "") else ""
            lines.append(f"- {label}{suffix}")

    if debug:
        lines.extend(_render_debug_lines(response))

    return "\n".join(lines)


def sanitize_model_content(content: Any) -> str:
    """清理模型误输出的伪工具调用文本。"""
    return sanitize_pseudo_tool_content(content)


def _response_kind(errors: list[dict[str, Any]], pending_confirmation: dict[str, Any]) -> tuple[ResponseStatus, ResponseType]:
    """判断响应状态和类型。"""
    if pending_confirmation:
        return "confirmation_required", "confirmation"
    if errors:
        return "error", "error"
    return "success", "message"


def _collect_errors(state: dict[str, Any]) -> list[dict[str, Any]]:
    """收集错误信息。"""
    errors = []
    if state.get("last_error"):
        errors.append(state["last_error"])
    for error in state.get("tool_errors", []):
        if isinstance(error, dict):
            errors.append(error)
        else:
            errors.append({"message": str(error)})
    return errors


def _build_tool_summary(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """生成工具调用摘要。"""
    summary = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        summary.append(
            {
                "tool_name": call.get("tool_name", ""),
                "success": bool(call.get("success")),
                "duration_ms": call.get("duration_ms", 0.0),
                "attempts": call.get("attempts", 0),
                "result_status": call.get("result_status", ""),
                "error_type": call.get("error_type", ""),
                "is_retryable": bool(call.get("is_retryable")),
                "fallback_tool_names": call.get("fallback_tool_names", []),
            }
        )
    return summary


def _build_retrieval_sources(retrieval_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """生成检索来源摘要。"""
    sources = []
    for item in retrieval_results:
        if not isinstance(item, dict):
            continue
        sources.append(
            {
                "source": item.get("source", ""),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "document_id": item.get("document_id", ""),
                "chunk_id": item.get("chunk_id", ""),
                "chunk_index": item.get("chunk_index", ""),
                "document_version": item.get("document_version", ""),
                "page": item.get("page", ""),
                "sheet": item.get("sheet", ""),
                "score": item.get("score", ""),
                "vector_score": item.get("vector_score", ""),
                "keyword_score": item.get("keyword_score", ""),
            }
        )
    return sources


def _render_debug_lines(response: dict[str, Any]) -> list[str]:
    """渲染 debug 信息。"""
    lines = ["", "Debug:"]
    if response.get("trace_id"):
        lines.append(f"- trace_id: {response['trace_id']}")

    tool_summary = response.get("tool_summary", [])
    if tool_summary:
        lines.append("- tools:")
        for tool in tool_summary:
            lines.append(
                f"  - {tool.get('tool_name', '')}: "
                f"success={tool.get('success')} "
                f"duration_ms={tool.get('duration_ms')} "
                f"attempts={tool.get('attempts')} "
                f"result_status={tool.get('result_status', '')} "
                f"error_type={tool.get('error_type', '')}"
            )

    node_runs = response.get("node_runs", [])
    if node_runs:
        lines.append("- nodes:")
        for node in node_runs:
            lines.append(
                f"  - {node.get('node_name', '')}: "
                f"success={node.get('success')} "
                f"duration_ms={node.get('duration_ms')} "
                f"error={node.get('error', '')}"
            )

    reflection = (response.get("metadata") or {}).get("reflection") or {}
    if reflection:
        lines.append("- reflection:")
        lines.append(
            f"  - status={reflection.get('status', '')} "
            f"next_action={reflection.get('next_action', '')} "
            f"retry_count={reflection.get('retry_count', 0)} "
            f"stop_reason={reflection.get('stop_reason', '')}"
        )
        if reflection.get("fallback_tool_name") or reflection.get("loop_reason") or reflection.get("attempted_tools"):
            lines.append(
                f"  - fallback_tool={reflection.get('fallback_tool_name', '')} "
                f"attempted_tools={reflection.get('attempted_tools', [])} "
                f"loop_reason={reflection.get('loop_reason', '')}"
            )
        if reflection.get("reason"):
            lines.append(f"  - reason={reflection.get('reason')}")

    errors = response.get("errors", [])
    if errors:
        lines.append("- errors:")
        for error in errors:
            lines.append(f"  - {error.get('message') or error.get('error') or error}")

    return lines
