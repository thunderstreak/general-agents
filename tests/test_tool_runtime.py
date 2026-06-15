"""工具运行时测试。"""

import unittest

from agent_app.tools.runtime import ToolMetadata, run_tool


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

    def test_retry_succeeds_after_first_failure(self):
        """工具失败后可按配置重试并记录成功。"""
        tool = FakeTool([RuntimeError("timeout"), "成功"])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具", max_retries=1)

        record = run_tool("demo", {"q": "x"}, {"demo": tool}, {"demo": metadata})

        self.assertTrue(record.success)
        self.assertEqual(record.result, "成功")
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
        self.assertEqual(record.attempts, 2)

    def test_success_record_contains_args_and_duration(self):
        """成功记录包含工具参数和耗时。"""
        tool = FakeTool(["ok"])
        metadata = ToolMetadata(name="demo", category="test", description="测试工具")

        record = run_tool("demo", {"city": "长沙"}, {"demo": tool}, {"demo": metadata})

        self.assertTrue(record.success)
        self.assertEqual(record.tool_args, {"city": "长沙"})
        self.assertGreaterEqual(record.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
