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

        with patch.object(cli, "CLI_STREAM", False), patch.object(cli, "app", fake_app):
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
        with patch.object(cli, "app", fake_app), patch.object(cli, "CLI_STREAM_PROGRESS", True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        output = buffer.getvalue()
        self.assertEqual(result, final_state)
        self.assertEqual(fake_app.kwargs["stream_mode"], ["messages", "updates", "custom", "values"])
        self.assertEqual(fake_app.kwargs["version"], "v2")
        self.assertIn("检索中...", output)
        self.assertIn("Agent: 你好", output)

    def test_stream_response_falls_back_when_no_tokens(self):
        """没有 token 时使用统一响应渲染。"""
        final_state = {
            "messages": [],
            "final_response": {"content": "需要确认", "retrieval_sources": [], "tool_calls": [], "tool_summary": [], "errors": []},
        }
        chunks = [{"type": "values", "data": final_state}]

        with patch.object(cli, "app", FakeStreamApp(chunks)):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli._stream_response({"messages": []})

        self.assertEqual(result, final_state)
        self.assertIn("Agent: 需要确认", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
