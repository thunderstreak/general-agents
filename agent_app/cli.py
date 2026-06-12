"""命令行交互入口。"""

from agent_app.file_inputs import build_human_message, parse_user_input
from agent_app.graph import app


def run_cli():
    """启动命令行 Agent。"""
    print("🧠 LangGraph Agent 启动 (输入 'quit' 退出)\n")
    state = {
        "messages": [],
        "tool_selection": {},
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
    }  # 持久化状态

    while True:
        user_input = input("你: ")
        if user_input.lower() == "quit":
            break

        # 保留多轮上下文，让工具调用和模型回复都在消息历史中连续出现
        text, file_results = parse_user_input(user_input)
        state["messages"].append(build_human_message(text, file_results))
        result = app.invoke(state)
        state = result
        last_ai = state["messages"][-1]
        print(f"Agent: {last_ai.content}\n")
