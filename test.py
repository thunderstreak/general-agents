# from langchain_openai import ChatOpenAI

# llm = ChatOpenAI(
#     model="gpt-5.5",               # 第三方可能用别的名字，按对方文档填写
#     temperature=0,
#     openai_api_key="your-api-key-here",     # 直接写，或用环境变量
#     base_url="https://tokendocker.com/v1"   # 关键：改成第三方给的地址
# )
# response = llm.invoke("你好")
# print(response.content)

# from langchain_openai import ChatOpenAI
# from langchain_core.tools import tool

# @tool
# def add(a: int, b: int) -> int:
#     """两数相加"""
#     return a + b

# llm = ChatOpenAI(model="gpt-5.5", base_url="https://tokendocker.com/v1", openai_api_key="your-api-key-here")
# llm_with_tools = llm.bind_tools([add])
# response = llm_with_tools.invoke("帮我算 3+5")
# print(response)


from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查天气"""
    return "晴，22°C"

llm = ChatOpenAI(model="gpt-5.5", base_url="https://tokendocker.com/v1", openai_api_key="your-api-key-here")
llm_with_tools = llm.bind_tools([get_weather])

# 第一次调用
response1 = llm_with_tools.invoke([HumanMessage(content="长沙天气")])
print("第一步 tool_calls:", response1.tool_calls)

# 模拟工具返回
tool_call = response1.tool_calls[0]
tool_result = get_weather.invoke(tool_call["args"])
tool_msg = ToolMessage(content=tool_result, tool_call_id=tool_call["id"])

# 第二次调用（这里大概率会报 400）
response2 = llm_with_tools.invoke([HumanMessage(content="长沙天气"), response1, tool_msg])
print("第二步回复:", response2.content)
