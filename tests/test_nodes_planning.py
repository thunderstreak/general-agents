"""Planning 节点测试。"""

import unittest

from langchain_core.messages import HumanMessage

from agent_app.graph import planning_node
from tests.helpers import base_state


class PlanningNodeTest(unittest.TestCase):
    """planning_node 行为测试。"""

    def test_planning_node_builds_tool_agent_plan(self):
        """明确工具意图生成 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气 如何")]

        result = planning_node(state)

        self.assertEqual(result["tool_selection"]["action"], "auto")
        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "tool_agent")

    def test_planning_node_builds_chat_plan(self):
        """普通对话转换为 chat plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="讲个短笑话")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "chat")

    def test_planning_node_missing_operation_target_uses_clarification_plan(self):
        """缺少处理对象的操作请求生成 clarification plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="帮我优化一下")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "clarification")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "clarification")
        self.assertEqual(result["plan"]["missing_info"], "处理对象")
        self.assertIn("哪段内容", result["plan"]["clarification_question"])

    def test_planning_node_operation_with_file_context_skips_clarification(self):
        """已有文件上下文时不触发 clarification。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="帮我优化一下 [文件: docs/demo.md]")]
        state["input_context"] = {"normalized_text": "帮我优化一下 [文件: docs/demo.md]", "attachments": [{"path": "docs/demo.md"}]}

        result = planning_node(state)

        self.assertNotEqual(result["plan"]["mode"], "clarification")

    def test_planning_node_missing_search_query_uses_clarification_plan(self):
        """缺少查询对象的搜索请求生成 clarification plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="查一下")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "clarification")
        self.assertEqual(result["plan"]["missing_info"], "查询内容")
        self.assertIn("查询什么内容", result["plan"]["clarification_question"])

    def test_planning_node_memory_instruction_uses_chat_plan(self):
        """记忆类设计约束不进入外部工具模式。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="请记住本次设计里不要引入数据库，先用内存存储")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "chat")
        self.assertEqual(result["plan"]["candidate_tool_names"], [])

    def test_planning_node_uses_quick_chat_without_select_tool(self):
        """明显普通对话跳过工具选择模型。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="你好")]

        result = planning_node(state)

        self.assertEqual(result["tool_selection"]["action"], "chat")
        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["decision_reason"], "本地判断：普通对话")

    def test_planning_node_market_question_enters_tool_agent(self):
        """实时市场问题进入 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="我想看今天的股票市场行情")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])

    def test_planning_node_url_question_enters_tool_agent(self):
        """URL 问题进入 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="总结 https://example.com 这篇文章")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["fetch_url"])

    def test_planning_node_weather_question_records_candidate_tool(self):
        """天气问题只记录天气候选工具。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气如何")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["candidate_tool_names"], ["get_weather"])

    def test_planning_node_prefers_input_context_candidates(self):
        """planning 优先使用 perception 生成的候选工具。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="你好")]
        state["input_context"] = {"normalized_text": "你好", "candidate_tool_names": ["web_search"]}

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])

    def test_planning_node_uses_chat_plan_for_rag_context(self):
        """RAG 命中时直接使用检索上下文回答，不进入工具 agent。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答：chunks.jsonl 是做什么的？")]
        state["input_context"] = {
            "normalized_text": "根据知识库回答：chunks.jsonl 是做什么的？",
            "should_retrieve": True,
            "candidate_tool_names": [],
        }

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["decision_reason"], "本地判断：使用知识库检索上下文回答")

    def test_planning_node_multilingual_chat_skips_tool_selector(self):
        """多语言普通问候直接 chat。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="こんにちは")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")

    def test_planning_node_uses_reflection_fallback_tool(self):
        """reflection 指定 fallback 工具时生成工具计划。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="总结 https://example.com")]
        state["reflection"] = {
            "status": "insufficient",
            "next_action": "planning",
            "fallback_tool_name": "web_search",
            "reason": "fetch_url 抓取失败",
            "loop_reason": "当前工具结果不足，切换到 web_search",
        }

        result = planning_node(state)

        self.assertEqual(result["tool_selection"]["action"], "tool")
        self.assertEqual(result["tool_selection"]["tool_name"], "web_search")
        self.assertEqual(result["plan"]["mode"], "tool")
        self.assertEqual(result["plan"]["plan_steps"][0]["tool_name"], "web_search")
        self.assertEqual(result["plan"]["plan_steps"][0]["args"], {"query": "fetch_url 抓取失败"})


if __name__ == "__main__":
    unittest.main()
