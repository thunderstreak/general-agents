"""Orchestrator 编排层测试。"""

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolCall

from agent_app.graph import agent_node, response_node, retrieval_node, router
from agent_app.orchestrator import should_retrieve
from agent_app.output import build_response


def _base_state():
    """构造基础 AgentState。"""
    return {
        "messages": [HumanMessage(content="你好")],
        "tool_selection": {},
        "tool_calls": [],
        "tool_errors": [],
        "retrieval_results": [],
        "user_profile": {},
        "long_term_memory": {},
        "step_count": 0,
        "max_steps": 8,
        "last_error": {},
        "pending_confirmation": {},
        "approved_tool_call_ids": [],
        "final_response": {},
        "trace_id": "test-trace",
        "node_runs": [],
        "memory_updated": False,
    }


class OrchestratorTest(unittest.TestCase):
    """Orchestrator 基础行为测试。"""

    def test_agent_node_exceeds_max_steps(self):
        """超过最大步骤时进入错误状态。"""
        state = _base_state()
        state["step_count"] = 8
        state["max_steps"] = 8

        result = agent_node(state)

        self.assertEqual(result["last_error"]["type"], "max_steps_exceeded")
        self.assertEqual(result["step_count"], 9)

    def test_router_requires_confirmation(self):
        """需要确认的工具进入确认分支。"""
        state = _base_state()
        tool_call = ToolCall(name="web_search", args={"query": "test"}, id="tool_1")
        state["messages"] = [AIMessage(content="", tool_calls=[tool_call])]

        from agent_app.graph import tool_metadata_by_name

        old_value = tool_metadata_by_name["web_search"].requires_confirmation
        object.__setattr__(tool_metadata_by_name["web_search"], "requires_confirmation", True)
        try:
            route = router(state)
        finally:
            object.__setattr__(tool_metadata_by_name["web_search"], "requires_confirmation", old_value)

        self.assertEqual(route, "confirm")

    def test_agent_node_keeps_existing_tool_call(self):
        """已确认的 tool_call 不应被 agent_node 重新选择。"""
        state = _base_state()
        tool_call = ToolCall(name="web_search", args={"query": "test"}, id="tool_1")
        state["messages"] = [HumanMessage(content="搜索 test"), AIMessage(content="", tool_calls=[tool_call])]

        result = agent_node(state)

        self.assertNotIn("messages", result)
        self.assertEqual(result["step_count"], 1)

    def test_retrieval_placeholder(self):
        """RAG 预留节点在命中关键词时写入检索结果。"""
        state = _base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答 LangGraph 是什么")]

        result = retrieval_node(state)

        self.assertTrue(should_retrieve("根据知识库回答 LangGraph 是什么"))
        self.assertEqual(result["retrieval_results"][0]["source"], "local_rag_placeholder")

    def test_response_node_builds_final_response(self):
        """response node 输出统一结构。"""
        state = _base_state()
        state["messages"].append(AIMessage(content="回答内容"))
        state["tool_calls"] = [{"tool_name": "web_search"}]
        state["memory_updated"] = True

        result = response_node(state)

        self.assertEqual(result["final_response"]["content"], "回答内容")
        self.assertEqual(result["final_response"]["tool_calls"], [{"tool_name": "web_search"}])
        self.assertTrue(result["final_response"]["memory_updated"])

    def test_build_response_includes_error(self):
        """统一输出包含错误信息。"""
        state = _base_state()
        state["messages"].append(AIMessage(content="失败"))
        state["last_error"] = {"message": "工具失败"}

        response = build_response(state)

        self.assertEqual(response["errors"][0]["message"], "工具失败")


if __name__ == "__main__":
    unittest.main()
