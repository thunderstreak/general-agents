"""CLI 取消控制测试。"""

import unittest
from contextlib import redirect_stdout
import io
import threading
import time
from unittest.mock import patch

from agent_app import cancel as cli_cancel


class CliCancelTest(unittest.TestCase):
    """Esc 取消逻辑测试。"""

    def test_pure_esc_triggers_cancel(self):
        """纯 Esc 会触发取消。"""
        self.assertTrue(cli_cancel.should_cancel_from_chars("\x1b", has_pending=lambda: False))

    def test_arrow_sequence_does_not_trigger_cancel(self):
        """方向键 ESC sequence 不触发取消。"""
        self.assertFalse(cli_cancel.should_cancel_from_chars("\x1b", has_pending=lambda: True, read_next=lambda: "["))

    def test_escape_sequence_drains_remaining_chars(self):
        """已识别的 ESC sequence 会清理剩余字符。"""
        drained = []

        self.assertFalse(
            cli_cancel.should_cancel_from_chars(
                "\x1b",
                has_pending=lambda: True,
                read_next=lambda: "[",
                drain_remaining=lambda: drained.append("drained"),
            )
        )
        self.assertEqual(drained, ["drained"])

    def test_escape_with_non_sequence_suffix_triggers_cancel(self):
        """ESC 后接普通字符仍视为取消。"""
        self.assertTrue(cli_cancel.should_cancel_from_chars("\x1b", has_pending=lambda: True, read_next=lambda: "x"))

    def test_non_esc_does_not_trigger_cancel(self):
        """非 Esc 字符不触发取消。"""
        self.assertFalse(cli_cancel.should_cancel_from_chars("a", has_pending=lambda: False))

    def test_run_with_esc_cancel_converts_keyboard_interrupt(self):
        """KeyboardInterrupt 会转换为 TaskCancelled。"""
        with patch("agent_app.cancel.esc_cancel_listener"):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(cli_cancel.TaskCancelled):
                    cli_cancel.run_with_esc_cancel(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    def test_cancel_flag_raises_keyboard_interrupt(self):
        """取消标记会在检查点抛出 KeyboardInterrupt。"""
        cli_cancel.request_cancel()
        try:
            with self.assertRaises(KeyboardInterrupt):
                cli_cancel.raise_if_cancelled()
        finally:
            cli_cancel.clear_cancel_requested()

    def test_run_with_esc_cancel_clears_cancel_flag(self):
        """任务包装器结束后会清理取消标记。"""
        with patch("agent_app.cancel.esc_cancel_listener"):
            self.assertEqual(cli_cancel.run_with_esc_cancel(lambda: "ok"), "ok")

        self.assertFalse(cli_cancel.is_cancel_requested())

    def test_run_with_esc_cancel_worker_returns_result(self):
        """worker 执行器正常返回结果。"""
        with patch("agent_app.cancel.esc_cancel_listener"):
            self.assertEqual(cli_cancel.run_with_esc_cancel_worker(lambda: "ok"), "ok")

    def test_run_with_esc_cancel_worker_propagates_exception(self):
        """worker 执行器透传任务异常。"""
        with patch("agent_app.cancel.esc_cancel_listener"):
            with self.assertRaises(ValueError):
                cli_cancel.run_with_esc_cancel_worker(lambda: (_ for _ in ()).throw(ValueError("bad")))

    def test_wait_for_worker_cancels_without_waiting_for_blocked_worker(self):
        """worker 阻塞时取消等待应立即返回。"""
        started = threading.Event()
        release = threading.Event()
        worker = cli_cancel.WorkerResult()

        def slow_task():
            started.set()
            release.wait(1)

        thread = threading.Thread(target=cli_cancel._run_worker, args=(slow_task, worker), daemon=True)
        thread.start()
        started.wait(0.5)
        start_time = time.perf_counter()
        cli_cancel.request_cancel()
        try:
            with self.assertRaises(KeyboardInterrupt):
                cli_cancel._wait_for_worker(thread, worker)
        finally:
            release.set()
            cli_cancel.clear_cancel_requested()

        self.assertLess(time.perf_counter() - start_time, 0.2)

    def test_listener_ignores_ready_input_after_stop(self):
        """监听器停止后不再把就绪输入转换成取消。"""
        stop_event = threading.Event()
        select_calls = {"count": 0}
        read_calls = {"count": 0}

        def fake_select(*args):
            select_calls["count"] += 1
            if select_calls["count"] == 1:
                stop_event.set()
                return [object()], [], []
            return [], [], []

        with (
            patch("agent_app.cancel.select.select", side_effect=fake_select),
            patch("agent_app.cancel.sys.stdin.read", side_effect=lambda _: read_calls.__setitem__("count", read_calls["count"] + 1)),
            patch("agent_app.cancel.os.kill") as kill,
        ):
            cli_cancel._listen_for_esc(stop_event)

        kill.assert_not_called()
        self.assertEqual(read_calls["count"], 0)

    def test_listener_disabled_when_config_false(self):
        """配置关闭时不启用 Esc 监听。"""
        with patch("agent_app.cancel.CLI_ESC_CANCEL", False):
            self.assertFalse(cli_cancel._should_enable_esc_listener())


if __name__ == "__main__":
    unittest.main()
