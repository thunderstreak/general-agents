"""CLI 任务取消控制。"""

from __future__ import annotations

import os
import select
import signal
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Generic, TypeVar

from agent_app.config import CLI_ESC_CANCEL

if os.name != "nt":
    import termios
    import tty
else:
    termios = None
    tty = None


T = TypeVar("T")
ESC = "\x1b"
ESC_SEQUENCE_PREFIXES = {"[", "O"}
_CANCEL_EVENT = threading.Event()
WORKER_POLL_INTERVAL_SECONDS = 0.03
ESC_SEQUENCE_GRACE_SECONDS = 0.12
ESC_SEQUENCE_DRAIN_SECONDS = 0.005
ESC_SEQUENCE_MAX_DRAIN_CHARS = 64


class TaskCancelled(RuntimeError):
    """当前 CLI 任务已取消。"""


def run_with_esc_cancel(fn: Callable[[], T], *, on_cancel_message: str = "已取消当前任务。") -> T:
    """执行任务，并允许运行中按 Esc 或 Ctrl+C 取消。"""
    clear_cancel_requested()
    try:
        with esc_cancel_listener():
            result = fn()
            raise_if_cancelled()
            return result
    except KeyboardInterrupt as exc:
        print(f"\n{on_cancel_message}\n")
        raise TaskCancelled(on_cancel_message) from exc
    finally:
        clear_cancel_requested()


def run_with_esc_cancel_worker(fn: Callable[[], T], *, on_cancel_message: str = "已取消当前任务。") -> T:
    """在 worker 线程中执行任务，主线程监听取消并立即返回。"""
    clear_cancel_requested()
    worker = WorkerResult[T]()
    thread = threading.Thread(target=_run_worker, args=(fn, worker), daemon=True)
    thread.start()
    try:
        with esc_cancel_listener():
            return _wait_for_worker(thread, worker)
    except KeyboardInterrupt as exc:
        request_cancel()
        print(f"\n{on_cancel_message}\n")
        raise TaskCancelled(on_cancel_message) from exc
    finally:
        if not thread.is_alive():
            clear_cancel_requested()


class WorkerResult(Generic[T]):
    """保存 worker 执行结果。"""

    def __init__(self) -> None:
        """初始化结果容器。"""
        self.value: T | None = None
        self.exception: BaseException | None = None


def request_cancel() -> None:
    """标记当前任务已请求取消。"""
    _CANCEL_EVENT.set()


def clear_cancel_requested() -> None:
    """清除当前任务取消标记。"""
    _CANCEL_EVENT.clear()


def is_cancel_requested() -> bool:
    """判断当前任务是否已请求取消。"""
    return _CANCEL_EVENT.is_set()


def raise_if_cancelled() -> None:
    """如果当前任务已请求取消，则抛出 KeyboardInterrupt。"""
    if is_cancel_requested():
        raise KeyboardInterrupt()


def _run_worker(fn: Callable[[], T], worker: WorkerResult[T]) -> None:
    """执行 worker 任务并记录结果。"""
    try:
        worker.value = fn()
    except BaseException as exc:
        worker.exception = exc


def _wait_for_worker(thread: threading.Thread, worker: WorkerResult[T]) -> T:
    """等待 worker 完成，并在取消时立即中断等待。"""
    while thread.is_alive():
        raise_if_cancelled()
        thread.join(WORKER_POLL_INTERVAL_SECONDS)
    if worker.exception:
        raise worker.exception
    raise_if_cancelled()
    return worker.value  # type: ignore[return-value]


@contextmanager
def esc_cancel_listener():
    """在支持的终端中临时启用 Esc 取消监听。"""
    if not _should_enable_esc_listener():
        yield
        return

    stop_event = threading.Event()
    if termios is None or tty is None:
        yield
        return
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    try:
        signal.siginterrupt(signal.SIGINT, True)
    except AttributeError:
        pass
    listener = threading.Thread(target=_listen_for_esc, args=(stop_event,), daemon=True)
    listener.start()
    try:
        yield
    finally:
        stop_event.set()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def should_cancel_from_chars(
    chars: str,
    *,
    has_pending: Callable[[], bool] | None = None,
    read_next: Callable[[], str] | None = None,
    drain_remaining: Callable[[], None] | None = None,
) -> bool:
    """判断读取到的字符是否代表纯 Esc。"""
    if chars != ESC:
        return False
    has_pending = has_pending or _stdin_has_pending
    read_next = read_next or (lambda: sys.stdin.read(1))
    if not has_pending():
        return True
    next_char = read_next()
    if next_char in ESC_SEQUENCE_PREFIXES:
        if drain_remaining is not None:
            drain_remaining()
        return False
    return True


def _listen_for_esc(stop_event: threading.Event) -> None:
    """后台监听 Esc，并触发 KeyboardInterrupt。"""
    while not stop_event.is_set():
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if not ready:
            continue
        char = sys.stdin.read(1)
        if should_cancel_from_chars(char, drain_remaining=_drain_pending_escape_sequence):
            request_cancel()
            os.kill(os.getpid(), signal.SIGINT)
            return


def _drain_pending_escape_sequence() -> None:
    """清理已识别 ESC 控制序列的剩余输入。"""
    drained = 0
    while drained < ESC_SEQUENCE_MAX_DRAIN_CHARS and _stdin_has_pending(ESC_SEQUENCE_DRAIN_SECONDS):
        sys.stdin.read(1)
        drained += 1


def _stdin_has_pending(timeout: float = ESC_SEQUENCE_GRACE_SECONDS) -> bool:
    """判断 stdin 是否有后续字符。"""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return bool(ready)


def _should_enable_esc_listener() -> bool:
    """判断当前环境是否可启用 Esc 监听。"""
    return bool(CLI_ESC_CANCEL and sys.stdin.isatty() and os.name != "nt")
