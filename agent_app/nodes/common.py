"""节点共享辅助函数。"""

import time

from langchain_core.messages import HumanMessage
from langgraph.config import get_stream_writer

from agent_app.config import ORCHESTRATOR_MAX_STEPS
from agent_app.orchestrator import error_state, success_node_run
from agent_app.state import AgentState


def emit_progress(message: str, event: str = "progress", **metadata) -> None:
    """发送 CLI 可消费的流式进度事件。"""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return

    payload = {"event": event, "message": message}
    payload.update(metadata)
    writer(payload)


def latest_human_message(messages: list):
    """获取最近一条用户消息。"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def next_step_state(state: AgentState, node_name: str):
    """增加编排步骤计数，超过上限时返回错误状态。"""
    step_count = int(state.get("step_count", 0)) + 1
    max_steps = int(state["max_steps"]) if state.get("max_steps") is not None else ORCHESTRATOR_MAX_STEPS
    if step_count > max_steps:
        return {
            "step_count": step_count,
            "last_error": error_state(f"编排步骤超过上限：{max_steps}", "max_steps_exceeded", node_name),
        }
    return {"step_count": step_count}


def node_run(node_name: str, start_time: float, success: bool = True, error: str = "") -> dict:
    """生成节点运行记录。"""
    if success:
        return success_node_run(node_name, start_time)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {"node_name": node_name, "success": False, "duration_ms": duration_ms, "error": error, "started_at": time.time()}


def join_tool_errors(tool_error_records: list[dict]) -> str:
    """拼接工具错误信息。"""
    return "；".join(record.get("error") or record.get("result", "") for record in tool_error_records)
