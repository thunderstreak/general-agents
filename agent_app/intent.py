"""用户意图路由。"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent_app.llm import get_intent_model
from agent_app.prompt_loader import load_prompt


IntentName = Literal["location", "weather", "web_search", "chat", "auto"]
LOW_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class IntentDecision:
    """意图分类结果。"""

    intent: IntentName
    confidence: float = 0.0
    reason: str = ""


INTENT_SYSTEM_PROMPT = load_prompt("intent_classifier.md")


intent_llm = get_intent_model()


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
        return IntentDecision(intent="auto", confidence=0.0, reason=f"意图分类失败：{exc}")

    intent = payload.get("intent", "auto")
    if intent not in {"location", "weather", "web_search", "chat", "auto"}:
        return IntentDecision(intent="auto", confidence=0.0, reason=f"未知意图：{intent}")

    confidence = _parse_confidence(payload.get("confidence", 0.0))
    reason = payload.get("reason", "")
    if confidence < LOW_CONFIDENCE_THRESHOLD and intent != "auto":
        return IntentDecision(intent="auto", confidence=confidence, reason=f"低置信度回退：{reason}")

    return IntentDecision(intent=intent, confidence=confidence, reason=reason)


def _parse_confidence(value) -> float:
    """解析并限制置信度范围。"""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, confidence))
