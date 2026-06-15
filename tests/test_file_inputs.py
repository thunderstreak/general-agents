"""文件输入解析测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_app.file_inputs import parser


class FileInputsTest(unittest.TestCase):
    """文件输入解析基础行为测试。"""

    def test_parse_file_returns_error_for_missing_file(self):
        """不存在的文件会在进入模型前返回错误。"""
        result = parser.parse_file("/tmp/not-exists-for-agent.txt")

        self.assertEqual(result.kind, "error")
        self.assertIn("文件不存在", result.error)

    def test_parse_file_returns_error_for_unsupported_extension(self):
        """不支持的扩展名会返回明确错误。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.bin"
            path.write_bytes(b"data")

            result = parser.parse_file(str(path))

        self.assertEqual(result.kind, "error")
        self.assertIn("不支持的文件类型", result.error)

    def test_parse_file_rejects_oversized_file_before_reading(self):
        """超出大小限制的文件会被提前拦截。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "large.txt"
            path.write_text("0123456789", encoding="utf-8")

            with patch.object(parser, "MAX_FILE_SIZE_MB", 0):
                result = parser.parse_file(str(path))

        self.assertEqual(result.kind, "error")
        self.assertIn("文件过大", result.error)

    def test_parse_text_file_success(self):
        """普通文本文件可解析为文本内容。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.txt"
            path.write_text("你好", encoding="utf-8")

            result = parser.parse_file(str(path))

        self.assertEqual(result.kind, "text")
        self.assertEqual(result.content, "你好")
        self.assertEqual(result.error, "")


if __name__ == "__main__":
    unittest.main()
