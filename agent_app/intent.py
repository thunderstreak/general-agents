"""用户意图路由。"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent_app.config import BASE_URL, MODEL_NAME, OPENAI_API_KEY
from agent_app.prompt_loader import load_prompt


IntentName = Literal["location", "weather", "web_search", "chat", "auto"]


@dataclass
class IntentDecision:
    """意图分类结果。"""

    intent: IntentName
    reason: str = ""


INTENT_SYSTEM_PROMPT = load_prompt("intent_classifier.md")


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
