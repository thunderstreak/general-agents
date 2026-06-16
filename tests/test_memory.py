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
            "schema_version": memory.MEMORY_SCHEMA_VERSION,
            "summary": "用户问过天气。",
            "items": [
                {
                    "id": "mem_profile",
                    "content": "用户名字是 张三",
                    "category": "profile",
                    "source": "user",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
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
        self.assertEqual(state["schema_version"], memory.MEMORY_SCHEMA_VERSION)
        self.assertTrue(all(item["id"].startswith("mem_") for item in state["items"]))
        self.assertIn("我叫小明", contents)
        self.assertIn("用户名字是 小明", contents)
        self.assertIn("用户：记住：我叫小明", state["summary"])

    def test_delete_memory_item(self):
        """按 ID 删除指定长期记忆。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_path = memory.MEMORY_FILE_PATH
            memory.MEMORY_FILE_PATH = str(Path(tmp_dir) / "memory.json")
            try:
                memory.save_memory(
                    memory.MemoryStore(
                        items=[
                            memory.MemoryItem(id="mem_keep", content="保留"),
                            memory.MemoryItem(id="mem_delete", content="删除"),
                        ],
                        summary="摘要",
                    )
                )
                self.assertTrue(memory.delete_memory_item("mem_delete"))
                store = memory.load_memory()
            finally:
                memory.MEMORY_FILE_PATH = old_path

        self.assertEqual([item.id for item in store.items], ["mem_keep"])
        self.assertEqual(store.summary, "摘要")

    def test_clear_memory(self):
        """清空长期记忆和摘要。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_path = memory.MEMORY_FILE_PATH
            memory.MEMORY_FILE_PATH = str(Path(tmp_dir) / "memory.json")
            try:
                memory.save_memory(memory.MemoryStore(items=[memory.MemoryItem(id="mem_1", content="记忆")], summary="摘要"))
                memory.clear_memory()
                store = memory.load_memory()
            finally:
                memory.MEMORY_FILE_PATH = old_path

        self.assertEqual(store.items, [])
        self.assertEqual(store.summary, "")


if __name__ == "__main__":
    unittest.main()
