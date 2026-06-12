"""LangChain message 辅助函数。"""

from typing import Any


def message_text(message: Any) -> str:
    """提取消息中的文本内容。"""
    if message is None:
        return ""

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
