"""基于工具元数据的工具选择器。"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from agent_app.llm import get_tool_selector_model
from agent_app.prompt_loader import load_prompt
from agent_app.tools import candidate_tool_names_for_text, tool_metadata


SelectorAction = Literal["tool", "chat", "auto"]
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
REALTIME_KEYWORDS = ("今天", "现在", "当前", "实时", "最新", "today", "now", "current", "recent")
EXTERNAL_INFO_KEYWORDS = (
    "股票",
    "股市",
    "行情",
    "市场",
    "汇率",
    "价格",
    "走势",
    "金价",
    "黄金",
    "贵金属",
    "预测",
    "新闻",
    "政策",
    "法规",
    "公告",
    "release",
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
    """判断是否需要进入可调用工具的 agent 模式。"""
    normalized = _normalize_quick_chat_text(user_text)
    if not normalized:
        return False

    if any(keyword in normalized for keyword in MEMORY_INSTRUCTION_KEYWORDS):
        return False

    if candidate_tool_names_for_text(normalized):
        return True

    if any(keyword in normalized for keyword in LOCAL_CONTEXT_KEYWORDS):
        return False

    return any(keyword in normalized for keyword in REALTIME_KEYWORDS) and any(
        keyword in normalized for keyword in EXTERNAL_INFO_KEYWORDS
    )


def quick_chat_selection(user_text: str) -> ToolSelection | None:
    """对明显普通对话做本地快速判断，避免额外调用工具选择模型。"""
    normalized = _normalize_quick_chat_text(user_text)
    if not normalized:
        return None

    if normalized in QUICK_CHAT_EXACT_MATCHES:
        return ToolSelection(action="chat", confidence=1.0, reason="本地快速判断：普通对话")

    return None


def select_tool(user_text: str) -> ToolSelection:
    """根据用户输入和工具元数据选择工具。"""
    prompt = load_prompt("tool_selector.md").replace("{tool_descriptions}", _format_tool_descriptions())

    try:
        response = _get_selector_llm().invoke(
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
