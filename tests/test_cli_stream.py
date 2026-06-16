"""CLI 流式输出测试。"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from langchain_core.messages import AIMessageChunk, ToolMessage

from agent_app import cli
from agent_app.cli import stream as cli_stream


class FakeInvokeApp:
    """只支持 invoke 的假图。"""

    def __init__(self):
        self.invoked = False

    def invoke(self, state):
        self.invoked = True
        return {**state, "final_response": {"content": "完成"}}


class FakeStreamApp:
    """只支持 stream 的假图。"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None

    def stream(self, state, **kwargs):
        self.kwargs = kwargs
        yield from self.chunks


class CliStreamTest(unittest.TestCase):
    """CLI stream chunk 解析与分支测试。"""

    def test_run_turn_uses_invoke_when_stream_disabled(self):
        """关闭流式时保留 invoke 执行路径。"""
        fake_app = FakeInvokeApp()

        with patch.object(cli, "CLI_STREAM", False), patch.object(cli, "get_app", return_value=fake_app):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._run_turn({"messages": []})

        self.assertTrue(fake_app.invoked)
        self.assertEqual(result["final_response"]["content"], "完成")
        self.assertIn("Agent: 完成", buffer.getvalue())

    def test_message_chunk_text_filters_empty_tool_and_nostream_chunks(self):
        """空内容、工具调用、工具消息和 nostream 内部模型不输出。"""
        self.assertEqual(cli_stream.message_chunk_text((AIMessageChunk(content=""), {})), "")
        self.assertEqual(cli_stream.message_chunk_text((AIMessageChunk(content="内部"), {"tags": ["nostream"]})), "")
        self.assertEqual(cli_stream.message_chunk_text((ToolMessage(content="工具结果", tool_call_id="tool_1"), {})), "")
        tool_chunk = AIMessageChunk(content="", tool_call_chunks=[{"name": "web_search", "args": "", "id": "1", "index": 0}])
        self.assertEqual(cli_stream.message_chunk_text((tool_chunk, {})), "")
        self.assertEqual(cli_stream.message_chunk_text((AIMessageChunk(content="你好"), {})), "你好")

    def test_stream_response_prints_progress_and_tokens(self):
        """流式输出进度和模型 token，并返回最终 state。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "你好"},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": False,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "custom", "data": {"message": "检索中..."}},
            {"type": "messages", "data": (AIMessageChunk(content="你"), {"tags": []})},
            {"type": "messages", "data": (AIMessageChunk(content="好"), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        fake_app = FakeStreamApp(chunks)
        with patch.object(cli, "get_app", return_value=fake_app), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertEqual(result, final_state)
        self.assertEqual(fake_app.kwargs["stream_mode"], ["messages", "updates", "custom", "values"])
        self.assertEqual(fake_app.kwargs["version"], "v2")
        self.assertIn("检索中...", output)
        self.assertIn("Agent: 你好", output)
        self.assertIn("处理中...", output)

    def test_update_progress_ignores_normal_chat_nodes(self):
        """普通节点 updates 不应显示检索、规划、思考等噪音进度。"""
        self.assertEqual(cli_stream.update_progress_message({"retrieval": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"planning": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"agent": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"memory": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"response": {}}), "")

    def test_update_progress_keeps_only_actionable_state_fallbacks(self):
        """只保留需要用户感知的状态兜底进度。"""
        self.assertEqual(cli_stream.update_progress_message({"confirm": {}}), "等待人工确认...")
        self.assertEqual(cli_stream.update_progress_message({"tools": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"reflection": {}}), "")
        self.assertEqual(cli_stream.update_progress_message({"error": {}}), "生成错误响应...")

    def test_stream_response_prints_tool_custom_progress(self):
        """工具 custom 事件仍应显示进度。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "完成"},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": False,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "custom", "data": {"message": "调用工具 get_weather..."}},
            {"type": "messages", "data": (AIMessageChunk(content="完成"), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertIn("调用工具 get_weather...", output)
        self.assertIn("Agent: 完成", output)

    def test_stream_response_hides_generic_tool_and_reflection_updates(self):
        """隐藏工具和反思兜底进度，保留具体 custom 进度。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "完成"},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": False,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "updates", "data": {"tools": {}}},
            {"type": "custom", "data": {"message": "调用工具 get_weather...", "node": "tools", "event": "tool_started"}},
            {"type": "custom", "data": {"message": "工具 get_weather 调用完成。", "node": "tools", "event": "tool_succeeded"}},
            {"type": "updates", "data": {"reflection": {}}},
            {"type": "custom", "data": {"message": "正在整理工具结果...", "node": "agent", "event": "summary_started"}},
            {"type": "messages", "data": (AIMessageChunk(content="完成"), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertNotIn("执行工具中...", output)
        self.assertNotIn("核对工具结果...", output)
        self.assertIn("调用工具 get_weather...", output)
        self.assertIn("工具 get_weather 调用完成。", output)
        self.assertIn("正在整理工具结果...", output)
        self.assertIn("Agent: 完成", output)

    def test_stream_response_prints_summary_progress_after_tool_done(self):
        """工具完成后仍显示总结阶段进度。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "最终总结"},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": False,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "custom", "data": {"message": "工具 get_weather_forecast 调用完成。"}},
            {"type": "custom", "data": {"message": "正在整理工具结果..."}},
            {"type": "messages", "data": (AIMessageChunk(content="不应显示"), {"tags": ["nostream"]})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertEqual(result, final_state)
        self.assertIn("工具 get_weather_forecast 调用完成。", output)
        self.assertIn("正在整理工具结果...", output)
        self.assertIn("Agent: 最终总结", output)
        self.assertNotIn("不应显示", output)

    def test_stream_response_hides_internal_memory_and_response_progress(self):
        """记忆和响应收尾进度不应打印给用户。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "完成"},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": True,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "custom", "data": {"message": "更新记忆...", "node": "memory", "event": "progress"}},
            {"type": "custom", "data": {"message": "整理响应...", "node": "response", "event": "progress"}},
            {"type": "messages", "data": (AIMessageChunk(content="完成"), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertNotIn("更新记忆...", output)
        self.assertNotIn("整理响应...", output)
        self.assertIn("Agent: 完成", output)

    def test_stream_response_hides_pseudo_tool_call_content(self):
        """流式伪工具调用不展示 XML 标签和参数内容。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "今日金价已查询。", "retrieval_sources": [], "tool_calls": [], "tool_summary": [], "errors": []},
            "tool_calls": [],
            "tool_errors": [],
            "retrieval_results": [],
            "last_error": {},
            "pending_confirmation": {},
            "memory_updated": False,
            "trace_id": "trace",
            "node_runs": [],
            "step_count": 1,
            "max_steps": 8,
        }
        chunks = [
            {"type": "messages", "data": (AIMessageChunk(content="<tool"), {"tags": []})},
            {"type": "messages", "data": (AIMessageChunk(content="_call>\n<function=web_search>\n"), {"tags": []})},
            {
                "type": "messages",
                "data": (
                    AIMessageChunk(content="<parameter=query>今日黄金价格 实时金价查询 2026年6月15日</parameter>\n"),
                    {"tags": []},
                ),
            },
            {"type": "messages", "data": (AIMessageChunk(content="<parameter=max_results>5</parameter>\n"), {"tags": []})},
            {"type": "messages", "data": (AIMessageChunk(content="</function>\n</tool_call>"), {"tags": []})},
            {"type": "custom", "data": {"message": "调用工具 web_search...", "node": "tools", "event": "tool_started"}},
            {"type": "custom", "data": {"message": "工具 web_search 调用完成。", "node": "tools", "event": "tool_succeeded"}},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertNotIn("今日黄金价格 实时金价查询 2026年6月15日", output)
        self.assertIn("调用工具 web_search...", output)
        self.assertIn("工具 web_search 调用完成。", output)
        self.assertIn("Agent: 今日金价已查询。", output)
        self.assertNotIn("<tool_call>", output)
        self.assertNotIn("<function=web_search>", output)
        self.assertNotIn("<parameter=query>", output)
        self.assertNotIn("max_results", output)

    def test_stream_response_falls_back_when_no_tokens(self):
        """没有 token 时使用统一响应渲染。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "需要确认", "retrieval_sources": [], "tool_calls": [], "tool_summary": [], "errors": []},
        }
        chunks = [{"type": "values", "data": final_state}]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        self.assertEqual(result, final_state)
        self.assertIn("Agent: 需要确认", buffer.getvalue())
        self.assertEqual(buffer.getvalue().count("Agent:"), 1)

    def test_stream_response_falls_back_when_only_blank_tokens(self):
        """只有空白 token 时使用最终响应兜底。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "最终回答", "retrieval_sources": [], "tool_calls": [], "tool_summary": [], "errors": []},
        }
        chunks = [
            {"type": "messages", "data": (AIMessageChunk(content="\n"), {"tags": []})},
            {"type": "messages", "data": (AIMessageChunk(content="   "), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        self.assertEqual(result, final_state)
        output = buffer.getvalue()
        self.assertIn("Agent: 最终回答", output)
        self.assertEqual(output.count("Agent:"), 1)

    def test_stream_response_prints_initial_status_before_first_chunk(self):
        """进入 stream 前立即输出临时状态而非 Agent 前缀。"""
        fake_app = FakeStreamApp([])

        buffer = io.StringIO()
        with patch.object(cli, "get_app", return_value=fake_app), redirect_stdout(buffer):
            result = cli._stream_response({"messages": []})

        self.assertEqual(result, {"messages": []})
        self.assertTrue(buffer.getvalue().startswith("处理中..."))
        self.assertFalse(buffer.getvalue().startswith("Agent: "))

    def test_stream_response_hides_initial_status_when_progress_disabled(self):
        """关闭进度时不显示临时状态。"""
        fake_app = FakeStreamApp([])

        buffer = io.StringIO()
        with patch.object(cli, "get_app", return_value=fake_app), patch.object(cli, "CLI_STREAM_PROGRESS", False), redirect_stdout(buffer):
            cli._stream_response({"messages": []})

        self.assertNotIn("处理中...", buffer.getvalue())

    def test_stream_response_clears_initial_status_on_cancel(self):
        """流式执行取消时清除临时状态。"""
        class CancelApp:
            def stream(self, state, **kwargs):
                raise KeyboardInterrupt()

        buffer = io.StringIO()
        with patch.object(cli, "get_app", return_value=CancelApp()), redirect_stdout(buffer):
            with self.assertRaises(KeyboardInterrupt):
                cli._stream_response({"messages": []})

        self.assertIn("\r\033[2K", buffer.getvalue())

    def test_stream_debug_tail_does_not_repeat_answer(self):
        """流式 debug 尾部不应重复打印回答正文。"""
        final_state = {
            "messages": [],
            "final_response": {
                "content": "回答内容",
                "retrieval_sources": [],
                "tool_calls": [],
                "tool_summary": [],
                "errors": [],
                "trace_id": "trace",
                "node_runs": [{"node_name": "planning", "success": True, "duration_ms": 1.0, "error": ""}],
            },
        }
        chunks = [
            {"type": "messages", "data": (AIMessageChunk(content="回答内容"), {"tags": []})},
            {"type": "values", "data": final_state},
        ]

        with patch.object(cli, "get_app", return_value=FakeStreamApp(chunks)), patch.object(cli, "OUTPUT_DEBUG", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertEqual(output.count("回答内容"), 1)
        self.assertIn("Debug:", output)
        self.assertIn("planning", output)
        self.assertLess(output.rindex("回答内容"), output.index("Debug:"))

    def test_debug_tail_waits_for_final_response(self):
        """没有 final_response 时不提前打印 debug。"""
        state = {
            "messages": [],
            "trace_id": "trace",
            "node_runs": [{"node_name": "agent", "success": True, "duration_ms": 1.0, "error": ""}],
        }

        with patch("agent_app.cli.stream.OUTPUT_DEBUG", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli_stream.print_debug_tail(state)

        self.assertNotIn("Debug:", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
