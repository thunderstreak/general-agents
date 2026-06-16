"""CLI 会话命令测试。"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from agent_app import cli, session_store
from agent_app.context_compaction import ContextUsage
from agent_app.memory import MemoryItem, MemoryStore
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

    def test_rag_list_command_handles_legacy_metadata(self):
        """`/rag list` 遇到旧 metadata 时不崩溃。"""
        with patch("agent_app.cli.list_documents", return_value=[{"document_id": "doc1", "active": True, "updated_at": 1}]):
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

    def test_memory_list_command(self):
        """`/memory list` 显示长期记忆。"""
        store = MemoryStore(items=[MemoryItem(id="mem_1", content="用户喜欢中文", category="preference", created_at="2026-01-01T00:00:00")], summary="摘要")
        with patch("agent_app.cli.list_memory", return_value=store):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/memory list", {}, "current")

        self.assertTrue(handled)
        self.assertIn("历史摘要", buffer.getvalue())
        self.assertIn("memory_id=mem_1", buffer.getvalue())
        self.assertIn("用户喜欢中文", buffer.getvalue())

    def test_memory_list_summary_without_items_prints_no_deletable_items(self):
        """只有摘要时提示没有可删除条目。"""
        with patch("agent_app.cli.list_memory", return_value=MemoryStore(summary="摘要")):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/memory list", {}, "current")

        self.assertTrue(handled)
        self.assertIn("历史摘要", buffer.getvalue())
        self.assertIn("没有可删除的长期记忆条目", buffer.getvalue())

    def test_memory_delete_command(self):
        """`/memory delete` 删除指定长期记忆。"""
        with patch("agent_app.cli.delete_memory_item", return_value=True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/memory delete mem_1", {}, "current")

        self.assertTrue(handled)
        self.assertIn("已删除长期记忆：mem_1", buffer.getvalue())

    def test_memory_delete_missing_command(self):
        """`/memory delete` 删除不存在记忆时提示。"""
        with patch("agent_app.cli.delete_memory_item", return_value=False):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/memory delete missing", {}, "current")

        self.assertTrue(handled)
        self.assertIn("长期记忆不存在：missing", buffer.getvalue())

    def test_memory_clear_command(self):
        """`/memory clear` 清空长期记忆。"""
        with patch("agent_app.cli.clear_memory") as clear:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                handled, _, _, _ = cli._handle_cli_command("/memory clear", {}, "current")

        self.assertTrue(handled)
        clear.assert_called_once_with()
        self.assertIn("已清空长期记忆", buffer.getvalue())

    def test_memory_help_command(self):
        """`/memory` 显示帮助。"""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            handled, _, _, _ = cli._handle_cli_command("/memory", {}, "current")

        self.assertTrue(handled)
        self.assertIn("/memory list", buffer.getvalue())

    def test_run_turn_cancellable_raises_task_cancelled(self):
        """单轮执行取消时抛出 TaskCancelled。"""
        with patch("agent_app.cli._run_turn", side_effect=KeyboardInterrupt):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                with self.assertRaises(cli.TaskCancelled):
                    cli._run_turn_cancellable({"messages": []})

    def test_run_cli_input_keyboard_interrupt_continues(self):
        """输入阶段 Ctrl+C 不应打印 traceback 或退出异常。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                _patch_store_dir(tmp_dir),
                patch("agent_app.cli._read_user_input", side_effect=[KeyboardInterrupt(), "quit"]),
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    cli.run_cli()

        self.assertIn("已取消当前输入", buffer.getvalue())

    def test_compact_command_compacts_and_saves_session(self):
        """`/compact` 压缩当前会话并保存归档。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                metadata = session_store.create_session(tmp_dir)
                state = create_initial_state(messages=_turns(6))
                buffer = io.StringIO()
                with (
                    patch(
                        "agent_app.cli.estimate_context_usage",
                        side_effect=[
                            _token_usage(12, 23000, 2),
                            _token_usage(12, 23000, 2),
                            _token_usage(8, 15000, 2),
                        ],
                    ),
                    patch("agent_app.context_compaction.invoke_with_fallback", return_value=AIMessage(content="旧对话摘要")),
                    redirect_stdout(buffer),
                ):
                    handled, state, session_id, pending_delete = cli._handle_cli_command("/compact", state, metadata.session_id)

            archive_path = Path(tmp_dir) / metadata.session_id / "messages.archive.jsonl"
            self.assertTrue(handled)
            self.assertEqual(session_id, metadata.session_id)
            self.assertEqual(pending_delete, "")
            self.assertIn("已压缩上下文", buffer.getvalue())
            self.assertIn("当前上下文使用率：约 2%（23000/1000000 tokens", buffer.getvalue())
            self.assertIn("消息数 12 -> 8", buffer.getvalue())
            self.assertIn("token 使用率 2% -> 2%（23000 -> 15000 tokens）", buffer.getvalue())
            self.assertEqual(state["conversation_summary"], "旧对话摘要")
            self.assertEqual(len(state["messages"]), 8)
            self.assertIn("问题 1", archive_path.read_text(encoding="utf-8"))

    def test_compact_command_cancel_does_not_escape_command_handler(self):
        """`/compact` 取消后仍视为已处理。"""
        state = create_initial_state(messages=_turns(6))

        buffer = io.StringIO()
        with patch("agent_app.cli._run_cancellable", side_effect=cli.TaskCancelled("cancel")), redirect_stdout(buffer):
            handled, result_state, session_id, pending_delete = cli._handle_cli_command("/compact", state, "session")

        self.assertTrue(handled)
        self.assertIs(result_state, state)
        self.assertEqual(session_id, "session")
        self.assertEqual(pending_delete, "")

    def test_compact_show_command_prints_summary(self):
        """`/compact show` 显示当前会话摘要。"""
        state = create_initial_state(conversation_summary="摘要内容")

        buffer = io.StringIO()
        with patch("agent_app.cli.estimate_context_usage", return_value=_token_usage(0, 1200, 0)), redirect_stdout(buffer):
            handled, _, _, _ = cli._handle_cli_command("/compact show", state, "session")

        self.assertTrue(handled)
        self.assertIn("当前上下文使用率：约 0%（1200/1000000 tokens", buffer.getvalue())
        self.assertIn("摘要内容", buffer.getvalue())

    def test_compact_status_command_prints_usage(self):
        """`/compact status` 只显示上下文使用率。"""
        state = create_initial_state(messages=_turns(2))

        buffer = io.StringIO()
        with patch("agent_app.cli.estimate_context_usage", return_value=_token_usage(4, 23200, 2)), redirect_stdout(buffer):
            handled, result_state, session_id, pending_delete = cli._handle_cli_command("/compact status", state, "session")

        self.assertTrue(handled)
        self.assertIs(result_state, state)
        self.assertEqual(session_id, "session")
        self.assertEqual(pending_delete, "")
        self.assertIn("当前上下文使用率：约 2%（23200/1000000 tokens", buffer.getvalue())
        self.assertNotIn("当前会话摘要", buffer.getvalue())

    def test_compact_status_falls_back_to_message_usage(self):
        """token 统计不可用时显示消息数兜底。"""
        state = create_initial_state(messages=_turns(2))

        buffer = io.StringIO()
        with patch("agent_app.cli.estimate_context_usage", return_value=_message_usage(4, 10, 40)), redirect_stdout(buffer):
            handled, _, _, _ = cli._handle_cli_command("/compact usage", state, "session")

        self.assertTrue(handled)
        self.assertIn("当前上下文使用率：约 40%（4/10 条消息，token 统计不可用）", buffer.getvalue())

    def test_auto_compact_if_needed_saves_archive(self):
        """自动压缩达到阈值的会话。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_store_dir(tmp_dir):
                metadata = session_store.create_session(tmp_dir)
                state = create_initial_state(messages=_turns(6))
                buffer = io.StringIO()
                with (
                    patch("agent_app.cli.CONTEXT_COMPACT_ENABLED", True),
                    patch("agent_app.cli.CONTEXT_COMPACT_MESSAGE_THRESHOLD", 10),
                    patch(
                        "agent_app.cli.estimate_context_usage",
                        side_effect=[
                            _token_usage(12, 850000, 85),
                            _token_usage(8, 250000, 25),
                        ],
                    ),
                    patch("agent_app.context_compaction.invoke_with_fallback", return_value=AIMessage(content="自动摘要")),
                    redirect_stdout(buffer),
                ):
                    result = cli._auto_compact_if_needed(state, metadata.session_id)

            self.assertEqual(result["conversation_summary"], "自动摘要")
            self.assertIn("已自动压缩上下文", buffer.getvalue())
            self.assertIn("token 使用率 85% -> 25%（850000 -> 250000 tokens）", buffer.getvalue())
            archive_path = Path(tmp_dir) / metadata.session_id / "messages.archive.jsonl"
            self.assertIn("问题 1", archive_path.read_text(encoding="utf-8"))

    def test_auto_compact_cancel_returns_original_state(self):
        """自动压缩取消后保留原 state。"""
        state = create_initial_state(messages=_turns(6))
        with (
            patch("agent_app.cli.CONTEXT_COMPACT_ENABLED", True),
            patch("agent_app.cli.CONTEXT_COMPACT_MESSAGE_THRESHOLD", 10),
            patch("agent_app.cli._run_cancellable", side_effect=cli.TaskCancelled("cancel")),
        ):
            result = cli._auto_compact_if_needed(state, "session")

        self.assertIs(result, state)


def _patch_store_dir(tmp_dir: str):
    """patch CLI 和 store 使用临时目录。"""
    return patch.multiple(
        cli,
        create_session=lambda: session_store.create_session(tmp_dir),
        save_session_state=lambda session_id, state, archived_messages=None: session_store.save_session_state(
            session_id, state, tmp_dir, archived_messages=archived_messages
        ),
        list_sessions=lambda: session_store.list_sessions(tmp_dir),
        load_session_state=lambda session_id: session_store.load_session_state(session_id, tmp_dir),
        delete_session=lambda session_id: session_store.delete_session(session_id, tmp_dir),
        session_exists=lambda session_id: session_store.session_exists(session_id, tmp_dir),
    )


def _turns(count: int):
    """构造多轮消息。"""
    messages = []
    for index in range(1, count + 1):
        messages.append(HumanMessage(content=f"问题 {index}"))
        messages.append(AIMessage(content=f"回答 {index}"))
    return messages


def _token_usage(message_count: int, used_tokens: int, percent: int) -> ContextUsage:
    """构造 token 使用量。"""
    return ContextUsage(
        mode="token",
        message_count=message_count,
        threshold=40,
        percent=percent,
        token_available=True,
        used_tokens=used_tokens,
        context_window_tokens=1000000,
        reserved_output_tokens=4096,
        available_input_tokens=995904,
        remaining_tokens=max(0, 995904 - used_tokens),
    )


def _message_usage(message_count: int, threshold: int, percent: int) -> ContextUsage:
    """构造消息数使用量。"""
    return ContextUsage(mode="message", message_count=message_count, threshold=threshold, percent=percent)


if __name__ == "__main__":
    unittest.main()
