"""基于工具元数据的工具选择器。"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent_app.llm import get_tool_selector_model
from agent_app.prompt_loader import load_prompt
from agent_app.tools import tool_metadata


SelectorAction = Literal["tool", "chat", "auto"]
LOW_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ToolSelection:
    """工具选择结果。"""

    action: SelectorAction
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 LangGraph state 的字典。"""
        return asdict(self)


selector_llm = get_tool_selector_model()


def select_tool(user_text: str) -> ToolSelection:
    """根据用户输入和工具元数据选择工具。"""
    prompt = load_prompt("tool_selector.md").replace("{tool_descriptions}", _format_tool_descriptions())

    try:
        response = selector_llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=user_text),
            ]
        )
        payload = json.loads(response.content)
    except Exception as exc:
        return ToolSelection(action="auto", confidence=0.0, reason=f"工具选择失败：{exc}")

    action = payload.get("action", "auto")
    if action not in {"tool", "chat", "auto"}:
        return ToolSelection(action="auto", confidence=0.0, reason=f"未知 action：{action}")

    confidence = _parse_confidence(payload.get("confidence", 0.0))
    tool_name = payload.get("tool_name", "")
    args = payload.get("args", {})
    reason = payload.get("reason", "")

    if not isinstance(args, dict):
        return ToolSelection(action="auto", confidence=confidence, reason="工具参数格式错误")

    if confidence < LOW_CONFIDENCE_THRESHOLD and action != "auto":
        return ToolSelection(action="auto", tool_name=tool_name, args=args, confidence=confidence, reason=f"低置信度回退：{reason}")

    available_tool_names = {metadata.name for metadata in tool_metadata}
    if action == "tool" and tool_name not in available_tool_names:
        return ToolSelection(action="auto", tool_name=tool_name, args=args, confidence=confidence, reason=f"未知工具：{tool_name}")

    if action != "tool":
        tool_name = ""
        args = {}

    return ToolSelection(action=action, tool_name=tool_name, args=args, confidence=confidence, reason=reason)


def _format_tool_descriptions() -> str:
    """将工具元数据格式化给选择器模型。"""
    lines = []
    for metadata in tool_metadata:
        lines.append(
            f"- name: {metadata.name}\n"
            f"  category: {metadata.category}\n"
            f"  description: {metadata.description}\n"
            f"  requires_confirmation: {metadata.requires_confirmation}"
        )
    return "\n".join(lines)


def _parse_confidence(value) -> float:
    """解析并限制置信度范围。"""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, confidence))
