"""Planning 节点与 plan 辅助函数。"""

import time

from agent_app.nodes.common import latest_human_message, node_run
from agent_app.state import AgentState
from agent_app.tool_selector import ToolSelection, should_enter_tool_mode
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
    user_text = message_text(latest_message)

    selection = planning_selection(user_text, bool(latest_message))
    plan = selection_to_plan(selection)
    return {
        "tool_selection": selection.to_dict(),
        "plan": plan,
        "node_runs": [node_run("planning", start_time)],
    }


def planning_selection(user_text: str, has_user_message: bool) -> ToolSelection:
    """根据本地 gate 生成规划选择。"""
    if not has_user_message:
        return ToolSelection(action="auto", reason="没有找到用户消息")
    if should_enter_tool_mode(user_text):
        return tool_agent_selection(user_text)
    return ToolSelection(action="chat", confidence=1.0, reason="本地判断：普通对话")


def selection_to_plan(selection: ToolSelection) -> dict:
    """把工具选择结果转换为统一 plan 结构。"""
    action = selection.action if selection.action in {"tool", "chat", "auto"} else "auto"
    if action == "auto" and selection.reason == "本地判断：进入工具 agent 模式":
        action = "tool_agent"
    step = {
        "step_id": "step_1",
        "action": action,
        "tool_name": selection.tool_name if action == "tool" else "",
        "args": selection.args if action == "tool" else {},
        "reason": selection.reason,
    }
    candidate_tool_names = selection.args.get("_candidate_tool_names", []) if isinstance(selection.args, dict) else []
    return {
        "intent": plan_intent(selection),
        "mode": action,
        "plan_steps": [step],
        "current_step": 0,
        "decision_reason": selection.reason,
        "candidate_tool_names": candidate_tool_names,
        "status": "ready",
    }


def auto_plan(reason: str) -> dict:
    """生成自动回退计划。"""
    return selection_to_plan(ToolSelection(action="auto", confidence=0.0, reason=reason))


def plan_intent(selection: ToolSelection) -> str:
    """根据选择器结果生成轻量意图标签。"""
    if selection.action == "tool" and selection.tool_name:
        return f"use_tool:{selection.tool_name}"
    if selection.action == "auto" and selection.reason == "本地判断：进入工具 agent 模式":
        return "tool_agent"
    if selection.action == "chat":
        return "chat"
    return "auto"


def tool_agent_selection(user_text: str) -> ToolSelection:
    """生成 tool-agent 选择结果，并记录本轮候选工具。"""
    candidate_tool_names = candidate_tool_names_for_text(user_text)
    return ToolSelection(
        action="auto",
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
