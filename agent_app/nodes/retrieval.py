"""RAG 检索节点。"""

import time

from agent_app.nodes.common import emit_progress, latest_human_message, node_run
from agent_app.orchestrator import new_trace_id, should_retrieve
from agent_app.rag import search_knowledge
from agent_app.state import AgentState
from agent_app.utils.messages import message_text


def retrieval_node(state: AgentState):
    """执行 RAG 知识检索。"""
    start_time = time.perf_counter()
    trace_id = state.get("trace_id") or new_trace_id()
    latest_message = latest_human_message(state["messages"])
    input_context = state.get("input_context") or {}
    user_text = input_context.get("normalized_text") or message_text(latest_message)

    retrieval_results = []
    if input_context.get("should_retrieve") or should_retrieve(user_text):
        emit_progress("检索中...", node="retrieval")
        retrieval_results = search_knowledge(user_text, progress=_emit_rag_progress)

    return {
        "trace_id": trace_id,
        "retrieval_results": retrieval_results,
        "node_runs": [node_run("retrieval", start_time)],
    }


def _emit_rag_progress(message: str) -> None:
    """发送 RAG 内部阶段进度。"""
    emit_progress(message, node="retrieval", event="rag_progress")
