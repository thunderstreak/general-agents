"""Agent 编排层辅助结构。"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_MAX_STEPS = 8


@dataclass
class NodeRun:
    """单个编排节点运行记录。"""

    node_name: str
    success: bool
    duration_ms: float
    error: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 state 的字典。"""
        return asdict(self)


@contextmanager
def trace_node(node_name: str):
    """记录节点运行耗时和错误。"""
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        raise NodeExecutionError(node_name=node_name, error=str(exc), duration_ms=duration_ms) from exc


class NodeExecutionError(RuntimeError):
    """节点执行失败。"""

    def __init__(self, node_name: str, error: str, duration_ms: float):
        super().__init__(error)
        self.node_name = node_name
        self.error = error
        self.duration_ms = duration_ms

    def to_node_run(self) -> dict[str, Any]:
        """转换为失败节点运行记录。"""
        return NodeRun(node_name=self.node_name, success=False, duration_ms=self.duration_ms, error=self.error).to_dict()


def new_trace_id() -> str:
    """生成单轮 trace id。"""
    return uuid.uuid4().hex


def success_node_run(node_name: str, start_time: float) -> dict[str, Any]:
    """生成成功节点运行记录。"""
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return NodeRun(node_name=node_name, success=True, duration_ms=duration_ms).to_dict()


def error_state(message: str, error_type: str = "orchestrator_error", node_name: str = "") -> dict[str, Any]:
    """构造统一错误状态。"""
    return {
        "type": error_type,
        "node_name": node_name,
        "message": message,
    }


def confirmation_state(tool_name: str, tool_args: dict[str, Any], tool_call_id: str) -> dict[str, Any]:
    """构造人工确认等待状态。"""
    return {
        "status": "pending",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_call_id": tool_call_id,
        "message": f"工具 {tool_name} 需要人工确认后才能执行。",
    }


def build_response(state: dict[str, Any]) -> dict[str, Any]:
    """构造统一输出结构。"""
    last_message = state["messages"][-1] if state.get("messages") else None
    content = getattr(last_message, "content", "") if last_message is not None else ""
    errors = []
    if state.get("last_error"):
        errors.append(state["last_error"])
    errors.extend(state.get("tool_errors", []))

    return {
        "content": content,
        "tool_calls": state.get("tool_calls", []),
        "errors": errors,
        "retrieval_sources": [item.get("source", "") for item in state.get("retrieval_results", []) if isinstance(item, dict)],
        "memory_updated": bool(state.get("memory_updated")),
        "trace_id": state.get("trace_id", ""),
        "node_runs": state.get("node_runs", []),
    }


def should_retrieve(user_text: str) -> bool:
    """判断是否需要进入 RAG 检索预留节点。"""
    keywords = ("知识库", "文档", "资料库", "内部资料", "根据资料", "检索")
    return any(keyword in user_text for keyword in keywords)
