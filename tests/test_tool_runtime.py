"""工具运行时测试。"""

import unittest
import requests

from agent_app.tools.runtime import (
    ERROR_MISSING_PARAMETER,
    ERROR_PERMISSION,
    ERROR_TEMPORARY,
    ERROR_UNSUPPORTED_CONTENT,
    RESULT_ASK_USER,
    RESULT_FAILED,
    RESULT_INSUFFICIENT,
    RESULT_OK,
    ToolMetadata,
    ToolRunRecord,
    run_tool,
)


class FakeTool:
    """可控结果的假工具。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def invoke(self, args):
        """模拟 LangChain tool invoke。"""
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ToolRuntimeTest(unittest.TestCase):
    """工具运行时白名单、重试和记录测试。"""

    def test_unregistered_tool_returns_failure_record(self):
        """未注册工具会被白名单拦截。"""
        record = run_tool("unknown", {}, {}, {})

        self.assertFalse(record.success)
        self.assertIn("工具未注册", record.result)
        self.assertEqual(record.attempts, 0)
        self.assertEqual(record.result_status, RESULT_FAILED)
        self.assertEqual(record.error_type, ERROR_PERMISSION)

    def test_retry_succeeds_after_first_failure(self):
        """工具失败后可按配置重试并记录成功。"""
        tool = FakeTool([RuntimeError("timeout"), "成功"])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具", max_retries=1)

        record = run_tool("demo", {"q": "x"}, {"demo": tool}, {"demo": metadata})

        self.assertTrue(record.success)
        self.assertEqual(record.result, "成功")
        self.assertEqual(record.result_status, RESULT_OK)
        self.assertEqual(record.attempts, 2)
        self.assertEqual(tool.calls, 2)

    def test_retry_failure_uses_standard_error_format(self):
        """重试耗尽后返回统一失败格式。"""
        tool = FakeTool([RuntimeError("boom"), RuntimeError("boom")])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具", max_retries=1)

        record = run_tool("demo", {}, {"demo": tool}, {"demo": metadata})

        self.assertFalse(record.success)
        self.assertIn("工具调用失败：demo：boom", record.result)
        self.assertEqual(record.error, "boom")
        self.assertEqual(record.result_status, RESULT_FAILED)
        self.assertEqual(record.attempts, 2)

    def test_success_record_contains_args_and_duration(self):
        """成功记录包含工具参数和耗时。"""
        tool = FakeTool(["ok"])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具")

        record = run_tool("demo", {"city": "长沙"}, {"demo": tool}, {"demo": metadata})

        self.assertTrue(record.success)
        self.assertEqual(record.tool_args, {"city": "长沙"})
        self.assertGreaterEqual(record.duration_ms, 0)

    def test_tool_run_record_to_dict_contains_structured_fields(self):
        """工具记录 JSON 包含结构化语义字段。"""
        record = ToolRunRecord(
            tool_name="fetch_url",
            tool_args={"url": "https://example.com/image.png"},
            success=True,
            result="不支持正文抓取",
            result_status=RESULT_INSUFFICIENT,
            error_type=ERROR_UNSUPPORTED_CONTENT,
            fallback_tool_names=["web_search"],
        )

        payload = record.to_dict()

        self.assertEqual(payload["result_status"], RESULT_INSUFFICIENT)
        self.assertEqual(payload["error_type"], ERROR_UNSUPPORTED_CONTENT)
        self.assertEqual(payload["fallback_tool_names"], ["web_search"])

    def test_timeout_exception_is_classified_as_temporary(self):
        """超时异常会标记为临时错误。"""
        tool = FakeTool([requests.Timeout("timeout")])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具", max_retries=0)

        record = run_tool("demo", {}, {"demo": tool}, {"demo": metadata})

        self.assertFalse(record.success)
        self.assertEqual(record.error_type, ERROR_TEMPORARY)
        self.assertTrue(record.is_retryable)

    def test_weather_missing_city_result_is_classified(self):
        """天气缺城市结果会标记为追问用户。"""
        tool = FakeTool(["天气查询失败：用户没有提供城市，且无法通过当前 IP 定位城市。请提供城市名后再查询。"])
        metadata = ToolMetadata(name="get_weather", category="weather", description="天气工具")

        record = run_tool("get_weather", {}, {"get_weather": tool}, {"get_weather": metadata})

        self.assertTrue(record.success)
        self.assertEqual(record.result_status, RESULT_ASK_USER)
        self.assertEqual(record.error_type, ERROR_MISSING_PARAMETER)
        self.assertEqual(record.missing_info, "城市")

    def test_fetch_url_unsupported_content_has_search_fallback(self):
        """URL 正文不足会标记 fallback 搜索。"""
        tool = FakeTool(["URL 抓取完成，但该内容类型不支持正文抓取：image/png"])
        metadata = ToolMetadata(name="fetch_url", category="fetch", description="URL 工具")

        record = run_tool("fetch_url", {}, {"fetch_url": tool}, {"fetch_url": metadata})

        self.assertEqual(record.result_status, RESULT_INSUFFICIENT)
        self.assertEqual(record.error_type, ERROR_UNSUPPORTED_CONTENT)
        self.assertEqual(record.fallback_tool_names, ["web_search"])

    def test_web_search_missing_query_result_is_classified(self):
        """搜索缺查询词会标记为追问用户。"""
        tool = FakeTool(["缺少搜索关键词。请提供要搜索的内容。"])
        metadata = ToolMetadata(name="web_search", category="search", description="网页搜索")

        record = run_tool("web_search", {}, {"web_search": tool}, {"web_search": metadata})

        self.assertEqual(record.result_status, RESULT_ASK_USER)
        self.assertEqual(record.error_type, ERROR_MISSING_PARAMETER)
        self.assertEqual(record.missing_info, "查询词")

    def test_web_search_missing_api_key_result_is_classified(self):
        """Tavily 配置错误会标记为权限配置问题。"""
        tool = FakeTool(["网页搜索配置错误：缺少 TAVILY_API_KEY。请在 .env 中配置 Tavily Search API key。"])
        metadata = ToolMetadata(name="web_search", category="search", description="网页搜索")

        record = run_tool("web_search", {}, {"web_search": tool}, {"web_search": metadata})

        self.assertEqual(record.result_status, RESULT_FAILED)
        self.assertEqual(record.error_type, ERROR_PERMISSION)


if __name__ == "__main__":
    unittest.main()
