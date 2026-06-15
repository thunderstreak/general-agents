"""Perception 节点测试。"""

import unittest

from langchain_core.messages import HumanMessage

from agent_app.graph import perception_node
from tests.helpers import base_state


class PerceptionNodeTest(unittest.TestCase):
    """perception_node 行为测试。"""

    def test_perception_node_builds_text_context(self):
        """普通文本会生成标准 input_context。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="  你好   世界  ")]

        result = perception_node(state)

        context = result["input_context"]
        self.assertEqual(context["raw_text"], "  你好   世界  ")
        self.assertEqual(context["normalized_text"], "你好 世界")
        self.assertEqual(context["message_text"], "  你好   世界  ")
        self.assertFalse(context["has_image"])
        self.assertFalse(context["requires_vision"])

    def test_perception_node_extracts_file_attachment(self):
        """文件内容块会进入 attachments。"""
        state = base_state()
        state["messages"] = [
            HumanMessage(content="总结 [文件: docs/task-plan.md]\n\n[文件内容]\n路径：docs/task-plan.md\n类型：text\n内容：\nhello")
        ]

        result = perception_node(state)

        self.assertEqual(result["input_context"]["attachments"][0]["path"], "docs/task-plan.md")
        self.assertEqual(result["input_context"]["attachments"][0]["kind"], "text")

    def test_perception_node_extracts_file_errors(self):
        """文件解析失败块会进入 file_errors。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="[文件解析失败]\n路径：missing.md\n原因：文件不存在或不是普通文件。")]

        result = perception_node(state)

        self.assertEqual(result["input_context"]["file_errors"][0]["path"], "missing.md")
        self.assertIn("文件不存在", result["input_context"]["file_errors"][0]["error"])

    def test_perception_node_detects_image_message(self):
        """多模态图片消息会标记视觉需求。"""
        state = base_state()
        state["messages"] = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "识别图片\n\n[图片文件]\n路径：demo.png\n说明：图片已作为多模态输入附加。"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ]
            )
        ]

        result = perception_node(state)

        context = result["input_context"]
        self.assertTrue(context["has_image"])
        self.assertTrue(context["requires_vision"])
        self.assertEqual(context["attachments"][0]["kind"], "image")

    def test_perception_node_records_tool_and_rag_signals(self):
        """工具和 RAG 信号会进入 input_context。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答 LangGraph，并总结 https://example.com")]

        result = perception_node(state)

        context = result["input_context"]
        self.assertTrue(context["should_retrieve"])
        self.assertIn("rag", context["intent_signals"])
        self.assertIn("tool", context["intent_signals"])
        self.assertIn("url", context["intent_signals"])
        self.assertEqual(context["candidate_tool_names"], ["fetch_url"])


if __name__ == "__main__":
    unittest.main()
