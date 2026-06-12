"""命令行交互入口。"""

from agent_app.file_inputs import build_human_message, parse_user_input
from agent_app.config import ORCHESTRATOR_MAX_STEPS
from agent_app.graph import app, resume_confirmed_tool
from agent_app.memory import load_memory, memory_to_state
from agent_app.orchestrator import new_trace_id


def run_cli():
    """启动命令行 Agent。"""
    print("🧠 LangGraph Agent 启动 (输入 'quit' 退出)\n")
    memory = load_memory()
    state = {
        "messages": [],
        "tool_selection": {},
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
        "long_term_memory": memory_to_state(memory),
        "step_count": 0,
        "max_steps": ORCHESTRATOR_MAX_STEPS,
        "last_error": {},
        "pending_confirmation": {},
        "approved_tool_call_ids": [],
        "final_response": {},
        "trace_id": "",
        "node_runs": [],
        "memory_updated": False,
    }  # 持久化状态

    while True:
        user_input = input("你: ")
        if user_input.lower() == "quit":
            break

        if state.get("pending_confirmation"):
            if user_input.lower() in {"yes", "y"}:
                state = resume_confirmed_tool(state, approved=True)
                state = _reset_turn_state(state)
                result = app.invoke(state)
                state = result
                _print_response(state)
                continue
            if user_input.lower() in {"no", "n"}:
                state = resume_confirmed_tool(state, approved=False)
                state = _reset_turn_state(state)
                _print_response(state)
                continue
            print("请输入 yes 确认执行，或 no 取消。\n")
            continue

        # 保留多轮上下文，让工具调用和模型回复都在消息历史中连续出现
        text, file_results = parse_user_input(user_input)
        state["messages"].append(build_human_message(text, file_results))
        state = _reset_turn_state(state)
        result = app.invoke(state)
        state = result
        _print_response(state)


def _reset_turn_state(state: dict) -> dict:
    """重置单轮编排状态，保留历史消息和长期记忆。"""
    state["step_count"] = 0
    state["max_steps"] = ORCHESTRATOR_MAX_STEPS
    state["last_error"] = {}
    state["retrieval_results"] = []
    state["final_response"] = {}
    state["trace_id"] = new_trace_id()
    state["node_runs"] = []
    state["memory_updated"] = False
    state["approved_tool_call_ids"] = state.get("approved_tool_call_ids", [])
    return state


def _print_response(state: dict) -> None:
    """打印统一响应。"""
    response = state.get("final_response") or {}
    content = response.get("content")
    if content is None:
        content = state["messages"][-1].content
    print(f"Agent: {content}\n")
