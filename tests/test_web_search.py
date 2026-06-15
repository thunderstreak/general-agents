"""网页搜索工具测试。"""

import unittest
from unittest.mock import Mock, patch

import requests

from agent_app.tools.runtime import ERROR_TEMPORARY, ToolMetadata, run_tool
from agent_app.tools.web_search import _extract_results, _format_search_results, web_search


class WebSearchTest(unittest.TestCase):
    """Tavily 搜索工具测试。"""

    def test_web_search_returns_config_error_without_api_key(self):
        """缺少 Tavily API key 时返回明确配置错误。"""
        with patch("agent_app.tools.web_search.TAVILY_API_KEY", ""):
            result = web_search.invoke({"query": "OpenAI 最新消息"})

        self.assertIn("缺少 TAVILY_API_KEY", result)

    def test_web_search_returns_missing_query_message(self):
        """缺少查询词时返回明确提示。"""
        result = web_search.invoke({"query": ""})

        self.assertIn("缺少搜索关键词", result)

    def test_web_search_formats_tavily_results(self):
        """Tavily 正常结果会格式化为标题、链接和摘要。"""
        tavily = Mock()
        tavily.invoke.return_value = {
            "results": [
                {
                    "title": "OpenAI News",
                    "url": "https://example.com/openai",
                    "content": "OpenAI 发布了新消息。",
                }
            ]
        }

        with patch("agent_app.tools.web_search.TAVILY_API_KEY", "test-key"), patch(
            "agent_app.tools.web_search._create_tavily_search",
            return_value=tavily,
        ):
            result = web_search.invoke({"query": "OpenAI 最新消息"})

        self.assertIn("1. OpenAI News", result)
        self.assertIn("链接: https://example.com/openai", result)
        self.assertIn("摘要: OpenAI 发布了新消息。", result)
        tavily.invoke.assert_called_once_with({"query": "OpenAI 最新消息"})

    def test_web_search_returns_no_results_message(self):
        """Tavily 无结果时返回统一无结果文本。"""
        tavily = Mock()
        tavily.invoke.return_value = {"results": []}

        with patch("agent_app.tools.web_search.TAVILY_API_KEY", "test-key"), patch(
            "agent_app.tools.web_search._create_tavily_search",
            return_value=tavily,
        ):
            result = web_search.invoke({"query": "不存在的搜索词"})

        self.assertEqual(result, "未搜索到相关结果。")

    def test_tavily_timeout_is_temporary_in_runtime(self):
        """Tavily 超时异常会由运行时分类为临时错误。"""
        fake_tool = Mock()
        fake_tool.invoke.side_effect = requests.Timeout("timeout")
        metadata = ToolMetadata(name="web_search", category="search", description="网页搜索", max_retries=0)

        record = run_tool("web_search", {"query": "OpenAI"}, {"web_search": fake_tool}, {"web_search": metadata})

        self.assertFalse(record.success)
        self.assertEqual(record.error_type, ERROR_TEMPORARY)
        self.assertTrue(record.is_retryable)

    def test_extract_results_accepts_dict_or_list(self):
        """结果提取兼容 Tavily 字典和列表返回。"""
        results = [{"title": "A"}]

        self.assertEqual(_extract_results({"results": results}), results)
        self.assertEqual(_extract_results(results), results)
        self.assertEqual(_extract_results({"results": "bad"}), [])

    def test_format_search_results_respects_max_results(self):
        """结果格式化遵守最大结果数量。"""
        results = [
            {"title": "A", "url": "https://a.example", "content": "A"},
            {"title": "B", "url": "https://b.example", "content": "B"},
        ]

        with patch("agent_app.tools.web_search.WEB_SEARCH_MAX_RESULTS", 1):
            text = _format_search_results(results)

        self.assertIn("1. A", text)
        self.assertNotIn("2. B", text)


if __name__ == "__main__":
    unittest.main()
