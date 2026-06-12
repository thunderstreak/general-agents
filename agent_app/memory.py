"""长期记忆管理。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_app.config import MEMORY_FILE_PATH, MEMORY_MAX_ITEMS


@dataclass
class MemoryItem:
    """单条长期记忆。"""

    content: str
    category: str = "fact"
    source: str = "user"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, str]:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class MemoryStore:
    """长期记忆存储结构。"""

    items: list[MemoryItem] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 存储结构。"""
        return {
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
        }


def load_memory() -> MemoryStore:
    """从本地 JSON 文件加载长期记忆。"""
    path = Path(MEMORY_FILE_PATH).expanduser()
    if not path.is_file():
        return MemoryStore()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return MemoryStore()

    items = []
    for raw_item in payload.get("items", []):
        if not isinstance(raw_item, dict) or not raw_item.get("content"):
            continue
        items.append(
            MemoryItem(
                content=str(raw_item["content"]),
                category=str(raw_item.get("category", "fact")),
                source=str(raw_item.get("source", "user")),
                created_at=str(raw_item.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            )
        )

    return MemoryStore(items=items[-MEMORY_MAX_ITEMS:], summary=str(payload.get("summary", "")))


def save_memory(memory: MemoryStore) -> None:
    """保存长期记忆到本地 JSON 文件。"""
    path = Path(MEMORY_FILE_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    memory.items = memory.items[-MEMORY_MAX_ITEMS:]
    path.write_text(json.dumps(memory.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def memory_to_state(memory: MemoryStore) -> dict[str, Any]:
    """转换为可写入 AgentState 的结构。"""
    return memory.to_dict()


def state_to_memory(memory_state: dict[str, Any] | None) -> MemoryStore:
    """从 AgentState 结构恢复 MemoryStore。"""
    if not memory_state:
        return MemoryStore()

    items = []
    for raw_item in memory_state.get("items", []):
        if isinstance(raw_item, dict) and raw_item.get("content"):
            items.append(
                MemoryItem(
                    content=str(raw_item["content"]),
                    category=str(raw_item.get("category", "fact")),
                    source=str(raw_item.get("source", "user")),
                    created_at=str(raw_item.get("created_at") or datetime.now().isoformat(timespec="seconds")),
                )
            )
    return MemoryStore(items=items[-MEMORY_MAX_ITEMS:], summary=str(memory_state.get("summary", "")))


def build_memory_context(memory_state: dict[str, Any] | None) -> str:
    """构造注入模型的长期记忆上下文。"""
    memory = state_to_memory(memory_state)
    parts = []
    if memory.summary:
        parts.append(f"历史摘要：{memory.summary}")

    if memory.items:
        item_lines = [f"- {item.content}" for item in memory.items[-MEMORY_MAX_ITEMS:]]
        parts.append("已知长期记忆：\n" + "\n".join(item_lines))

    if not parts:
        return ""

    return "\n\n".join(parts)


def with_memory_context(messages: list, memory_state: dict[str, Any] | None) -> list:
    """在模型消息前追加长期记忆系统消息。"""
    context = build_memory_context(memory_state)
    if not context:
        return messages

    return [
        SystemMessage(
            content=(
                "[长期记忆]\n"
                "下面是用户明确要求保留或可稳定复用的信息。回答时可参考，但不要主动泄露无关记忆。\n"
                f"{context}"
            )
        ),
        *messages,
    ]


def update_memory_from_turn(memory_state: dict[str, Any] | None, human_message: HumanMessage, ai_message: AIMessage) -> dict[str, Any]:
    """根据一轮对话更新长期记忆。"""
    memory = state_to_memory(memory_state)
    user_text = _message_text(human_message)
    assistant_text = _message_text(ai_message)

    new_items = extract_memory_items(user_text)
    for item in new_items:
        _append_unique(memory, item)

    memory.summary = update_summary(memory.summary, user_text, assistant_text)
    memory.items = memory.items[-MEMORY_MAX_ITEMS:]
    save_memory(memory)
    return memory_to_state(memory)


def extract_memory_items(user_text: str) -> list[MemoryItem]:
    """从用户文本中提取明确的长期记忆。"""
    text = user_text.strip()
    if not text:
        return []

    items = []
    explicit_match = re.search(r"(?:请记住|记住|以后记得|帮我记住)[：:，,\s]*(?P<content>.+)", text)
    if explicit_match:
        items.append(MemoryItem(content=explicit_match.group("content").strip(), category="explicit"))

    name_match = re.search(r"(?:我叫|我的名字是|我是)[：:，,\s]*(?P<name>[\w\u4e00-\u9fff-]{2,30})", text)
    if name_match:
        items.append(MemoryItem(content=f"用户名字是 {name_match.group('name').strip()}", category="profile"))

    preference_match = re.search(r"我(?:喜欢|偏好|常用|习惯)[：:，,\s]*(?P<content>.+)", text)
    if preference_match:
        items.append(MemoryItem(content=f"用户偏好：{preference_match.group('content').strip()}", category="preference"))

    return items


def update_summary(summary: str, user_text: str, assistant_text: str) -> str:
    """用简单规则维护短摘要，避免第一版依赖额外 LLM 调用。"""
    if not user_text and not assistant_text:
        return summary

    turn_summary = f"用户：{_compact(user_text)} / 助手：{_compact(assistant_text)}"
    if not summary:
        return turn_summary

    combined = f"{summary}\n{turn_summary}"
    return combined[-2000:]


def _append_unique(memory: MemoryStore, item: MemoryItem) -> None:
    """按内容去重追加记忆。"""
    normalized = item.content.strip()
    if not normalized:
        return
    if any(existing.content == normalized for existing in memory.items):
        return
    memory.items.append(item)


def _compact(text: str, max_length: int = 160) -> str:
    """压缩单轮文本，控制摘要长度。"""
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= max_length:
        return compacted
    return compacted[:max_length] + "..."


def _message_text(message) -> str:
    """提取消息文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(parts)
    return str(content)
