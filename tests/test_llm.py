"""LLM 调用测试。"""

import unittest
from unittest.mock import patch

from agent_app import cli_cancel, llm


class LlmTest(unittest.TestCase):
    """LLM 管理测试。"""

    def tearDown(self):
        """清理取消标记。"""
        cli_cancel.clear_cancel_requested()

    def test_invoke_with_fallback_checks_cancel_before_model_call(self):
        """取消后不应继续发起模型调用。"""
        cli_cancel.request_cancel()

        with patch("agent_app.llm.get_chat_model") as get_chat_model:
            with self.assertRaises(KeyboardInterrupt):
                llm.invoke_with_fallback([])

        get_chat_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
