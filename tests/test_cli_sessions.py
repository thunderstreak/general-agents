"""CLI 会话命令测试。"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agent_app import cli, session_store
from agent_app.state import create_initial_state, reset_turn_state


class CliSessionCommandTest(unittest.TestCase):
    """CLI 会话管理命令测试。"""

    def test_new_command_creates_and_switches_session(self):
        """`/new` 创建并切换新会话。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                old = session_store.create_session(tmp_dir)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    handled, state, session_id, pending_delete = cli._handle_cli_command("/new", {"messages": []}, old.session_id)

            self.assertTrue(handled)
            self.assertNotEqual(session_id, old.session_id)
            self.assertEqual(state["messages"], [])
            self.assertEqual(pending_delete, "")
            self.assertTrue((Path(tmp_dir) / session_id).is_dir())

    def test_sessions_command_lists_sessions(self):
        """`/sessions` 打印历史会话。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                metadata = session_store.create_session(tmp_dir)
                session_store.save_session_state(metadata.session_id, {"messages": [HumanMessage(content="你好")]}, tmp_dir)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    handled, _, _, _ = cli._handle_cli_command("/sessions", {}, metadata.session_id)

            self.assertTrue(handled)
            self.assertIn(metadata.session_id, buffer.getvalue())

    def test_resume_command_loads_session(self):
        """`/resume <id>` 加载指定会话。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                metadata = session_store.create_session(tmp_dir)
                session_store.save_session_state(metadata.session_id, {"messages": [HumanMessage(content="旧会话")]}, tmp_dir)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    handled, state, session_id, pending_delete = cli._handle_cli_command(f"/resume {metadata.session_id}", {}, "current")

            self.assertTrue(handled)
            self.assertEqual(session_id, metadata.session_id)
            self.assertEqual(state["messages"][0].content, "旧会话")
            self.assertEqual(pending_delete, "")

    def test_delete_command_requires_confirmation(self):
        """`/delete <id>` 返回待确认会话 id。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                metadata = session_store.create_session(tmp_dir)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    handled, state, session_id, pending_delete = cli._handle_cli_command(f"/delete {metadata.session_id}", {}, "current")

            self.assertTrue(handled)
            self.assertEqual(state, {})
            self.assertEqual(session_id, "current")
            self.assertEqual(pending_delete, metadata.session_id)

    def test_default_start_creates_new_session_not_resume_old(self):
        """新建会话不会恢复旧 state。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            old = session_store.create_session(tmp_dir)
            session_store.save_session_state(old.session_id, {"messages": [HumanMessage(content="旧历史")]}, tmp_dir)
            new = session_store.create_session(tmp_dir)
            new_state = create_initial_state()

            self.assertNotEqual(new.session_id, old.session_id)
            self.assertEqual(new_state["messages"], [])
            self.assertEqual(new_state["plan"], {})
            self.assertEqual(new_state["reflection"], {})

    def test_reset_turn_state_clears_plan_and_reflection(self):
        """每轮开始时清空上一轮 plan 和 reflection。"""
        state = create_initial_state()
        state["plan"] = {"mode": "tool"}
        state["reflection"] = {"status": "passed"}
        state["retrieval_results"] = [{"source": "old"}]

        result = reset_turn_state(state)

        self.assertEqual(result["plan"], {})
        self.assertEqual(result["reflection"], {})
        self.assertEqual(result["retrieval_results"], [])

    def test_rag_list_command(self):
        """`/rag list` 打印知识库文档。"""
        with patch("agent_app.cli.list_documents", return_value=[{"document_id": "doc1", "title": "demo.md", "chunk_count": 2, "path": "/tmp/demo.md"}]):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/rag list", {}, "current")

        self.assertTrue(handled)
        self.assertIn("doc1", buffer.getvalue())

    def test_rag_add_command(self):
        """`/rag add` 导入知识库文档。"""
        document = {"document_id": "doc1", "title": "demo.md", "chunk_count": 2}
        with patch("agent_app.cli.add_document", return_value={"status": "added", "document": document}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/rag add demo.md", {}, "current")

        self.assertTrue(handled)
        self.assertIn("已导入", buffer.getvalue())

    def test_rag_command_cancel_does_not_escape_command_handler(self):
        """RAG 命令取消后仍视为已处理。"""
        with patch("agent_app.cli._handle_rag_command", side_effect=cli.TaskCancelled("cancel")):
            handled, state, session_id, pending_delete = cli._handle_cli_command("/rag add demo.md", {"messages": []}, "session")

        self.assertTrue(handled)
        self.assertEqual(state, {"messages": []})
        self.assertEqual(session_id, "session")
        self.assertEqual(pending_delete, "")

    def test_rag_sync_command(self):
        """`/rag sync` 同步知识库。"""
        summary = {"checked": 1, "updated": 1, "unchanged": 0, "missing": 0, "failed": 0}
        with patch("agent_app.cli.sync_knowledge_base", return_value=summary):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/rag sync", {}, "current")

        self.assertTrue(handled)
        self.assertIn("知识库同步完成", buffer.getvalue())

    def test_rag_rebuild_command(self):
        """`/rag rebuild` 重建知识库索引。"""
        summary = {"checked": 1, "rebuilt": 1, "missing": 0, "failed": 0}
        with patch("agent_app.cli.rebuild_knowledge_base", return_value=summary):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/rag rebuild", {}, "current")

        self.assertTrue(handled)
        self.assertIn("知识库重建完成", buffer.getvalue())

    def test_run_turn_cancellable_raises_task_cancelled(self):
        """单轮执行取消时抛出 TaskCancelled。"""
        with patch("agent_app.cli._run_turn", side_effect=KeyboardInterrupt):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                with self.assertRaises(cli.TaskCancelled):
                    cli._run_turn_cancellable({"messages": []})


def _patch_store_dir(tmp_dir: str):
    """patch CLI 和 store 使用临时目录。"""
    return patch.multiple(
        cli,
        create_session=lambda: session_store.create_session(tmp_dir),
        save_session_state=lambda session_id, state: session_store.save_session_state(session_id, state, tmp_dir),
        list_sessions=lambda: session_store.list_sessions(tmp_dir),
        load_session_state=lambda session_id: session_store.load_session_state(session_id, tmp_dir),
        delete_session=lambda session_id: session_store.delete_session(session_id, tmp_dir),
        session_exists=lambda session_id: session_store.session_exists(session_id, tmp_dir),
    )


if __name__ == "__main__":
    unittest.main()
