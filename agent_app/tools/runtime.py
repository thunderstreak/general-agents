"""工具运行时：元数据、权限、日志、重试和错误格式。"""

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolMetadata:
    """工具元数据。"""

    name: str
    category: str
    description: str
    timeout_seconds: int = 10
    max_retries: int = 1
    requires_confirmation: bool = False
    trigger_keywords: tuple[str, ...] = ()


class ToolRuntimeError(RuntimeError):
    """工具运行时错误。"""


@dataclass
class ToolRunRecord:
    """工具执行记录。"""

    tool_name: str
    tool_args: dict[str, Any]
    success: bool
    result: str
    error: str = ""
    duration_ms: float = 0.0
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 LangGraph state 的字典。"""
        return asdict(self)


def run_tool(tool_name: str, tool_args: dict[str, Any], tools_by_name: dict[str, Any], tool_metadata_by_name: dict[str, ToolMetadata]) -> ToolRunRecord:
    """通过统一运行时执行工具。"""
    start_time = time.perf_counter()
    metadata = tool_metadata_by_name.get(tool_name)
    if metadata is None or tool_name not in tools_by_name:
        result = _format_tool_error(tool_name, "工具未注册或不在白名单中")
        return ToolRunRecord(tool_name=tool_name, tool_args=tool_args, success=False, result=result, error=result)

    if metadata.requires_confirmation:
        result = _format_tool_error(tool_name, "工具需要人工确认后才能执行")
        return ToolRunRecord(tool_name=tool_name, tool_args=tool_args, success=False, result=result, error=result)

    attempts = metadata.max_retries + 1
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            logger.info("tool_call_started", extra={"tool_name": tool_name, "tool_args": tool_args, "attempt": attempt})
            result = tools_by_name[tool_name].invoke(tool_args)
        except Exception as exc:
            last_error = exc
            logger.warning("tool_call_failed", extra={"tool_name": tool_name, "attempt": attempt, "error": str(exc)})
            if attempt >= attempts:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                result = _format_tool_error(tool_name, f"{exc}", duration_ms)
                return ToolRunRecord(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    success=False,
                    result=result,
                    error=str(exc),
                    duration_ms=duration_ms,
                    attempts=attempt,
                )
        else:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info("tool_call_succeeded", extra={"tool_name": tool_name, "attempt": attempt, "duration_ms": duration_ms})
            return ToolRunRecord(
                tool_name=tool_name,
                tool_args=tool_args,
                success=True,
                result=str(result),
                duration_ms=duration_ms,
                attempts=attempt,
            )

    result = _format_tool_error(tool_name, str(last_error))
    return ToolRunRecord(tool_name=tool_name, tool_args=tool_args, success=False, result=result, error=str(last_error))


def _format_tool_error(tool_name: str, message: str, duration_ms: float | None = None) -> str:
    """统一工具错误文本，便于模型理解。"""
    suffix = f"；耗时：{duration_ms}ms" if duration_ms is not None else ""
    return f"工具调用失败：{tool_name}：{message}{suffix}"
