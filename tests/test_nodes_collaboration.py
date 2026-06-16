"""Sub-Agent 协作节点测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from agent_app.nodes.collaboration import (
    aggregate_evidence_node,
    analyst_node,
    critic_node,
    subagent_worker_node,
    supervisor_node,
    writer_node,
)
from tests.helpers import base_state


class CollaborationNodeTest(unittest.TestCase):
    """协作节点行为测试。"""

    def test_supervisor_node_builds_fixed_role_tasks(self):
        """supervisor 生成固定角色计划和 map 任务。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="评估架构优化计划")]
        state["plan"] = {"mode": "collaboration", "decision_reason": "复杂任务"}

        result = supervisor_node(state)

        self.assertEqual(result["collaboration_plan"]["mode"], "collaboration")
        self.assertEqual(result["collaboration_plan"]["roles"], ["researcher", "executor", "analyst", "writer", "critic"])
        self.assertEqual([task["role"] for task in result["subagent_tasks"]], ["researcher", "executor"])

    def test_subagent_worker_researcher_uses_retrieval_results(self):
        """researcher 汇总 RAG 检索结果。"""
        state = base_state()
        state["active_subagent_task"] = {"task_id": "subtask_researcher", "role": "researcher"}
        state["retrieval_results"] = [{"source": "docs/a.md", "content": "项目已有 LangGraph 流程。"}]

        result = subagent_worker_node(state)

        item = result["subagent_results"][0]
        self.assertEqual(item["role"], "researcher")
        self.assertEqual(item["evidence"][0]["source"], "docs/a.md")
        self.assertIn("LangGraph", item["evidence"][0]["content"])

    def test_aggregate_and_analyst_nodes_update_summary(self):
        """聚合与分析节点写入 collaboration_summary。"""
        state = base_state()
        state["subagent_results"] = [
            {
                "role": "researcher",
                "evidence": [{"source": "docs", "content": "证据"}],
                "limitations": ["限制"],
            }
        ]

        aggregate_result = aggregate_evidence_node(state)
        state.update(aggregate_result)
        analyst_result = analyst_node(state)

        self.assertEqual(aggregate_result["collaboration_summary"]["evidence_count"], 1)
        self.assertIn("analysis", analyst_result["collaboration_summary"])

    def test_writer_and_critic_emit_final_message(self):
        """writer 生成草稿，critic 通过后追加最终消息。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="评估架构优化计划")]
        state["collaboration_summary"] = {
            "evidence": [{"source": "docs", "content": "已有单 Agent 链路。"}],
            "analysis": {"findings": ["协作链路适合复杂任务。"]},
            "revision_count": 0,
        }

        draft = "协作流程回答已经覆盖证据、分析和落地建议，能够支持复杂任务处理。\n结论：适合进入协作链路。"
        with patch("agent_app.nodes.collaboration.invoke_with_fallback", return_value=AIMessage(content=draft)):
            writer_result = writer_node(state)
        state.update(writer_result)
        critic_result = critic_node(state)

        self.assertIn("结论：", writer_result["collaboration_summary"]["draft"])
        self.assertEqual(critic_result["collaboration_summary"]["critic"]["status"], "passed")
        self.assertIn("协作流程", critic_result["messages"][0].content)

    def test_critic_requests_at_most_one_revision(self):
        """critic 首次可要求修订，第二次接受限制。"""
        state = base_state()
        state["collaboration_summary"] = {"draft": "太短", "revision_count": 0}

        first = critic_node(state)
        state.update(first)
        second = critic_node(state)

        self.assertEqual(first["collaboration_summary"]["critic"]["status"], "revise")
        self.assertEqual(first["collaboration_summary"]["revision_count"], 1)
        self.assertEqual(second["collaboration_summary"]["critic"]["status"], "accepted_with_limitations")
        self.assertTrue(second["messages"][0].content)


if __name__ == "__main__":
    unittest.main()
