"""Agent state 初始化测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agent_app.state import create_initial_state, ensure_state_defaults, reset_turn_state


class AgentStateTest(unittest.TestCase):
    """state 工具函数测试。"""

    def test_create_initial_state_contains_required_fields(self):
        """初始 state 包含完整字段和长期记忆。"""
        with patch("agent_app.state.load_memory") as load_memory:
            load_memory.return_value.to_dict.return_value = {"items": [{"content": "偏好中文"}], "summary": "摘要"}

            state = create_initial_state()

        self.assertEqual(state["messages"], [])
        self.assertEqual(state["plan"], {})
        self.assertEqual(state["reflection"], {})
        self.assertEqual(state["long_term_memory"]["summary"], "摘要")
        self.assertIn("node_runs", state)

    def test_reset_turn_state_clears_turn_fields(self):
        """重置单轮字段但保留历史消息和长期记忆。"""
        state = create_initial_state(
            messages=[HumanMessage(content="你好")],
            long_term_memory={"summary": "保留"},
            plan={"mode": "tool"},
            reflection={"status": "passed"},
            retrieval_results=[{"source": "old"}],
            final_response={"content": "old"},
            approved_tool_call_ids=["tool_1"],
        )

        result = reset_turn_state(state)

        self.assertEqual(result["messages"][0].content, "你好")
        self.assertEqual(result["long_term_memory"], {"summary": "保留"})
        self.assertEqual(result["approved_tool_call_ids"], ["tool_1"])
        self.assertEqual(result["plan"], {})
        self.assertEqual(result["reflection"], {})
        self.assertEqual(result["retrieval_results"], [])
        self.assertEqual(result["final_response"], {})
        self.assertTrue(result["trace_id"])

    def test_ensure_state_defaults_fills_missing_fields(self):
        """旧会话 state 缺字段时自动补齐。"""
        state = ensure_state_defaults({"messages": [HumanMessage(content="旧会话")]})

        self.assertEqual(state["messages"][0].content, "旧会话")
        self.assertEqual(state["plan"], {})
        self.assertEqual(state["reflection"], {})
        self.assertIn("long_term_memory", state)


if __name__ == "__main__":
    unittest.main()
