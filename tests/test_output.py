"""输出层测试。"""

import unittest

from langchain_core.messages import AIMessage

from agent_app.output import build_response, render_cli_response


def _state(content: str = "你好"):
    """构造基础输出 state。"""
    return {
        "messages": [AIMessage(content=content)],
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "last_error": {},
        "pending_confirmation": {},
        "memory_updated": False,
        "trace_id": "trace-1",
        "node_runs": [],
        "step_count": 1,
        "max_steps": 8,
        "clarification": {},
    }


class OutputTest(unittest.TestCase):
    """统一输出结构测试。"""

    def test_success_response(self):
        """普通成功响应。"""
        response = build_response(_state("完成"))

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["type"], "message")
        self.assertEqual(response["content"], "完成")

    def test_empty_success_response_has_visible_fallback(self):
        """成功但内容为空时给出可见兜底回答。"""
        response = build_response(_state(""))

        self.assertEqual(response["status"], "success")
        self.assertIn("没有生成可展示的回答", response["content"])

    def test_error_response(self):
        """错误响应。"""
        state = _state("执行失败")
        state["last_error"] = {"type": "tool_error", "message": "工具失败"}

        response = build_response(state)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["type"], "error")
        self.assertEqual(response["errors"][0]["message"], "工具失败")

    def test_confirmation_response(self):
        """确认响应。"""
        state = _state("需要确认")
        state["pending_confirmation"] = {"tool_name": "danger_tool", "message": "需要确认"}

        response = build_response(state)

        self.assertEqual(response["status"], "confirmation_required")
        self.assertEqual(response["type"], "confirmation")
        self.assertEqual(response["confirmation"]["tool_name"], "danger_tool")

    def test_build_response_includes_clarification_metadata(self):
        """输出结构包含 clarification metadata。"""
        state = _state("你想让我处理哪段内容？")
        state["clarification"] = {
            "question": "你想让我处理哪段内容？",
            "missing_info": "处理对象",
            "reason": "操作类请求缺少明确处理对象。",
        }

        response = build_response(state)

        self.assertEqual(response["metadata"]["clarification"]["missing_info"], "处理对象")
        self.assertIn("哪段内容", response["metadata"]["clarification"]["question"])

    def test_render_cli_response(self):
        """CLI 普通渲染。"""
        text = render_cli_response(build_response(_state("回答内容")))

        self.assertEqual(text, "Agent: 回答内容")

    def test_build_response_sanitizes_fake_tool_call_markup(self):
        """输出层会清理模型误吐的伪工具调用标签。"""
        content = (
            "长沙未来天气请参考工具结果。\n"
            "<tool_call>\n"
            "<function=search_internet>\n"
            "<parameter=query>长沙未来三天天气预报</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )

        response = build_response(_state(content))

        self.assertEqual(response["content"], "长沙未来天气请参考工具结果。")

    def test_render_cli_response_sanitizes_orphan_tool_call_tag(self):
        """CLI 渲染会清理孤立的伪工具调用结束标签。"""
        response = build_response(_state("回答</tool_call>"))

        text = render_cli_response(response)

        self.assertEqual(text, "Agent: 回答")

    def test_render_cli_debug_response(self):
        """CLI debug 渲染。"""
        state = _state("回答内容")
        state["tool_calls"] = [
            {
                "tool_name": "web_search",
                "success": True,
                "duration_ms": 10.5,
                "attempts": 1,
                "result_status": "ok",
                "error_type": "",
            }
        ]
        state["node_runs"] = [{"node_name": "agent", "success": True, "duration_ms": 20.0, "error": ""}]

        text = render_cli_response(build_response(state), debug=True)

        self.assertIn("trace_id: trace-1", text)
        self.assertIn("web_search", text)
        self.assertIn("result_status=ok", text)
        self.assertIn("agent", text)

    def test_render_cli_debug_includes_reflection(self):
        """CLI debug 渲染包含 reflection 摘要。"""
        state = _state("回答内容")
        state["reflection"] = {
            "status": "retry",
            "reason": "timeout",
            "next_action": "tools",
            "retry_count": 1,
            "fallback_tool_name": "web_search",
            "attempted_tools": ["fetch_url"],
            "loop_reason": "当前工具结果不足，切换到 web_search",
            "stop_reason": "",
        }

        text = render_cli_response(build_response(state), debug=True)

        self.assertIn("- reflection:", text)
        self.assertIn("status=retry", text)
        self.assertIn("next_action=tools", text)
        self.assertIn("fallback_tool=web_search", text)
        self.assertIn("attempted_tools=['fetch_url']", text)
        self.assertIn("reason=timeout", text)

    def test_build_response_includes_rag_source_metadata(self):
        """输出结构包含 RAG 来源 metadata。"""
        state = _state("回答内容")
        state["retrieval_results"] = [
            {
                "source": "/tmp/demo.md",
                "title": "demo.md",
                "document_id": "doc1",
                "chunk_id": "chunk1",
                "chunk_index": 0,
                "document_version": "v1",
                "page": "2",
                "sheet": "Sheet1",
                "score": 0.8,
                "vector_score": 0.7,
                "keyword_score": 0.5,
            }
        ]

        response = build_response(state)

        self.assertEqual(response["retrieval_sources"][0]["document_id"], "doc1")
        self.assertEqual(response["retrieval_sources"][0]["chunk_id"], "chunk1")
        self.assertEqual(response["retrieval_sources"][0]["page"], "2")
        self.assertEqual(response["retrieval_sources"][0]["sheet"], "Sheet1")
        self.assertEqual(response["retrieval_sources"][0]["vector_score"], 0.7)
        self.assertEqual(response["retrieval_sources"][0]["keyword_score"], 0.5)


if __name__ == "__main__":
    unittest.main()
