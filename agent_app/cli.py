"""命令行交互入口。"""

from langchain_core.messages import HumanMessage

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
        state["messages"].append(HumanMessage(content=user_input))
        result = app.invoke(state)
        state = result
        last_ai = state["messages"][-1]
        print(f"Agent: {last_ai.content}\n")
