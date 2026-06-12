"""LangGraph 路由测试。"""

import unittest

from langchain_core.messages import AIMessage, ToolCall

from agent_app.graph import after_tool_router, router
from tests.helpers import base_state


class GraphRouterTest(unittest.TestCase):
    """Graph 路由行为测试。"""

    def test_router_requires_confirmation(self):
        """需要确认的工具进入确认分支。"""
        state = base_state()
        tool_call = ToolCall(name="web_search", args={"query": "test"}, id="tool_1")
        state["messages"] = [AIMessage(content="", tool_calls=[tool_call])]

        from agent_app.graph import tool_metadata_by_name

        old_value = tool_metadata_by_name["web_search"].requires_confirmation
        object.__setattr__(tool_metadata_by_name["web_search"], "requires_confirmation", True)
        try:
            route = router(state)
        finally:
            object.__setattr__(tool_metadata_by_name["web_search"], "requires_confirmation", old_value)

        self.assertEqual(route, "confirm")

    def test_after_tool_router_goes_to_reflection(self):
        """工具执行后进入 reflection。"""
        self.assertEqual(after_tool_router(base_state()), "reflection")


if __name__ == "__main__":
    unittest.main()
