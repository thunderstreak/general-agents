"""CLI 流式输出测试。"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from langchain_core.messages import AIMessageChunk

from agent_app import cli


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
        """空内容、工具调用和 nostream 内部模型不输出。"""
        self.assertEqual(cli._message_chunk_text((AIMessageChunk(content=""), {})), "")
        self.assertEqual(cli._message_chunk_text((AIMessageChunk(content="内部"), {"tags": ["nostream"]})), "")
        tool_chunk = AIMessageChunk(content="", tool_call_chunks=[{"name": "web_search", "args": "", "id": "1", "index": 0}])
        self.assertEqual(cli._message_chunk_text((tool_chunk, {})), "")
        self.assertEqual(cli._message_chunk_text((AIMessageChunk(content="你好"), {})), "你好")

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

    def test_update_progress_ignores_normal_chat_nodes(self):
        """普通节点 updates 不应显示检索、规划、思考等噪音进度。"""
        self.assertEqual(cli._update_progress_message({"retrieval": {}}), "")
        self.assertEqual(cli._update_progress_message({"planning": {}}), "")
        self.assertEqual(cli._update_progress_message({"agent": {}}), "")
        self.assertEqual(cli._update_progress_message({"memory": {}}), "")
        self.assertEqual(cli._update_progress_message({"response": {}}), "")

    def test_update_progress_keeps_state_fallbacks(self):
        """确认、工具和错误节点仍保留兜底进度。"""
        self.assertEqual(cli._update_progress_message({"confirm": {}}), "等待人工确认...")
        self.assertEqual(cli._update_progress_message({"tools": {}}), "执行工具中...")
        self.assertEqual(cli._update_progress_message({"reflection": {}}), "核对工具结果...")
        self.assertEqual(cli._update_progress_message({"error": {}}), "生成错误响应...")

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


if __name__ == "__main__":
    unittest.main()
