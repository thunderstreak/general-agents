"""节点共享辅助函数测试。"""

import unittest

from agent_app.nodes.common import merge_attempted_tools


class NodesCommonTest(unittest.TestCase):
    """nodes.common 行为测试。"""

    def test_merge_attempted_tools_keeps_order_and_removes_duplicates(self):
        """合并工具名时保持顺序并去重。"""
        state = {"attempted_tools": ["fetch_url", "", "web_search", "fetch_url", 123]}

        result = merge_attempted_tools(state, ["web_search", "get_weather", "", None])

        self.assertEqual(result, ["fetch_url", "web_search", "get_weather"])


if __name__ == "__main__":
    unittest.main()
