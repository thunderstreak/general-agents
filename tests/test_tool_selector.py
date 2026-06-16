"""工具选择器测试。"""

import importlib
import unittest
from unittest.mock import patch

from agent_app.tool_selector import quick_chat_selection, should_enter_tool_mode
from agent_app.tools import candidate_tool_names_for_text


class ToolSelectorTest(unittest.TestCase):
    """工具选择器本地快速判断测试。"""

    def test_quick_chat_selection_matches_greeting(self):
        """明显问候直接返回 chat。"""
        selection = quick_chat_selection("你好")

        self.assertIsNotNone(selection)
        self.assertEqual(selection.action, "chat")

    def test_quick_chat_selection_matches_pinyin_greeting(self):
        """拼音问候直接返回 chat。"""
        selection = quick_chat_selection("nihao")

        self.assertIsNotNone(selection)
        self.assertEqual(selection.action, "chat")

    def test_quick_chat_selection_matches_thanks(self):
        """明显感谢直接返回 chat。"""
        selection = quick_chat_selection("谢谢")

        self.assertIsNotNone(selection)
        self.assertEqual(selection.action, "chat")

    def test_quick_chat_selection_ignores_weather(self):
        """天气问题不能被误判为普通对话。"""
        self.assertIsNone(quick_chat_selection("今天天气如何"))

    def test_quick_chat_selection_ignores_search(self):
        """搜索问题不能被误判为普通对话。"""
        self.assertIsNone(quick_chat_selection("搜索 LangGraph 最新消息"))

    def test_quick_chat_selection_ignores_mixed_intent(self):
        """包含问候但有明确任务时不能跳过工具选择。"""
        self.assertIsNone(quick_chat_selection("你好，帮我查一下天气"))

    def test_should_enter_tool_mode_ignores_plain_chat(self):
        """普通多语言问候不进入工具模式。"""
        self.assertFalse(should_enter_tool_mode("你好"))
        self.assertFalse(should_enter_tool_mode("hello"))
        self.assertFalse(should_enter_tool_mode("こんにちは"))

    def test_should_enter_tool_mode_detects_weather(self):
        """天气问题进入工具模式。"""
        self.assertTrue(should_enter_tool_mode("今天天气如何"))

    def test_should_enter_tool_mode_detects_search(self):
        """搜索问题进入工具模式。"""
        self.assertTrue(should_enter_tool_mode("搜索 LangGraph 最新消息"))

    def test_should_enter_tool_mode_detects_realtime_market(self):
        """实时市场类问题进入工具模式。"""
        self.assertTrue(should_enter_tool_mode("我想看今天的股票市场行情"))
        self.assertTrue(should_enter_tool_mode("做一个未来3-6个月的金价预测"))

    def test_should_enter_tool_mode_detects_rag_file_and_memory(self):
        """RAG、文件和记忆信号进入工具模式。"""
        self.assertTrue(should_enter_tool_mode("根据知识库回答 LangGraph 是什么"))
        self.assertTrue(should_enter_tool_mode("总结 [文件: docs/task-plan.md]"))
        self.assertTrue(should_enter_tool_mode("请记住我喜欢中文回答"))

    def test_should_enter_tool_mode_detects_url(self):
        """URL 输入进入工具模式。"""
        self.assertTrue(should_enter_tool_mode("总结 https://example.com 这篇文章"))
        self.assertTrue(should_enter_tool_mode("fetch url https://example.com"))

    def test_candidate_tools_detect_url_fetch_only(self):
        """URL 输入优先筛选 URL 抓取工具。"""
        self.assertEqual(candidate_tool_names_for_text("总结 https://example.com 这篇文章"), ["fetch_url"])

    def test_candidate_tools_detect_weather_only(self):
        """天气输入优先筛选天气工具。"""
        self.assertEqual(candidate_tool_names_for_text("今天天气如何"), ["get_weather"])

    def test_candidate_tools_detect_weather_forecast_only(self):
        """未来天气输入优先筛选天气预报工具。"""
        self.assertEqual(candidate_tool_names_for_text("长沙未来三天天气如何"), ["get_weather_forecast"])
        self.assertEqual(candidate_tool_names_for_text("未来3个月黄金预测"), ["web_search"])

    def test_candidate_tools_detect_market_search_only(self):
        """实时行情输入优先筛选网页搜索工具。"""
        self.assertEqual(candidate_tool_names_for_text("我想看今天的股票市场行情"), ["web_search"])
        self.assertEqual(candidate_tool_names_for_text("做一个未来3-6个月的金价预测"), ["web_search"])

    def test_tool_selector_import_does_not_initialize_model(self):
        """导入 tool_selector 时不初始化工具选择模型。"""
        import agent_app.tool_selector as tool_selector_module

        with patch(
            "agent_app.tool_selector.get_tool_selector_model",
            side_effect=AssertionError("不应导入时初始化模型"),
        ):
            reloaded = importlib.reload(tool_selector_module)

        self.assertIsNone(reloaded._selector_llm)


if __name__ == "__main__":
    unittest.main()
