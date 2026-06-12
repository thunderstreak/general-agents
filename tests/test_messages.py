"""消息辅助函数测试。"""

import unittest

from langchain_core.messages import HumanMessage

from agent_app.utils.messages import message_text


class MessageUtilsTest(unittest.TestCase):
    """message_text 行为测试。"""

    def test_message_text_reads_string_content(self):
        """字符串 content 直接返回。"""
        self.assertEqual(message_text(HumanMessage(content="你好")), "你好")

    def test_message_text_reads_list_text_parts(self):
        """多模态列表 content 只提取文本部分。"""
        message = HumanMessage(content=[{"type": "text", "text": "第一段"}, {"type": "image_url", "image_url": {"url": "x"}}])

        self.assertEqual(message_text(message), "第一段")

    def test_message_text_handles_none(self):
        """空消息返回空字符串。"""
        self.assertEqual(message_text(None), "")

    def test_message_text_stringifies_non_string_content(self):
        """非字符串 content 转为字符串。"""
        class FakeMessage:
            content = {"value": 1}

        self.assertEqual(message_text(FakeMessage()), "{'value': 1}")


if __name__ == "__main__":
    unittest.main()
