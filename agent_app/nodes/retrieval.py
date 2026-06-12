"""RAG 检索节点。"""

import time

from agent_app.nodes.common import emit_progress, latest_human_message, node_run
from agent_app.orchestrator import new_trace_id, should_retrieve
from agent_app.state import AgentState
from agent_app.utils.messages import message_text


def retrieval_node(state: AgentState):
    """RAG 检索预留节点。"""
    start_time = time.perf_counter()
    trace_id = state.get("trace_id") or new_trace_id()
    latest_message = latest_human_message(state["messages"])
    user_text = message_text(latest_message)

    retrieval_results = []
    if should_retrieve(user_text):
        emit_progress("检索中...", node="retrieval")
        retrieval_results.append(
            {
                "source": "local_rag_placeholder",
                "content": "RAG 检索模块尚未接入，当前仅保留编排节点和结果结构。",
                "score": 0.0,
            }
        )

    return {
        "trace_id": trace_id,
        "retrieval_results": retrieval_results,
        "node_runs": [node_run("retrieval", start_time)],
    }
