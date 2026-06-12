"""文件夹式会话历史存储测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_app import session_store


class SessionStoreTest(unittest.TestCase):
    """会话存储基础行为测试。"""

    def test_create_session_writes_files(self):
        """创建新会话时写入目录和基础文件。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = session_store.create_session(tmp_dir)
            session_dir = Path(tmp_dir) / metadata.session_id

            self.assertTrue((session_dir / "metadata.json").is_file())
            self.assertTrue((session_dir / "state.json").is_file())
            self.assertTrue((session_dir / "messages.jsonl").is_file())

    def test_save_and_load_session_state(self):
        """保存后可恢复完整消息和关键 state 字段。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = session_store.create_session(tmp_dir)
            state = {
                "messages": [
                    HumanMessage(content="你好"),
                    AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "LangGraph"}, "id": "tool_1"}]),
                    ToolMessage(content="搜索结果", tool_call_id="tool_1"),
                    AIMessage(content="回答"),
                ],
                "pending_confirmation": {"tool_name": "web_search"},
                "long_term_memory": {"items": [{"content": "用户喜欢中文"}], "summary": "摘要"},
                "tool_calls": [{"tool_name": "web_search", "success": True}],
            }

            saved = session_store.save_session_state(metadata.session_id, state, tmp_dir)
            loaded = session_store.load_session_state(metadata.session_id, tmp_dir)

            self.assertEqual(saved.message_count, 4)
            self.assertEqual(loaded["messages"][0].content, "你好")
            self.assertEqual(loaded["messages"][2].content, "搜索结果")
            self.assertEqual(loaded["pending_confirmation"]["tool_name"], "web_search")
            self.assertEqual(loaded["long_term_memory"]["summary"], "摘要")

    def test_messages_jsonl_is_readable(self):
        """messages.jsonl 保存可读角色和内容。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = session_store.create_session(tmp_dir)
            session_store.save_session_state(
                metadata.session_id,
                {"messages": [HumanMessage(content="问题"), AIMessage(content="回答")]},
                tmp_dir,
            )

            lines = (Path(tmp_dir) / metadata.session_id / "messages.jsonl").read_text(encoding="utf-8").splitlines()
            payloads = [json.loads(line) for line in lines]

            self.assertEqual(payloads[0]["role"], "user")
            self.assertEqual(payloads[0]["content"], "问题")
            self.assertEqual(payloads[1]["role"], "assistant")
            self.assertEqual(payloads[1]["content"], "回答")

    def test_title_updates_from_first_user_message(self):
        """空会话保存后标题更新为第一条用户输入。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = session_store.create_session(tmp_dir)

            saved = session_store.save_session_state(metadata.session_id, {"messages": [HumanMessage(content="这是第一条问题")]}, tmp_dir)

            self.assertEqual(saved.title, "这是第一条问题")

    def test_list_sessions_orders_by_updated_at_desc(self):
        """会话列表按更新时间倒序。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            first = session_store.create_session(tmp_dir)
            second = session_store.create_session(tmp_dir)
            session_store.save_session_state(first.session_id, {"messages": [HumanMessage(content="旧")]}, tmp_dir)
            session_store.save_session_state(second.session_id, {"messages": [HumanMessage(content="新")]}, tmp_dir)
            first_payload = json.loads((Path(tmp_dir) / first.session_id / "metadata.json").read_text(encoding="utf-8"))
            first_payload["updated_at"] = "2026-01-01T00:00:00"
            (Path(tmp_dir) / first.session_id / "metadata.json").write_text(json.dumps(first_payload, ensure_ascii=False), encoding="utf-8")
            second_payload = json.loads((Path(tmp_dir) / second.session_id / "metadata.json").read_text(encoding="utf-8"))
            second_payload["updated_at"] = "2026-01-02T00:00:00"
            (Path(tmp_dir) / second.session_id / "metadata.json").write_text(json.dumps(second_payload, ensure_ascii=False), encoding="utf-8")

            sessions = session_store.list_sessions(tmp_dir)

            self.assertEqual(sessions[0].session_id, second.session_id)

    def test_delete_session_removes_directory(self):
        """删除会话会移除目录。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata = session_store.create_session(tmp_dir)

            self.assertTrue(session_store.delete_session(metadata.session_id, tmp_dir))
            self.assertFalse((Path(tmp_dir) / metadata.session_id).exists())


if __name__ == "__main__":
    unittest.main()
