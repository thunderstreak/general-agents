"""Reflection 节点测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage, ToolMessage

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
                "result_status": "ask_user",
                "error_type": "missing_parameter",
                "missing_info": "城市",
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
        state["tool_calls"] = [
            {
                "tool_name": "fetch_url",
                "success": False,
                "result": "timeout",
                "error": "timeout",
                "result_status": "failed",
                "error_type": "temporary",
                "is_retryable": True,
                "fallback_tool_names": ["web_search"],
            }
        ]
        state["tool_errors"] = [state["tool_calls"][0]]

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
        state["tool_calls"] = [
            {
                "tool_name": "fetch_url",
                "success": False,
                "result": "timeout",
                "error": "timeout",
                "result_status": "failed",
                "error_type": "temporary",
                "is_retryable": True,
                "fallback_tool_names": ["web_search"],
            }
        ]
        state["tool_errors"] = [state["tool_calls"][0]]

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
        state["tool_calls"] = [
            {
                "tool_name": "fetch_url",
                "success": False,
                "result": "timeout",
                "error": "timeout",
                "result_status": "failed",
                "error_type": "temporary",
                "is_retryable": True,
                "fallback_tool_names": ["web_search"],
            }
        ]
        state["tool_errors"] = [state["tool_calls"][0]]

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
                "result_status": "insufficient",
                "error_type": "unsupported_content",
                "fallback_tool_names": ["web_search"],
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

    def test_reflection_node_prefers_structured_missing_parameter(self):
        """结构化缺参字段优先于错误文案。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="opaque", tool_call_id="tool_1")]
        state["tool_calls"] = [
            {
                "tool_name": "get_weather",
                "success": True,
                "result": "opaque",
                "result_status": "ask_user",
                "error_type": "missing_parameter",
                "missing_info": "城市",
            }
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "ask_user")
        self.assertEqual(result["reflection"]["missing_info"], "城市")
        self.assertEqual(result["reflection"]["next_action"], "response")

    def test_reflection_node_prefers_structured_fallback(self):
        """结构化 fallback 字段优先于关键词判断。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="opaque", tool_call_id="tool_1")]
        state["tool_calls"] = [
            {
                "tool_name": "fetch_url",
                "success": True,
                "result": "opaque",
                "result_status": "insufficient",
                "error_type": "unsupported_content",
                "fallback_tool_names": ["web_search"],
            }
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "insufficient")
        self.assertEqual(result["reflection"]["next_action"], "planning")
        self.assertEqual(result["reflection"]["fallback_tool_name"], "web_search")

    def test_reflection_node_unstructured_success_record_passes(self):
        """缺少结构化字段的成功记录不再做文本关键词兼容。"""
        state = base_state()
        state["messages"] = [ToolMessage(content="URL 抓取完成，但该内容类型不支持正文抓取", tool_call_id="tool_1")]
        state["tool_calls"] = [{"tool_name": "fetch_url", "success": True, "result": "URL 抓取完成，但该内容类型不支持正文抓取"}]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "passed")
        self.assertEqual(result["reflection"]["next_action"], "agent")

    def test_reflection_node_retries_irrelevant_web_search_result(self):
        """web_search 结果不相关时调整查询重试。"""
        state = base_state()
        state["messages"] = [
            HumanMessage(content="今天金价"),
            ToolMessage(content="1. 今日 头条\n链接: https://www.toutiao.com/\n摘要: 新闻热点", tool_call_id="tool_1"),
        ]
        state["tool_calls"] = [
            {
                "tool_name": "web_search",
                "tool_args": {"query": "今日黄金价格 实时金价查询 2026年6月15日"},
                "success": True,
                "result": "1. 今日 头条\n链接: https://www.toutiao.com/\n摘要: 新闻热点",
                "result_status": "ok",
            }
        ]

        with patch("agent_app.nodes.reflection.emit_progress") as emit_progress:
            result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "retry")
        self.assertEqual(result["reflection"]["next_action"], "tools")
        self.assertEqual(result["last_tool_request"]["tool_calls"][0]["name"], "web_search")
        self.assertIn("今天金价", result["last_tool_request"]["tool_calls"][0]["args"]["query"])
        emit_progress.assert_any_call(
            "已搜索 1 次，但结果不匹配，正在调整关键词重试...",
            event="tool_retry",
            node="reflection",
            tool_name="web_search",
        )

    def test_reflection_node_stops_after_web_search_relevance_limit(self):
        """web_search 多次不相关后进入 response，不报 max_steps。"""
        state = base_state()
        state["step_count"] = state["max_steps"]
        state["messages"] = [
            HumanMessage(content="今天金价"),
            ToolMessage(content="1. 今日 头条\n链接: https://www.toutiao.com/\n摘要: 新闻热点", tool_call_id="tool_3"),
        ]
        state["tool_calls"] = [
            {
                "tool_name": "web_search",
                "tool_args": {"query": "今日黄金价格"},
                "success": True,
                "result": "1. 今日 头条\n链接: https://www.toutiao.com/\n摘要: 新闻热点",
                "result_status": "ok",
            },
            {
                "tool_name": "web_search",
                "tool_args": {"query": "今天金价 今日黄金价格 权威 实时 价格"},
                "success": True,
                "result": "1. 今日 热榜官网\n链接: https://tophub.today/\n摘要: 热榜",
                "result_status": "ok",
            },
            {
                "tool_name": "web_search",
                "tool_args": {"query": "今天金价 黄金 金价 XAU"},
                "success": True,
                "result": "1. 今日 头条\n链接: https://www.toutiao.com/\n摘要: 新闻热点",
                "result_status": "ok",
            },
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "insufficient")
        self.assertEqual(result["reflection"]["next_action"], "response")
        self.assertEqual(result["reflection"]["stop_reason"], "web_search_irrelevant_limit")
        self.assertEqual(result["last_error"], {})

    def test_reflection_node_passes_relevant_web_search_result(self):
        """web_search 结果包含领域关键词时正常总结。"""
        state = base_state()
        state["messages"] = [
            HumanMessage(content="今天金价"),
            ToolMessage(content="今日金价 实时更新，国内黄金价格 904.80 人民币/克", tool_call_id="tool_1"),
        ]
        state["tool_calls"] = [
            {
                "tool_name": "web_search",
                "tool_args": {"query": "今日黄金价格 实时金价查询 2026年6月15日"},
                "success": True,
                "result": "今日金价 实时更新，国内黄金价格 904.80 人民币/克",
                "result_status": "ok",
            }
        ]

        result = reflection_node(state)

        self.assertEqual(result["reflection"]["status"], "passed")
        self.assertEqual(result["reflection"]["next_action"], "agent")


if __name__ == "__main__":
    unittest.main()
