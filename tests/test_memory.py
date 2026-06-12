"""长期记忆测试。"""

import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from agent_app import memory


class MemoryTest(unittest.TestCase):
    """长期记忆基础行为测试。"""

    def test_extract_explicit_memory_items(self):
        """提取用户明确要求记住的信息。"""
        items = memory.extract_memory_items("请记住：我喜欢简洁的中文回答")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].content, "我喜欢简洁的中文回答")
        self.assertEqual(items[0].category, "explicit")
        self.assertEqual(items[1].content, "用户偏好：简洁的中文回答")

    def test_build_memory_context(self):
        """构造可注入模型的长期记忆上下文。"""
        memory_state = {
            "summary": "用户问过天气。",
            "items": [{"content": "用户名字是 张三", "category": "profile", "source": "user", "created_at": "2026-01-01T00:00:00"}],
        }

        context = memory.build_memory_context(memory_state)

        self.assertIn("历史摘要：用户问过天气。", context)
        self.assertIn("- 用户名字是 张三", context)

    def test_update_memory_from_turn_saves_file(self):
        """一轮对话后更新并保存长期记忆。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_path = memory.MEMORY_FILE_PATH
            memory.MEMORY_FILE_PATH = str(Path(tmp_dir) / "memory.json")
            try:
                state = memory.update_memory_from_turn(
                    {},
                    HumanMessage(content="记住：我叫小明"),
                    AIMessage(content="好的，我记住了。"),
                )
            finally:
                memory.MEMORY_FILE_PATH = old_path

        contents = [item["content"] for item in state["items"]]
        self.assertIn("我叫小明", contents)
        self.assertIn("用户名字是 小明", contents)
        self.assertIn("用户：记住：我叫小明", state["summary"])


if __name__ == "__main__":
    unittest.main()
