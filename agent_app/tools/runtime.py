"""工具运行时：元数据、权限、日志、重试和错误格式。"""

import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Any


logger = logging.getLogger(__name__)

RESULT_OK = "ok"
RESULT_INSUFFICIENT = "insufficient"
RESULT_ASK_USER = "ask_user"
RESULT_FAILED = "failed"

ERROR_TEMPORARY = "temporary"
ERROR_MISSING_PARAMETER = "missing_parameter"
ERROR_SECURITY_BLOCKED = "security_blocked"
ERROR_UNSUPPORTED_INPUT = "unsupported_input"
ERROR_UNSUPPORTED_CONTENT = "unsupported_content"
ERROR_NO_RESULTS = "no_results"
ERROR_PERMISSION = "permission"
ERROR_UNKNOWN = "unknown"


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
    result_status: str = ""
    error_type: str = ""
    missing_info: str = ""
    is_retryable: bool = False
    fallback_tool_names: list[str] = field(default_factory=list)

    def __post_init__(self):
        """补齐旧调用方式未显式传入的结构化字段。"""
        if not self.result_status:
            self.result_status = RESULT_OK if self.success else RESULT_FAILED
        if not self.error_type and not self.success:
            self.error_type = ERROR_UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 LangGraph state 的字典。"""
        return asdict(self)


def run_tool(tool_name: str, tool_args: dict[str, Any], tools_by_name: dict[str, Any], tool_metadata_by_name: dict[str, ToolMetadata]) -> ToolRunRecord:
    """通过统一运行时执行工具。"""
    start_time = time.perf_counter()
    metadata = tool_metadata_by_name.get(tool_name)
    if metadata is None or tool_name not in tools_by_name:
        result = _format_tool_error(tool_name, "工具未注册或不在白名单中")
        return ToolRunRecord(
            tool_name=tool_name,
            tool_args=tool_args,
            success=False,
            result=result,
            error=result,
            result_status=RESULT_FAILED,
            error_type=ERROR_PERMISSION,
            is_retryable=False,
        )

    if metadata.requires_confirmation:
        result = _format_tool_error(tool_name, "工具需要人工确认后才能执行")
        return ToolRunRecord(
            tool_name=tool_name,
            tool_args=tool_args,
            success=False,
            result=result,
            error=result,
            result_status=RESULT_FAILED,
            error_type=ERROR_PERMISSION,
            is_retryable=False,
        )

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
                classification = classify_tool_error(tool_name, str(exc))
                return ToolRunRecord(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    success=False,
                    result=result,
                    error=str(exc),
                    duration_ms=duration_ms,
                    attempts=attempt,
                    **classification,
                )
        else:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info("tool_call_succeeded", extra={"tool_name": tool_name, "attempt": attempt, "duration_ms": duration_ms})
            classification = classify_tool_result(tool_name, str(result))
            return ToolRunRecord(
                tool_name=tool_name,
                tool_args=tool_args,
                success=True,
                result=str(result),
                duration_ms=duration_ms,
                attempts=attempt,
                **classification,
            )

    result = _format_tool_error(tool_name, str(last_error))
    classification = classify_tool_error(tool_name, str(last_error))
    return ToolRunRecord(tool_name=tool_name, tool_args=tool_args, success=False, result=result, error=str(last_error), **classification)


def _format_tool_error(tool_name: str, message: str, duration_ms: float | None = None) -> str:
    """统一工具错误文本，便于模型理解。"""
    suffix = f"；耗时：{duration_ms}ms" if duration_ms is not None else ""
    return f"工具调用失败：{tool_name}：{message}{suffix}"


def classify_tool_error(tool_name: str, message: str) -> dict[str, Any]:
    """将异常或运行时错误归类为结构化工具语义。"""
    error_type = _classify_error_type(message)
    return {
        "result_status": RESULT_FAILED,
        "error_type": error_type,
        "missing_info": _missing_info_from_text(message),
        "is_retryable": error_type == ERROR_TEMPORARY,
        "fallback_tool_names": _fallback_tools_for_error(tool_name, error_type),
    }


def classify_tool_result(tool_name: str, result: str) -> dict[str, Any]:
    """将工具字符串结果归类为结构化语义，兼容现有工具返回值。"""
    text = str(result or "")
    error_type = _classify_tool_result_error_type(tool_name, text)
    if error_type == "":
        return {
            "result_status": RESULT_OK,
            "error_type": "",
            "missing_info": "",
            "is_retryable": False,
            "fallback_tool_names": [],
        }

    status = RESULT_FAILED
    if error_type == ERROR_MISSING_PARAMETER:
        status = RESULT_ASK_USER
    elif error_type in {ERROR_UNSUPPORTED_CONTENT, ERROR_NO_RESULTS}:
        status = RESULT_INSUFFICIENT

    return {
        "result_status": status,
        "error_type": error_type,
        "missing_info": _missing_info_from_text(text),
        "is_retryable": error_type == ERROR_TEMPORARY,
        "fallback_tool_names": _fallback_tools_for_error(tool_name, error_type),
    }


def _classify_tool_result_error_type(tool_name: str, text: str) -> str:
    """按工具返回文本推导错误类型。"""
    lowered = text.lower()
    if not text.strip():
        return ERROR_NO_RESULTS if tool_name == "web_search" else ERROR_UNKNOWN
    if "没有提供城市" in text or "请提供城市" in text or "缺少 hostname" in lowered or "missing" in lowered or "required" in lowered:
        return ERROR_MISSING_PARAMETER
    if "禁止访问 localhost" in text or "内网地址" in text or "metadata 地址" in text:
        return ERROR_SECURITY_BLOCKED
    if "仅支持 http:// 或 https://" in text:
        return ERROR_UNSUPPORTED_INPUT
    if "不支持正文抓取" in text or "未提取到正文文本" in text:
        return ERROR_UNSUPPORTED_CONTENT
    if "未搜索到相关结果" in text or "无搜索结果" in text or "没有搜索结果" in text:
        return ERROR_NO_RESULTS
    if "网页搜索失败" in text and "未解析到搜索结果" in text:
        return ERROR_NO_RESULTS
    if "失败" in text or "error" in lowered or "failed" in lowered:
        return _classify_error_type(text)
    return ""


def _classify_error_type(message: str) -> str:
    """按通用错误文本推导错误类型。"""
    lowered = str(message or "").lower()
    if any(keyword in lowered for keyword in ("timeout", "timed out", "connection", "temporarily", "temporary", "502", "503", "504", "5xx")):
        return ERROR_TEMPORARY
    if "超时" in message or "网络" in message:
        return ERROR_TEMPORARY
    if any(keyword in lowered for keyword in ("api key", "permission", "forbidden", "unauthorized")) or "权限" in message:
        return ERROR_PERMISSION
    if "禁止访问 localhost" in message or "内网地址" in message or "metadata 地址" in message:
        return ERROR_SECURITY_BLOCKED
    if "仅支持 http:// 或 https://" in message:
        return ERROR_UNSUPPORTED_INPUT
    if "不支持正文抓取" in message or "未提取到正文文本" in message:
        return ERROR_UNSUPPORTED_CONTENT
    if "未搜索到相关结果" in message or "无搜索结果" in message or "没有搜索结果" in message:
        return ERROR_NO_RESULTS
    if "没有提供城市" in message or "请提供城市" in message or "缺少 hostname" in lowered:
        return ERROR_MISSING_PARAMETER
    return ERROR_UNKNOWN


def _missing_info_from_text(text: str) -> str:
    """根据错误文本推断缺失信息。"""
    lowered = str(text or "").lower()
    if "城市" in lowered:
        return "城市"
    if "url" in lowered or "hostname" in lowered or "链接" in lowered:
        return "URL"
    if "query" in lowered or "查询" in lowered or "搜索" in lowered:
        return "查询词"
    return ""


def _fallback_tools_for_error(tool_name: str, error_type: str) -> list[str]:
    """根据工具和错误类型返回可尝试的 fallback 工具。"""
    if tool_name == "fetch_url" and error_type in {ERROR_TEMPORARY, ERROR_UNSUPPORTED_CONTENT, ERROR_NO_RESULTS, ERROR_UNKNOWN}:
        return ["web_search"]
    return []
