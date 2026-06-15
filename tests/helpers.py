"""测试辅助函数。"""

from langchain_core.messages import HumanMessage


def base_state() -> dict:
    """构造基础 AgentState。"""
    return {
        "messages": [HumanMessage(content="你好")],
        "input_context": {},
        "tool_selection": {},
        "plan": {},
        "reflection": {},
        "last_tool_request": {},
        "attempted_tools": [],
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
        "long_term_memory": {},
        "step_count": 0,
        "max_steps": 8,
        "last_error": {},
        "pending_confirmation": {},
        "approved_tool_call_ids": [],
        "final_response": {},
        "trace_id": "test-trace",
        "node_runs": [],
        "memory_updated": False,
    }
