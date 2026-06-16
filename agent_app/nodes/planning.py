"""Planning 节点与 plan 辅助函数。"""

import re
import time
from urllib.parse import urlparse

from agent_app.nodes.common import latest_human_message, node_run
from agent_app.state import AgentState
from agent_app.tool_selector import ToolSelection, select_plan
from agent_app.tools import candidate_tool_names_for_text
from agent_app.utils.messages import message_text


def planning_node(state: AgentState):
    """生成单轮结构化执行计划。"""
    start_time = time.perf_counter()
    messages = state["messages"]
    if messages and hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
        return {
            "plan": auto_plan("已有待执行工具调用，跳过规划"),
            "node_runs": [node_run("planning", start_time)],
        }

    reflection = state.get("reflection") or {}
    fallback_tool_name = reflection.get("fallback_tool_name")
    if reflection.get("next_action") == "planning" and fallback_tool_name:
        selection = fallback_tool_selection(str(fallback_tool_name), reflection)
        return {
            "tool_selection": selection.to_dict(),
            "plan": selection_to_plan(selection),
            "node_runs": [node_run("planning", start_time)],
        }

    latest_message = latest_human_message(state["messages"])
    input_context = state.get("input_context") or {}
    user_text = input_context.get("normalized_text") or message_text(latest_message)

    selection = planning_selection(user_text, bool(latest_message), input_context)
    plan = selection_to_plan(selection)
    return {
        "tool_selection": selection.to_dict(),
        "plan": plan,
        "node_runs": [node_run("planning", start_time)],
    }


def planning_selection(user_text: str, has_user_message: bool, input_context: dict | None = None) -> ToolSelection:
    """根据 hard guard 和结构化 planner 生成规划选择。"""
    if not has_user_message:
        return ToolSelection(action="auto", reason="没有找到用户消息")
    input_context = input_context or {}
    candidate_tool_names = input_context.get("candidate_tool_names")
    if (input_context or {}).get("should_retrieve") and not _asks_external_info(user_text):
        return ToolSelection(action="chat", confidence=1.0, reason="本地判断：使用知识库检索上下文回答")
    hard_guard_selection = deterministic_selection(user_text, input_context, candidate_tool_names or [])
    if hard_guard_selection:
        return hard_guard_selection
    clarification = clarification_decision(user_text, input_context, candidate_tool_names or [])
    if clarification:
        return ToolSelection(action="clarification", args=clarification, confidence=1.0, reason="本地判断：需要澄清")
    planner_selection = select_plan(user_text, input_context)
    if planner_selection.action == "auto":
        return ToolSelection(action="chat", confidence=planner_selection.confidence, reason=planner_selection.reason or "规划失败，回退普通对话")
    return planner_selection


def selection_to_plan(selection: ToolSelection) -> dict:
    """把工具选择结果转换为统一 plan 结构。"""
    action = selection.action if selection.action in {"tool", "tool_agent", "chat", "clarification", "auto"} else "auto"
    tool_args = _tool_args(selection.args) if action == "tool" else {}
    step = {
        "step_id": "step_1",
        "action": action,
        "tool_name": selection.tool_name if action == "tool" else "",
        "args": tool_args,
        "reason": selection.reason,
    }
    candidate_tool_names = selection.args.get("_candidate_tool_names", []) if isinstance(selection.args, dict) else []
    clarification = selection.args if action == "clarification" and isinstance(selection.args, dict) else {}
    return {
        "intent": plan_intent(selection),
        "mode": action,
        "plan_steps": [step],
        "current_step": 0,
        "decision_reason": selection.reason,
        "candidate_tool_names": candidate_tool_names,
        "clarification_question": clarification.get("question", ""),
        "missing_info": clarification.get("missing_info", ""),
        "clarification_reason": clarification.get("reason", ""),
        "status": "ready",
    }


def auto_plan(reason: str) -> dict:
    """生成自动回退计划。"""
    return selection_to_plan(ToolSelection(action="auto", confidence=0.0, reason=reason))


def plan_intent(selection: ToolSelection) -> str:
    """根据选择器结果生成轻量意图标签。"""
    if selection.action == "tool" and selection.tool_name:
        return f"use_tool:{selection.tool_name}"
    if selection.action == "tool_agent":
        return "tool_agent"
    if selection.action == "clarification":
        return "clarification"
    if selection.action == "chat":
        return "chat"
    return "auto"


def deterministic_selection(user_text: str, input_context: dict, candidate_tool_names: list[str]) -> ToolSelection | None:
    """处理不需要 LLM 判断的确定性规划场景。"""
    normalized = " ".join(str(user_text or "").split()).strip()
    if not normalized:
        return None
    if _is_memory_instruction(normalized):
        return ToolSelection(action="chat", confidence=1.0, reason="本地判断：记忆指令")
    if _has_file_or_image_context(input_context) and not _asks_external_info(normalized):
        return ToolSelection(action="chat", confidence=1.0, reason="本地判断：使用已提供文件上下文回答")
    if "fetch_url" in candidate_tool_names or _first_url(normalized):
        return tool_agent_selection(normalized, ["fetch_url"])
    if "get_weather_forecast" in candidate_tool_names:
        return tool_agent_selection(normalized, ["get_weather_forecast"])
    if "get_weather" in candidate_tool_names:
        return tool_agent_selection(normalized, ["get_weather"])
    if "get_location" in candidate_tool_names:
        return tool_agent_selection(normalized, ["get_location"])
    if _is_event_summary_request(normalized):
        return tool_agent_selection(normalized, ["web_search"])
    return None


def clarification_decision(user_text: str, input_context: dict, candidate_tool_names: list[str]) -> dict:
    """判断是否需要先向用户澄清。"""
    normalized = " ".join(str(user_text or "").split()).strip()
    if not normalized or _has_context_target(normalized, input_context):
        return {}
    if _is_memory_instruction(normalized) or _is_weather_request(normalized):
        return {}
    if _is_missing_search_query(normalized, candidate_tool_names):
        return {
            "question": "你想查询什么内容？请补充关键词或范围。",
            "missing_info": "查询内容",
            "reason": "搜索类请求缺少查询对象。",
        }
    if _is_missing_operation_target(normalized):
        return {
            "question": "你想让我处理哪段内容？可以直接贴文本，或用 @文件路径 发给我。",
            "missing_info": "处理对象",
            "reason": "操作类请求缺少明确处理对象。",
        }
    return {}


def _has_context_target(text: str, input_context: dict) -> bool:
    """判断输入是否已经包含可处理对象。"""
    if _has_file_or_image_context(input_context) or input_context.get("file_errors") or input_context.get("should_retrieve"):
        return True
    if "http://" in text or "https://" in text or "[文件:" in text or "[文件内容]" in text:
        return True
    return bool(_content_after_action(text))


def _content_after_action(text: str) -> str:
    """提取操作词后的可能对象。"""
    for keyword in ("优化一下", "分析一下", "改一下", "修改一下", "总结一下", "处理一下", "润色一下"):
        if keyword not in text:
            continue
        _, _, tail = text.partition(keyword)
        return tail.strip(" ：:，,。.!！?")
    return ""


def _is_memory_instruction(text: str) -> bool:
    """判断是否为记忆指令。"""
    return any(keyword in text for keyword in ("记住", "请记住", "帮我记住", "以后记得", "我的偏好"))


def _is_weather_request(text: str) -> bool:
    """判断是否为天气请求。"""
    return any(keyword in text for keyword in ("天气", "气温", "下雨", "weather"))


def _is_missing_search_query(text: str, candidate_tool_names: list[str]) -> bool:
    """判断搜索类请求是否缺少查询对象。"""
    stripped = text.strip(" ：:，,。.!！?")
    if "fetch_url" in candidate_tool_names or urlparse(stripped).scheme in {"http", "https"}:
        return False
    search_phrases = {"查一下", "查询一下", "搜索一下", "搜一下", "帮我查一下", "帮我搜索一下", "看看最新", "查最新", "搜索"}
    return stripped in search_phrases


def _is_missing_operation_target(text: str) -> bool:
    """判断操作类请求是否缺少处理对象。"""
    stripped = text.strip(" ：:，,。.!！?")
    operation_phrases = {
        "帮我优化一下",
        "优化一下",
        "帮我分析一下",
        "分析一下",
        "帮我改一下",
        "改一下",
        "修改一下",
        "帮我总结一下",
        "总结一下",
        "处理一下",
        "润色一下",
    }
    return stripped in operation_phrases


def tool_agent_selection(user_text: str, candidate_tool_names: list[str] | None = None) -> ToolSelection:
    """生成 tool-agent 选择结果，并记录本轮候选工具。"""
    candidate_tool_names = candidate_tool_names if candidate_tool_names is not None else candidate_tool_names_for_text(user_text)
    return ToolSelection(
        action="tool_agent",
        args={"_candidate_tool_names": candidate_tool_names},
        confidence=1.0,
        reason="本地判断：进入工具 agent 模式",
    )


def fallback_tool_selection(tool_name: str, reflection: dict) -> ToolSelection:
    """根据 reflection 指定的 fallback 工具生成计划选择。"""
    reason = reflection.get("loop_reason") or reflection.get("reason") or f"反思决策：切换到 {tool_name}"
    args = {}
    if tool_name == "web_search":
        args = {"query": _fallback_query(reflection)}
    return ToolSelection(action="tool", tool_name=tool_name, args=args, confidence=1.0, reason=str(reason))


def _fallback_query(reflection: dict) -> str:
    """生成 fallback 搜索查询。"""
    reason = str(reflection.get("reason") or "").strip()
    if reason:
        return reason[:200]
    return "用户请求相关信息"


def _tool_args(args: dict) -> dict:
    """移除 plan 内部参数，保留真实工具参数。"""
    if not isinstance(args, dict):
        return {}
    return {key: value for key, value in args.items() if key != "_candidate_tool_names"}


def _has_file_or_image_context(input_context: dict) -> bool:
    """判断是否存在用户已提供的文件或图片上下文。"""
    return bool(input_context.get("attachments") or input_context.get("has_image"))


def _asks_external_info(text: str) -> bool:
    """判断用户是否明确要求外部信息。"""
    normalized = str(text or "").lower()
    return any(keyword in normalized for keyword in ("联网", "搜索", "查一下", "查询", "最新", "实时", "新闻", "网页", "web", "search"))


def _is_event_summary_request(text: str) -> bool:
    """判断是否为需要外部资料的事件总结请求。"""
    normalized = str(text or "").lower()
    time_keywords = ("去年", "今年", "最近一年", "过去一年", "上半年", "下半年", "last year", "this year", "recent")
    event_keywords = ("世界大事件", "大事件", "重大事件", "新闻事件", "年度事件", "events")
    action_keywords = ("总结", "梳理", "回顾", "盘点", "summary", "recap")
    return any(keyword in normalized for keyword in time_keywords) and any(
        keyword in normalized for keyword in event_keywords
    ) and any(keyword in normalized for keyword in action_keywords)


def _first_url(text: str) -> str:
    """提取文本中的第一个 URL。"""
    match = re.search(r"https?://[^\s，。)）]+", text)
    return match.group(0) if match else ""


def current_plan_step(plan: dict) -> dict:
    """读取当前 plan step，缺失时回退到 auto。"""
    steps = plan.get("plan_steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not steps:
        return {"step_id": "step_1", "action": "auto", "tool_name": "", "args": {}, "reason": "缺少计划，回退自动执行"}

    current_step = plan.get("current_step", 0)
    if not isinstance(current_step, int) or current_step < 0 or current_step >= len(steps):
        current_step = 0

    step = steps[current_step]
    if not isinstance(step, dict):
        return {"step_id": "step_1", "action": "auto", "tool_name": "", "args": {}, "reason": "计划步骤格式错误，回退自动执行"}
    return step
