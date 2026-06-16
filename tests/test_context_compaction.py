"""上下文压缩测试。"""

import unittest

from langchain_core.messages import AIMessage, HumanMessage

from agent_app.context_compaction import build_summary_context, compact_state, should_auto_compact
from tests.helpers import base_state


class ContextCompactionTest(unittest.TestCase):
    """上下文压缩行为测试。"""

    def test_compact_state_keeps_recent_turns_and_summarizes_old_messages(self):
        """压缩后保留最近若干轮并生成摘要。"""
        state = base_state()
        state["messages"] = _turns(6)

        result = compact_state(
            state,
            keep_turns=4,
            summarizer=lambda messages, previous, max_chars: f"{previous}\n摘要包含：{messages[0].content}".strip(),
        )

        self.assertEqual(len(result.kept_messages), 8)
        self.assertEqual(result.kept_messages[0].content, "问题 3")
        self.assertEqual(len(result.archived_messages), 4)
        self.assertIn("问题 1", result.summary)
        self.assertEqual(result.state["compact_count"], 1)
        self.assertEqual(result.state["messages"][0].content, "问题 3")

    def test_compact_state_falls_back_when_summarizer_fails(self):
        """摘要模型失败时回退到规则摘要。"""
        state = base_state()
        state["messages"] = _turns(5)

        def failing_summarizer(messages, previous, max_chars):
            raise RuntimeError("boom")

        result = compact_state(state, keep_turns=4, summarizer=failing_summarizer)

        self.assertIn("用户：问题 1", result.summary)
        self.assertIn("助手：回答 1", result.summary)

    def test_should_auto_compact_uses_message_threshold(self):
        """自动压缩按消息数阈值判断。"""
        state = base_state()
        state["messages"] = _turns(3)

        self.assertTrue(should_auto_compact(state, 6))
        self.assertFalse(should_auto_compact(state, 7))

    def test_build_summary_context_wraps_summary(self):
        """会话摘要会转换为 SystemMessage。"""
        message = build_summary_context("用户想实现上下文压缩。")

        self.assertIsNotNone(message)
        self.assertIn("[会话摘要]", message.content)
        self.assertIn("用户想实现上下文压缩", message.content)


def _turns(count: int):
    """构造多轮消息。"""
    messages = []
    for index in range(1, count + 1):
        messages.append(HumanMessage(content=f"问题 {index}"))
        messages.append(AIMessage(content=f"回答 {index}"))
    return messages


if __name__ == "__main__":
    unittest.main()
