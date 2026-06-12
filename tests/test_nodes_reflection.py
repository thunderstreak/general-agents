"""Reflection 节点测试。"""

import unittest

from langchain_core.messages import ToolMessage

from agent_app.graph import reflection_node
from tests.helpers import base_state


class ReflectionNodeTest(unittest.TestCase):
    """reflection_node 行为测试。"""

    def test_reflection_node_passes_successful_tool_results(self):
        """成功工具结果通过 reflection。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="工具结果", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "get_weather", "success": True, "result": "晴"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "passed")
        self.assertEqual(result["reflection"]["next_action"], "agent")

    def test_reflection_node_fails_tool_errors(self):
        """失败工具结果由 reflection 转为错误。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="失败", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "get_weather", "success": False, "result": "失败"}]
        state["tool_errors"] = [{"tool_name": "get_weather", "success": False, "error": "网络失败"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "failed")
        self.assertEqual(result["last_error"]["type"], "reflection_error")


if __name__ == "__main__":
    unittest.main()
