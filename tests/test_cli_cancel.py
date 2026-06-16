"""CLI 取消控制测试。"""

import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import patch

from agent_app import cli_cancel


class CliCancelTest(unittest.TestCase):
    """Esc 取消逻辑测试。"""

    def test_pure_esc_triggers_cancel(self):
        """纯 Esc 会触发取消。"""
        self.assertTrue(cli_cancel.should_cancel_from_chars("\x1b", has_pending=lambda: False))

    def test_arrow_sequence_does_not_trigger_cancel(self):
        """方向键 ESC sequence 不触发取消。"""
        self.assertFalse(cli_cancel.should_cancel_from_chars("\x1b", has_pending=lambda: True, read_next=lambda: "["))

    def test_non_esc_does_not_trigger_cancel(self):
        """非 Esc 字符不触发取消。"""
        self.assertFalse(cli_cancel.should_cancel_from_chars("a", has_pending=lambda: False))

    def test_run_with_esc_cancel_converts_keyboard_interrupt(self):
        """KeyboardInterrupt 会转换为 TaskCancelled。"""
        with patch("agent_app.cli_cancel.esc_cancel_listener"):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(cli_cancel.TaskCancelled):
                    cli_cancel.run_with_esc_cancel(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    def test_listener_disabled_when_config_false(self):
        """配置关闭时不启用 Esc 监听。"""
        with patch("agent_app.cli_cancel.CLI_ESC_CANCEL", False):
            self.assertFalse(cli_cancel._should_enable_esc_listener())


if __name__ == "__main__":
    unittest.main()
