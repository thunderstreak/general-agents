"""LangGraph 路由测试。"""

import unittest

from langchain_core.messages import AIMessage, ToolCall

from agent_app.graph import after_reflection_router, after_tool_router, build_graph, perception_node, router
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

    def test_after_reflection_router_uses_next_action(self):
        """reflection 可路由到多个下一步。"""
        for action in ("agent", "tools", "planning", "response", "error"):
            state = base_state()
            state["reflection"] = {"next_action": action}
            self.assertEqual(after_reflection_router(state), action)

    def test_after_reflection_router_prefers_last_error(self):
        """已有错误时进入 error。"""
        state = base_state()
        state["reflection"] = {"next_action": "tools"}
        state["last_error"] = {"message": "失败"}

        self.assertEqual(after_reflection_router(state), "error")

    def test_graph_exports_perception_and_compiles(self):
        """图包含 perception 入口节点并可编译。"""
        self.assertTrue(callable(perception_node))
        self.assertIsNotNone(build_graph())


if __name__ == "__main__":
    unittest.main()
