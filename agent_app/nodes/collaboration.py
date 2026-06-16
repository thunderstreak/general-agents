"""Sub-Agent 协作节点。"""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_app.llm import invoke_with_fallback
from agent_app.nodes.common import latest_human_message, node_run
from agent_app.state import AgentState
from agent_app.utils.messages import message_text


COLLABORATION_ROLES = ("researcher", "executor", "analyst", "writer", "critic")
MAP_ROLES = ("researcher", "executor")


def supervisor_node(state: AgentState):
    """生成固定角色协作计划和并行任务。"""
    start_time = time.perf_counter()
    plan = state.get("plan") or {}
    user_text = _latest_user_text(state)
    tasks = [
        {
            "task_id": "subtask_researcher",
            "role": "researcher",
            "instruction": "整理已有检索、网页、RAG 资料，提取可用于回答的证据。",
            "user_text": user_text,
        },
        {
            "task_id": "subtask_executor",
            "role": "executor",
            "instruction": "检查当前任务是否需要结构化工具操作，并说明可执行动作与限制。",
            "user_text": user_text,
        },
    ]
    collaboration_plan = {
        "mode": "collaboration",
        "roles": list(COLLABORATION_ROLES),
        "map_roles": list(MAP_ROLES),
        "reduce_roles": ["analyst", "writer", "critic"],
        "flow": "researcher + executor -> aggregate_evidence -> analyst -> writer -> critic",
        "reason": plan.get("decision_reason") or "复杂任务进入固定角色协作流程",
    }
    return {
        "collaboration_plan": collaboration_plan,
        "subagent_tasks": tasks,
        "collaboration_summary": {"revision_count": 0},
        "node_runs": [node_run("supervisor", start_time)],
    }


def subagent_worker_node(state: AgentState):
    """执行单个 map 阶段 sub-agent 任务。"""
    start_time = time.perf_counter()
    task = state.get("active_subagent_task") or {}
    role = task.get("role", "")
    if role == "researcher":
        result = _researcher_result(state, task)
    elif role == "executor":
        result = _executor_result(state, task)
    else:
        result = {
            "task_id": task.get("task_id", ""),
            "role": role or "unknown",
            "status": "skipped",
            "content": "未知角色，已跳过。",
            "evidence": [],
            "limitations": ["未注册的 sub-agent 角色。"],
        }
    return {"subagent_results": [result], "node_runs": [node_run("subagent_worker", start_time)]}


def aggregate_evidence_node(state: AgentState):
    """聚合并行 sub-agent 结果。"""
    start_time = time.perf_counter()
    results = [item for item in state.get("subagent_results", []) if isinstance(item, dict)]
    evidence = []
    limitations = []
    for result in results:
        for item in result.get("evidence", []):
            if isinstance(item, dict):
                evidence.append(item)
        limitations.extend(str(item) for item in result.get("limitations", []) if item)

    summary = dict(state.get("collaboration_summary") or {})
    summary.update(
        {
            "subagent_results": results,
            "evidence": evidence,
            "limitations": list(dict.fromkeys(limitations)),
            "evidence_count": len(evidence),
        }
    )
    return {"collaboration_summary": summary, "node_runs": [node_run("aggregate_evidence", start_time)]}


def analyst_node(state: AgentState):
    """根据聚合证据生成分析结论。"""
    start_time = time.perf_counter()
    summary = dict(state.get("collaboration_summary") or {})
    evidence = summary.get("evidence", [])
    limitations = summary.get("limitations", [])
    user_text = _latest_user_text(state)
    findings = []
    if evidence:
        findings.append(f"已整理 {len(evidence)} 条可用证据。")
    else:
        findings.append("当前没有外部或 RAG 证据，需基于已知上下文谨慎回答。")
    if limitations:
        findings.append("存在限制：" + "；".join(limitations[:3]))
    findings.append(f"回答应围绕用户问题展开：{user_text}")
    summary["analysis"] = {"findings": findings, "status": "ready"}
    return {"collaboration_summary": summary, "node_runs": [node_run("analyst", start_time)]}


def writer_node(state: AgentState):
    """生成协作流程的最终草稿。"""
    start_time = time.perf_counter()
    summary = dict(state.get("collaboration_summary") or {})
    revision_count = int(summary.get("revision_count", 0) or 0)
    user_text = _latest_user_text(state)
    evidence = summary.get("evidence", [])
    findings = (summary.get("analysis") or {}).get("findings", [])

    draft = _invoke_writer(user_text, evidence, findings, revision_count)
    if not draft:
        draft = _fallback_draft(user_text, evidence, findings, revision_count)
    summary["draft"] = draft
    return {"collaboration_summary": summary, "node_runs": [node_run("writer", start_time)]}


def critic_node(state: AgentState):
    """校验协作草稿，必要时要求 writer 最多修订一次。"""
    start_time = time.perf_counter()
    summary = dict(state.get("collaboration_summary") or {})
    draft = str(summary.get("draft") or "").strip()
    revision_count = int(summary.get("revision_count", 0) or 0)
    issues = []
    if not draft:
        issues.append("草稿为空。")
    if "结论：" not in draft:
        issues.append("缺少明确结论。")
    if len(draft) < 40:
        issues.append("回答过短，信息量不足。")

    if issues and revision_count < 1:
        summary["critic"] = {"status": "revise", "issues": issues}
        summary["revision_count"] = revision_count + 1
        return {"collaboration_summary": summary, "node_runs": [node_run("critic", start_time)]}

    status = "passed" if not issues else "accepted_with_limitations"
    summary["critic"] = {"status": status, "issues": issues}
    content = draft or "这次协作流程没有生成有效草稿，请换个更具体的任务再试。"
    return {
        "collaboration_summary": summary,
        "messages": [AIMessage(content=content)],
        "node_runs": [node_run("critic", start_time)],
    }


def _researcher_result(state: AgentState, task: dict) -> dict:
    """构造 researcher 结果。"""
    retrieval_results = [item for item in state.get("retrieval_results", []) if isinstance(item, dict)]
    evidence = []
    for item in retrieval_results[:5]:
        evidence.append(
            {
                "role": "researcher",
                "source": item.get("title") or item.get("source") or item.get("document_id") or "retrieval",
                "content": str(item.get("content") or "")[:500],
                "url": item.get("url", ""),
            }
        )
    limitations = [] if evidence else ["未检索到可聚合的 RAG 或网页证据。"]
    return {
        "task_id": task.get("task_id", "subtask_researcher"),
        "role": "researcher",
        "status": "completed",
        "content": f"researcher 汇总了 {len(evidence)} 条证据。",
        "evidence": evidence,
        "limitations": limitations,
    }


def _executor_result(state: AgentState, task: dict) -> dict:
    """构造 executor 结果。"""
    plan = state.get("plan") or {}
    candidate_tool_names = plan.get("candidate_tool_names") if isinstance(plan.get("candidate_tool_names"), list) else []
    evidence = [
        {
            "role": "executor",
            "source": "plan",
            "content": f"当前协作任务的候选工具：{candidate_tool_names or ['无']}；不会在协作链路中绕过工具确认直接执行。",
        }
    ]
    return {
        "task_id": task.get("task_id", "subtask_executor"),
        "role": "executor",
        "status": "completed",
        "content": "executor 已完成结构化操作检查。",
        "evidence": evidence,
        "limitations": ["需要真实工具调用时应回到 tool_agent/tools 主链路执行。"],
    }


def _latest_user_text(state: AgentState) -> str:
    """读取最近用户文本。"""
    input_context = state.get("input_context") or {}
    if input_context.get("normalized_text"):
        return str(input_context["normalized_text"])
    latest_message = latest_human_message(state.get("messages", []))
    return message_text(latest_message) if latest_message else ""


def _answer_opening(user_text: str) -> str:
    """生成草稿开头。"""
    text = str(user_text or "").strip()
    if not text:
        return "我按协作流程完成了这次分析。"
    return f"围绕“{text}”，我按协作流程整理如下。"


def _invoke_writer(user_text: str, evidence: list, findings: list, revision_count: int) -> str:
    """调用模型生成协作草稿，失败时返回空字符串。"""
    evidence_text = _format_evidence(evidence)
    findings_text = "\n".join(f"- {item}" for item in findings) or "- 暂无分析结论"
    revision_text = "这是 critic 要求后的唯一一次修订，请收敛表达并补足结论。" if revision_count else "这是首版草稿。"
    try:
        response = invoke_with_fallback(
            [
                SystemMessage(
                    content=(
                        "你是 writer，负责把 researcher/executor/analyst 的结果整理为最终中文回答。"
                        "必须直接回答用户问题，保留技术术语英文并给出中文解释。"
                        "不要编造未提供的来源；证据不足时明确说明限制。"
                        "回答末尾必须包含以“结论：”开头的简短结论。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"用户问题：{user_text}\n\n"
                        f"修订状态：{revision_text}\n\n"
                        f"analyst 分析：\n{findings_text}\n\n"
                        f"聚合证据：\n{evidence_text}\n\n"
                        "请生成最终回答。"
                    )
                ),
            ]
        )
    except Exception:
        return ""
    return str(getattr(response, "content", "") or "").strip()


def _fallback_draft(user_text: str, evidence: list, findings: list, revision_count: int) -> str:
    """生成无需模型的兜底草稿。"""
    lines = []
    if revision_count:
        lines.append("根据校验意见，我做了一次收敛修订：")
    lines.append(_answer_opening(user_text))
    if findings:
        lines.append("分析判断：" + " ".join(str(item) for item in findings))
    if evidence:
        lines.append("关键依据：")
        for item in evidence[:5]:
            source = item.get("source") or item.get("role") or "context"
            content = str(item.get("content") or "").strip()
            if content:
                lines.append(f"- {source}: {content}")
    if not evidence:
        lines.append("当前没有可引用的外部证据；这版回答会明确基于现有上下文，而不是伪造来源。")
    lines.append("结论：建议先按问题目标拆分信息、工具操作和表达校验三个层次推进，复杂任务使用协作链路，普通任务继续使用单 Agent 链路。")
    return "\n".join(lines)


def _format_evidence(evidence: list) -> str:
    """格式化聚合证据。"""
    lines = []
    for item in evidence[:8]:
        if not isinstance(item, dict):
            continue
        source = item.get("source") or item.get("role") or "context"
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {source}: {content}")
    return "\n".join(lines) or "- 暂无可引用证据"
