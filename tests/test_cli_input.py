"""CLI 输入层测试。"""

import builtins
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_app import cli


class CliInputTest(unittest.TestCase):
    """prompt_toolkit 输入封装测试。"""

    def test_read_user_input_uses_prompt_toolkit(self):
        """优先使用 prompt_toolkit 读取输入。"""
        prompt_toolkit = types.ModuleType("prompt_toolkit")
        history_module = types.ModuleType("prompt_toolkit.history")
        calls = {}

        def fake_prompt(label, **kwargs):
            calls["label"] = label
            calls["kwargs"] = kwargs
            return "中文输入"

        class FakeFileHistory:
            def __init__(self, path):
                self.path = path

        prompt_toolkit.prompt = fake_prompt
        history_module.FileHistory = FakeFileHistory

        with patch.dict(sys.modules, {"prompt_toolkit": prompt_toolkit, "prompt_toolkit.history": history_module}):
            result = cli._read_user_input()

        self.assertEqual(result, "中文输入")
        self.assertEqual(calls["label"], "你: ")
        self.assertFalse(calls["kwargs"]["complete_while_typing"])
        self.assertEqual(calls["kwargs"]["history"].path, cli.CLI_INPUT_HISTORY_FILE)

    def test_read_user_input_falls_back_to_input(self):
        """prompt_toolkit 不可用时回退 input。"""
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("prompt_toolkit"):
                raise ImportError("missing prompt_toolkit")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import), patch("builtins.input", return_value="fallback") as input_mock:
            result = cli._read_user_input()

        self.assertEqual(result, "fallback")
        input_mock.assert_called_once_with("你: ")

    def test_run_cli_reads_input_through_wrapper(self):
        """run_cli 使用 _read_user_input，而不是直接 input。"""
        with (
            patch("agent_app.cli.create_session") as create_session,
            patch("agent_app.cli.create_initial_state", return_value={"messages": []}),
            patch("agent_app.cli._save_current_session"),
            patch("agent_app.cli._read_user_input", return_value="quit") as read_user_input,
            patch("builtins.input", side_effect=AssertionError("不应直接调用 input")),
        ):
            create_session.return_value.session_id = "session"
            with redirect_stdout(io.StringIO()):
                cli.run_cli()

        read_user_input.assert_called_once()


if __name__ == "__main__":
    unittest.main()
