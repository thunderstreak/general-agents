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
        state["tool_errors"] = [{"tool_name": "get_weather", "success": False, "error": "权限拒绝"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "failed")
        self.assertEqual(result["last_error"]["type"], "reflection_error")

    def test_reflection_node_asks_user_for_missing_parameter(self):
        """参数缺失时进入追问响应。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="天气查询失败：用户没有提供城市，请提供城市名后再查询。", tool_call_id="tool_1")]
        state["tool_calls"] = [
            {
                "tool_name": "get_weather",
                "success": True,
                "result": "天气查询失败：用户没有提供城市，请提供城市名后再查询。",
            }
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "ask_user")
        self.assertEqual(result["reflection"]["next_action"], "response")
        self.assertEqual(result["reflection"]["missing_info"], "城市")
        self.assertEqual(result["last_error"], {})

    def test_reflection_node_retries_temporary_tool_error(self):
        """临时错误未超限时触发重试。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="失败", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "fetch_url", "success": False, "result": "timeout"}]
        state["tool_errors"] = [{"tool_name": "fetch_url", "success": False, "error": "timeout"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "retry")
        self.assertEqual(result["reflection"]["next_action"], "tools")
        self.assertEqual(result["reflection"]["retry_tool_name"], "fetch_url")
        self.assertEqual(result["reflection"]["retry_count"], 1)
        self.assertEqual(result["last_error"], {})

    def test_reflection_node_fails_after_retry_limit(self):
        """fetch_url 临时错误达到重试上限后 fallback 到搜索。"""
        state = base_state()
        state["reflection"] = {"retry_count": 1}
        state["messages"] = [ToolMessage(content="失败", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "fetch_url", "success": False, "result": "timeout"}]
        state["tool_errors"] = [{"tool_name": "fetch_url", "success": False, "error": "timeout"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "insufficient")
        self.assertEqual(result["reflection"]["next_action"], "planning")
        self.assertEqual(result["reflection"]["fallback_tool_name"], "web_search")
        self.assertEqual(result["reflection"]["stop_reason"], "retry_limit_exceeded")
        self.assertEqual(result["last_error"], {})

    def test_reflection_node_fails_after_retry_limit_without_fallback_loop(self):
        """已尝试 fallback 后不再重复切换同一工具。"""
        state = base_state()
        state["reflection"] = {"retry_count": 1}
        state["attempted_tools"] = ["fetch_url", "web_search"]
        state["messages"] = [ToolMessage(content="失败", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "fetch_url", "success": False, "result": "timeout"}]
        state["tool_errors"] = [{"tool_name": "fetch_url", "success": False, "error": "timeout"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "failed")
        self.assertEqual(result["reflection"]["stop_reason"], "retry_limit_exceeded")
        self.assertEqual(result["last_error"]["type"], "reflection_error")

    def test_reflection_node_marks_empty_result_insufficient(self):
        """web_search 空工具结果进入 insufficient response。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "web_search", "success": True, "result": ""}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "insufficient")
        self.assertEqual(result["reflection"]["next_action"], "response")

    def test_reflection_node_fallbacks_fetch_url_insufficient_to_search(self):
        """fetch_url 正文不足时 fallback 到 web_search。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="URL 抓取完成，但该内容类型不支持正文抓取", tool_call_id="tool_1")]
        state["tool_calls"] = [
            {
                "tool_name": "fetch_url",
                "success": True,
                "result": "URL 抓取完成，但该内容类型不支持正文抓取",
            }
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "insufficient")
        self.assertEqual(result["reflection"]["next_action"], "planning")
        self.assertEqual(result["reflection"]["fallback_tool_name"], "web_search")
        self.assertEqual(result["reflection"]["attempted_tools"], ["fetch_url"])

    def test_reflection_node_marks_max_steps_exceeded(self):
        """达到最大步骤时停止。"""
        state = base_state()
        state["step_count"] = state["max_steps"]
        state["messages"] = [ToolMessage(content="工具结果", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "get_weather", "success": True, "result": "晴"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "failed")
        self.assertEqual(result["reflection"]["stop_reason"], "max_steps_exceeded")

    def test_reflection_node_uses_latest_tool_batch(self):
        """重试成功后不被历史失败记录污染。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="最新工具结果", tool_call_id="tool_2")]
        state["tool_calls"] = [
            {"tool_name": "fetch_url", "success": False, "result": "timeout"},
            {"tool_name": "fetch_url", "success": True, "result": "最新工具结果"},
        ]
        state["tool_errors"] = [{"tool_name": "fetch_url", "success": False, "error": "timeout"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "passed")
        self.assertEqual(result["reflection"]["next_action"], "agent")


if __name__ == "__main__":
    unittest.main()
