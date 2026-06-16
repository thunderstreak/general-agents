"""基于 LLM 结构化输出的规划选择器。"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent_app.llm import get_tool_selector_model
from agent_app.prompt_loader import load_prompt
from agent_app.tools import tool_metadata


SelectorAction = Literal["tool", "tool_agent", "chat", "clarification", "auto"]
LOW_CONFIDENCE_THRESHOLD = 0.7
LOCAL_CONTEXT_KEYWORDS = (
    "知识库",
    "文档",
    "资料库",
    "内部资料",
    "根据资料",
    "检索",
    "[文件:",
    "[文件内容]",
    "[图片文件]",
    "[文件解析失败]",
)
MEMORY_INSTRUCTION_KEYWORDS = (
    "记住",
    "请记住",
    "以后你要",
    "我的偏好",
)
QUICK_CHAT_EXACT_MATCHES = {
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "hey",
    "nihao",
    "ni hao",
    "谢谢",
    "多谢",
    "感谢",
    "再见",
    "拜拜",
    "你是谁",
    "你能做什么",
}
PLANNER_MODES = {"tool", "tool_agent", "chat", "clarification"}


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


_selector_llm = None


def should_enter_tool_mode(user_text: str) -> bool:
    """兼容旧调用：仅保留明确 URL 和工具触发词的轻量判断。"""
    normalized = _normalize_quick_chat_text(user_text)
    if not normalized:
        return False

    if any(keyword in normalized for keyword in MEMORY_INSTRUCTION_KEYWORDS):
        return False

    if any(keyword in normalized for keyword in LOCAL_CONTEXT_KEYWORDS):
        return False

    return any(str(keyword).lower() in normalized for metadata in tool_metadata for keyword in metadata.trigger_keywords)


def quick_chat_selection(user_text: str) -> ToolSelection | None:
    """对明显普通对话做本地快速判断，避免额外调用工具选择模型。"""
    normalized = _normalize_quick_chat_text(user_text)
    if not normalized:
        return None

    if normalized in QUICK_CHAT_EXACT_MATCHES:
        return ToolSelection(action="chat", confidence=1.0, reason="本地快速判断：普通对话")

    return None


def select_tool(user_text: str) -> ToolSelection:
    """兼容旧调用：使用结构化 planner，仅返回工具或聊天选择。"""
    selection = select_plan(user_text, {})
    if selection.action == "tool_agent":
        return ToolSelection(action="auto", args=selection.args, confidence=selection.confidence, reason=selection.reason)
    if selection.action == "clarification":
        return ToolSelection(action="auto", args=selection.args, confidence=selection.confidence, reason=selection.reason)
    return selection


def select_plan(user_text: str, input_context: dict | None = None) -> ToolSelection:
    """调用结构化 planner 生成本轮规划选择。"""
    input_context = input_context or {}
    prompt = (
        load_prompt("planner.md")
        .replace("{tool_descriptions}", _format_tool_descriptions())
        .replace("{input_context}", _json_dumps(input_context))
    )

    try:
        response = _get_selector_llm().invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=user_text),
            ]
        )
        payload = json.loads(str(response.content or "").strip())
    except Exception as exc:
        return ToolSelection(action="auto", confidence=0.0, reason=f"规划失败：{exc}")

    return parse_planner_payload(payload)


def parse_planner_payload(payload: dict[str, Any]) -> ToolSelection:
    """校验 planner JSON 并转换为 ToolSelection。"""
    if not isinstance(payload, dict):
        return ToolSelection(action="auto", confidence=0.0, reason="规划结果格式错误")

    action = payload.get("mode") or payload.get("action") or "auto"
    if action not in PLANNER_MODES:
        return ToolSelection(action="auto", confidence=0.0, reason=f"未知 mode：{action}")

    confidence = _parse_confidence(payload.get("confidence", 0.0))
    reason = str(payload.get("reason") or "").strip()
    if confidence < LOW_CONFIDENCE_THRESHOLD and action not in {"chat", "clarification"}:
        return ToolSelection(action="chat", confidence=confidence, reason=f"低置信度回退：{reason}")

    available_tool_names = {metadata.name for metadata in tool_metadata}
    candidate_tool_names = _valid_tool_names(payload.get("candidate_tool_names"), available_tool_names)
    tool_name = str(payload.get("tool_name") or "").strip()
    args = payload.get("args", {})
    if not isinstance(args, dict):
        return ToolSelection(action="auto", confidence=confidence, reason="工具参数格式错误")
    if action == "tool" and tool_name not in available_tool_names:
        return ToolSelection(action="auto", tool_name=tool_name, args=args, confidence=confidence, reason=f"未知工具：{tool_name}")
    if action == "tool" and tool_name not in candidate_tool_names:
        candidate_tool_names.insert(0, tool_name)

    selection_args = {"_candidate_tool_names": candidate_tool_names}
    if action == "clarification":
        selection_args.update(
            {
                "question": str(payload.get("clarification_question") or "").strip(),
                "missing_info": str(payload.get("missing_info") or "").strip(),
                "reason": reason,
            }
        )
    if action == "tool":
        selection_args.update(args)
    if action not in {"tool", "tool_agent"}:
        tool_name = ""
    return ToolSelection(action=action, tool_name=tool_name, args=selection_args, confidence=confidence, reason=reason)


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


def _valid_tool_names(value, available_tool_names: set[str]) -> list[str]:
    """过滤 planner 返回的候选工具名。"""
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        name = str(item or "").strip()
        if name in available_tool_names and name not in names:
            names.append(name)
    return names


def _json_dumps(value: Any) -> str:
    """将上下文转换为稳定 JSON。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _get_selector_llm():
    """延迟获取工具选择模型，避免导入模块时初始化模型。"""
    global _selector_llm
    if _selector_llm is None:
        _selector_llm = get_tool_selector_model()
    return _selector_llm


def _normalize_quick_chat_text(text: str) -> str:
    """标准化短文本，供快速普通对话判断使用。"""
    normalized = str(text or "").strip().lower()
    return " ".join(normalized.strip(" \t\r\n,.!?。！？~～，、").split())


def _parse_confidence(value) -> float:
    """解析并限制置信度范围。"""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, confidence))
