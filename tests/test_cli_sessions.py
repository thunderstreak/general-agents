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
