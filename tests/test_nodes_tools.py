"""工具节点测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import ToolCall, ToolMessage

from agent_app.nodes.tools import tool_node
from agent_app.tools.runtime import ToolRunRecord
from tests.helpers import base_state


class ToolNodeTest(unittest.TestCase):
    """tool_node 行为测试。"""

    def test_tool_node_reuses_last_tool_request_for_retry(self):
        """reflection 触发重试时复用上一轮 tool_call。"""
        tool_call = ToolCall(name="fetch_url", args={"url": "https://example.com"}, id="tool_1")
        state = base_state()
        state["messages"] = [ToolMessage(content="timeout", tool_call_id="tool_1")]
        state["reflection"] = {"status": "retry", "next_action": "tools"}
        state["last_tool_request"] = {"tool_calls": [tool_call]}

        tool_run = ToolRunRecord(
            tool_name="fetch_url",
            tool_args={"url": "https://example.com"},
            success=True,
            result="抓取成功",
            attempts=1,
        )
        with patch("agent_app.nodes.tools.run_tool", return_value=tool_run) as run_tool:
            result = tool_node(state)

        run_tool.assert_called_once()
        self.assertEqual(result["messages"][0].content, "抓取成功")
        self.assertEqual(result["tool_calls"][0]["tool_name"], "fetch_url")
        self.assertNotIn("last_error", result)


if __name__ == "__main__":
    unittest.main()
