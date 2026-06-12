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
    }


class OutputTest(unittest.TestCase):
    """统一输出结构测试。"""

    def test_success_response(self):
        """普通成功响应。"""
        response = build_response(_state("完成"))

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["type"], "message")
        self.assertEqual(response["content"], "完成")

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

    def test_render_cli_response(self):
        """CLI 普通渲染。"""
        text = render_cli_response(build_response(_state("回答内容")))

        self.assertEqual(text, "Agent: 回答内容")

    def test_render_cli_debug_response(self):
        """CLI debug 渲染。"""
        state = _state("回答内容")
        state["tool_calls"] = [{"tool_name": "web_search", "success": True, "duration_ms": 10.5, "attempts": 1}]
        state["node_runs"] = [{"node_name": "agent", "success": True, "duration_ms": 20.0, "error": ""}]

        text = render_cli_response(build_response(state), debug=True)

        self.assertIn("trace_id: trace-1", text)
        self.assertIn("web_search", text)
        self.assertIn("agent", text)


if __name__ == "__main__":
    unittest.main()
