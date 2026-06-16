"""文件夹式会话历史存储。"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from agent_app.config import SESSION_STORE_DIR
from agent_app.utils.messages import message_text


STATE_VERSION = 1
SAFE_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class SessionMetadata:
    """会话元数据。"""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    last_user_input: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 字典。"""
        return asdict(self)


def create_session(store_dir: str | Path = SESSION_STORE_DIR) -> SessionMetadata:
    """创建新会话目录和元数据。"""
    now = _now()
    session_id = uuid.uuid4().hex[:12]
    metadata = SessionMetadata(
        session_id=session_id,
        title=f"新会话 {now}",
        created_at=now,
        updated_at=now,
    )
    session_dir = _session_dir(store_dir, session_id)
    session_dir.mkdir(parents=True, exist_ok=False)
    _write_json(session_dir / "metadata.json", metadata.to_dict())
    _write_json(session_dir / "state.json", {"version": STATE_VERSION, "state": {}})
    (session_dir / "messages.jsonl").write_text("", encoding="utf-8")
    (session_dir / "messages.archive.jsonl").write_text("", encoding="utf-8")
    return metadata


def save_session_state(
    session_id: str,
    state: dict[str, Any],
    store_dir: str | Path = SESSION_STORE_DIR,
    archived_messages: list[Any] | None = None,
) -> SessionMetadata:
    """保存完整 state、可读消息日志和元数据。"""
    session_dir = _session_dir(store_dir, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    old_metadata = load_session_metadata(session_id, store_dir)
    now = _now()
    serializable_state = _state_to_json(state)
    messages = state.get("messages", [])
    user_inputs = [message_text(message) for message in messages if _message_role(message) == "user"]
    title = old_metadata.title if old_metadata else _build_title(user_inputs)
    if old_metadata and old_metadata.title.startswith("新会话") and user_inputs:
        title = _build_title(user_inputs)
    metadata = SessionMetadata(
        session_id=session_id,
        title=title,
        created_at=old_metadata.created_at if old_metadata else now,
        updated_at=now,
        message_count=len(messages) if isinstance(messages, list) else 0,
        last_user_input=user_inputs[-1] if user_inputs else "",
    )

    _write_json(session_dir / "state.json", {"version": STATE_VERSION, "state": serializable_state})
    _write_json(session_dir / "metadata.json", metadata.to_dict())
    _write_messages_jsonl(session_dir / "messages.jsonl", messages)
    _append_messages_jsonl(session_dir / "messages.archive.jsonl", archived_messages or [])
    return metadata


def load_session_state(session_id: str, store_dir: str | Path = SESSION_STORE_DIR) -> dict[str, Any]:
    """加载会话 state。"""
    state_path = _session_dir(store_dir, session_id) / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return _state_from_json(payload.get("state", {}))


def load_session_metadata(session_id: str, store_dir: str | Path = SESSION_STORE_DIR) -> SessionMetadata | None:
    """读取单个会话元数据。"""
    metadata_path = _session_dir(store_dir, session_id) / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return SessionMetadata(
        session_id=str(payload.get("session_id", session_id)),
        title=str(payload.get("title", "未命名会话")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        message_count=int(payload.get("message_count", 0)),
        last_user_input=str(payload.get("last_user_input", "")),
    )


def list_sessions(store_dir: str | Path = SESSION_STORE_DIR) -> list[SessionMetadata]:
    """按更新时间倒序列出会话。"""
    root = Path(store_dir)
    if not root.is_dir():
        return []

    sessions = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            metadata = load_session_metadata(child.name, root)
        except ValueError:
            continue
        if metadata is not None:
            sessions.append(metadata)
    return sorted(sessions, key=lambda item: item.updated_at, reverse=True)


def delete_session(session_id: str, store_dir: str | Path = SESSION_STORE_DIR) -> bool:
    """删除会话目录。"""
    try:
        session_dir = _session_dir(store_dir, session_id)
    except ValueError:
        return False
    if not session_dir.is_dir():
        return False
    shutil.rmtree(session_dir)
    return True


def session_exists(session_id: str, store_dir: str | Path = SESSION_STORE_DIR) -> bool:
    """判断会话是否存在。"""
    try:
        return (_session_dir(store_dir, session_id) / "state.json").is_file()
    except ValueError:
        return False


def _state_to_json(state: dict[str, Any]) -> dict[str, Any]:
    """将 Agent state 转为 JSON 可保存结构。"""
    payload = {}
    for key, value in state.items():
        if key == "messages" and isinstance(value, list):
            payload[key] = messages_to_dict(value)
        else:
            payload[key] = _json_safe(value)
    return payload


def _state_from_json(payload: dict[str, Any]) -> dict[str, Any]:
    """从 JSON 结构恢复 Agent state。"""
    state = dict(payload)
    raw_messages = state.get("messages", [])
    if isinstance(raw_messages, list):
        try:
            state["messages"] = messages_from_dict(raw_messages)
        except Exception:
            state["messages"] = []
    return state


def _write_messages_jsonl(path: Path, messages: list[Any]) -> None:
    """写入便于人工查看的消息日志。"""
    path.write_text(_messages_jsonl(messages), encoding="utf-8")


def _append_messages_jsonl(path: Path, messages: list[Any]) -> None:
    """追加归档消息日志。"""
    if not messages:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(_messages_jsonl(messages))


def _messages_jsonl(messages: list[Any]) -> str:
    """转换消息为 JSONL 文本。"""
    lines = []
    if isinstance(messages, list):
        for index, message in enumerate(messages, start=1):
            lines.append(
                json.dumps(
                    {
                        "index": index,
                        "role": _message_role(message),
                        "content": message_text(message),
                        "tool_calls": getattr(message, "tool_calls", []),
                        "tool_call_id": getattr(message, "tool_call_id", ""),
                    },
                    ensure_ascii=False,
                )
            )
    return "\n".join(lines) + ("\n" if lines else "")


def _message_role(message: Any) -> str:
    """获取消息角色。"""
    message_type = getattr(message, "type", "")
    mapping = {
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
        "system": "system",
    }
    return mapping.get(message_type, str(message_type or "unknown"))


def _json_safe(value: Any) -> Any:
    """把常见对象转换成 JSON 安全值。"""
    if isinstance(value, BaseMessage):
        return messages_to_dict([value])[0]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _build_title(user_inputs: list[str]) -> str:
    """根据第一条用户输入生成标题。"""
    if not user_inputs:
        return "新会话"
    title = " ".join(user_inputs[0].split())
    return title[:30] or "新会话"


def _session_dir(store_dir: str | Path, session_id: str) -> Path:
    """获取会话目录。"""
    _validate_session_id(session_id)
    return Path(store_dir).expanduser() / session_id


def _validate_session_id(session_id: str) -> None:
    """校验会话 ID，避免路径穿越。"""
    if not session_id or not SAFE_SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("非法会话 ID，仅允许字母、数字、下划线和短横线。")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """写入 JSON 文件。"""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    """生成秒级时间字符串。"""
    return datetime.now().isoformat(timespec="seconds")
