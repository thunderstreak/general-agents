"""用户意图路由。"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent_app.config import BASE_URL, MODEL_NAME, OPENAI_API_KEY


IntentName = Literal["location", "weather", "web_search", "chat", "auto"]


@dataclass
class IntentDecision:
    """意图分类结果。"""

    intent: IntentName
    reason: str = ""


INTENT_SYSTEM_PROMPT = """你是一个意图分类器，只输出 JSON，不要输出 Markdown。

根据用户最后一句话选择 intent：
- location：用户询问自己在哪里、当前位置、当前地址、我的位置。
- weather：用户询问天气、气温、温度、是否下雨、降雨、空气冷热等天气信息。即使用户说“搜索天气”，也选择 weather，因为目标是天气数据。
- web_search：用户明确要求搜索网页、查询网上资料、新闻、最新信息，且不属于 weather 或 location。
- chat：普通闲聊、解释代码、一般问题，不需要工具。
- auto：不确定时选择，让主模型自行决定是否调用工具。

返回格式必须是：
{"intent": "weather", "reason": "一句简短中文原因"}
"""


intent_llm = ChatOpenAI(model=MODEL_NAME, base_url=BASE_URL, openai_api_key=OPENAI_API_KEY, temperature=0)


def classify_intent(user_text: str) -> IntentDecision:
    """使用模型把用户最后一句话分类为结构化意图。"""
    try:
        response = intent_llm.invoke(
            [
                SystemMessage(content=INTENT_SYSTEM_PROMPT),
                HumanMessage(content=user_text),
            ]
        )
        payload = json.loads(response.content)
    except Exception as exc:
        return IntentDecision(intent="auto", reason=f"意图分类失败：{exc}")

    intent = payload.get("intent", "auto")
    if intent not in {"location", "weather", "web_search", "chat", "auto"}:
        return IntentDecision(intent="auto", reason=f"未知意图：{intent}")

    return IntentDecision(intent=intent, reason=payload.get("reason", ""))
