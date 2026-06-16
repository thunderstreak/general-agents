"""LangGraph 路由测试。"""

import unittest

from langchain_core.messages import AIMessage, ToolCall

from agent_app.graph import (
    after_critic_router,
    after_planning_router,
    after_retrieval_router,
    after_reflection_router,
    after_tool_router,
    build_graph,
    dispatch_subagent_tasks,
    perception_node,
    router,
)
from tests.helpers import base_state


class GraphRouterTest(unittest.TestCase):
    """Graph 路由行为测试。"""

    def test_router_requires_confirmation(self):
        """需要确认的工具进入确认分支。"""
        state = base_state()
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

    def test_after_tool_router_goes_to_reflection(self):
        """工具执行后进入 reflection。"""
        self.assertEqual(after_tool_router(base_state()), "reflection")

    def test_after_reflection_router_uses_next_action(self):
        """reflection 可路由到多个下一步。"""
        for action in ("agent", "tools", "planning", "response", "error"):
            state = base_state()
            state["reflection"] = {"next_action": action}
            self.assertEqual(after_reflection_router(state), action)

    def test_after_reflection_router_prefers_last_error(self):
        """已有错误时进入 error。"""
        state = base_state()
        state["reflection"] = {"next_action": "tools"}
        state["last_error"] = {"message": "失败"}

        self.assertEqual(after_reflection_router(state), "error")

    def test_after_planning_router_routes_collaboration(self):
        """协作计划进入 supervisor。"""
        state = base_state()
        state["plan"] = {"mode": "collaboration"}

        self.assertEqual(after_planning_router(state), "supervisor")

    def test_after_planning_router_routes_chat_rag_to_retrieval(self):
        """chat 计划需要 RAG 时先进入 retrieval。"""
        state = base_state()
        state["plan"] = {"mode": "chat"}
        state["input_context"] = {"normalized_text": "根据知识库回答 LangGraph 是什么", "should_retrieve": True}

        self.assertEqual(after_planning_router(state), "retrieval")

    def test_after_planning_router_skips_retrieval_for_rag_list(self):
        """rag_list 计划直接进入 agent。"""
        state = base_state()
        state["plan"] = {"mode": "rag_list"}
        state["input_context"] = {"normalized_text": "知识库有哪些", "should_retrieve": True}

        self.assertEqual(after_planning_router(state), "agent")

    def test_after_planning_router_routes_regular_plan_to_agent(self):
        """普通计划继续进入单 Agent 链路。"""
        state = base_state()
        state["plan"] = {"mode": "chat"}

        self.assertEqual(after_planning_router(state), "agent")

    def test_after_retrieval_router_preserves_collaboration_plan(self):
        """协作计划完成检索后进入 supervisor。"""
        state = base_state()
        state["plan"] = {"mode": "collaboration"}

        self.assertEqual(after_retrieval_router(state), "supervisor")

    def test_dispatch_subagent_tasks_builds_send_payloads(self):
        """supervisor 任务使用 Send 分发到 worker。"""
        state = base_state()
        state["subagent_tasks"] = [{"task_id": "subtask_researcher", "role": "researcher"}]
        state["retrieval_results"] = [{"source": "doc", "content": "资料"}]

        sends = dispatch_subagent_tasks(state)

        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0].node, "subagent_worker")
        self.assertEqual(sends[0].arg["active_subagent_task"]["role"], "researcher")
        self.assertEqual(sends[0].arg["retrieval_results"], [{"source": "doc", "content": "资料"}])

    def test_after_critic_router_allows_single_revision(self):
        """critic 要求修订时回到 writer。"""
        state = base_state()
        state["collaboration_summary"] = {"critic": {"status": "revise"}}

        self.assertEqual(after_critic_router(state), "writer")

    def test_after_critic_router_passes_to_memory(self):
        """critic 通过后进入 memory。"""
        state = base_state()
        state["collaboration_summary"] = {"critic": {"status": "passed"}}

        self.assertEqual(after_critic_router(state), "memory")

    def test_graph_exports_perception_and_compiles(self):
        """图包含 perception 入口节点并可编译。"""
        self.assertTrue(callable(perception_node))
        self.assertIsNotNone(build_graph())


if __name__ == "__main__":
    unittest.main()
