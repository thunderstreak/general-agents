"""Planning 节点测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agent_app.graph import planning_node
from agent_app.tool_selector import ToolSelection
from tests.helpers import base_state


class PlanningNodeTest(unittest.TestCase):
    """planning_node 行为测试。"""

    def test_planning_node_builds_tool_agent_plan(self):
        """明确工具意图生成 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气 如何")]
        state["input_context"] = {"normalized_text": "今天天气 如何", "candidate_tool_names": ["get_weather"]}

        result = planning_node(state)

        self.assertEqual(result["tool_selection"]["action"], "tool_agent")
        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "tool_agent")

    def test_planning_node_builds_chat_plan(self):
        """普通对话转换为 chat plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="讲个短笑话")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="chat", confidence=0.93, reason="planner 判断为普通聊天")):
            result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "chat")

    def test_planning_node_missing_operation_target_uses_clarification_plan(self):
        """planner 失败时，缺少处理对象的极短请求生成 fallback clarification plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="帮我优化一下")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="auto", confidence=0.0, reason="规划失败")) as planner:
            result = planning_node(state)

        planner.assert_called_once()
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
        """planner 失败时，缺少查询对象的极短搜索请求生成 fallback clarification plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="查一下")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="auto", confidence=0.0, reason="规划失败")) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "clarification")
        self.assertEqual(result["plan"]["missing_info"], "查询内容")
        self.assertIn("查询什么内容", result["plan"]["clarification_question"])

    def test_planning_node_missing_install_target_uses_clarification_plan(self):
        """安装配置类请求缺少具体对象时由 planner 生成 clarification plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="如何安装安全审计协议")]

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="clarification",
                args={
                    "question": "你想安装或配置的是哪个具体安全审计协议、产品或标准？请补充名称、运行环境和目标系统。",
                    "missing_info": "安装对象和运行环境",
                    "reason": "缺少安装对象和运行环境",
                },
                confidence=0.91,
                reason="planner 判断需要澄清",
            ),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "clarification")
        self.assertEqual(result["plan"]["missing_info"], "安装对象和运行环境")
        self.assertIn("哪个具体安全审计协议", result["plan"]["clarification_question"])

    def test_planning_node_memory_instruction_uses_chat_plan(self):
        """记忆类设计约束不进入外部工具模式。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="请记住本次设计里不要引入数据库，先用内存存储")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["plan_steps"][0]["action"], "chat")
        self.assertEqual(result["plan"]["candidate_tool_names"], [])

    def test_planning_node_plain_chat_uses_structured_planner(self):
        """普通对话使用 structured planner 判断为 chat。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="你好")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="chat", confidence=0.95, reason="planner 判断为普通聊天")) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["tool_selection"]["action"], "chat")
        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["decision_reason"], "planner 判断为普通聊天")

    def test_planning_node_market_question_enters_tool_agent(self):
        """实时市场问题由 structured planner 进入 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="我想看今天的股票市场行情")]

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="tool_agent",
                args={"_candidate_tool_names": ["web_search"]},
                confidence=0.95,
                reason="planner 判断需要外部行情信息",
            ),
        ):
            result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])

    def test_planning_node_last_year_world_events_enters_search(self):
        """相对日期的世界大事件总结由 planner 进入搜索工具。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="总结去年一年发生的世界大事件")]

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="tool_agent",
                args={"_candidate_tool_names": ["web_search"]},
                confidence=0.95,
                reason="planner 判断需要搜索年度事件",
            ),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])

    def test_planning_node_url_question_enters_tool_agent(self):
        """URL 问题进入 tool_agent plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="总结 https://example.com 这篇文章")]

        result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["fetch_url"])

    def test_planning_node_complex_request_enters_collaboration(self):
        """复杂评估任务由 planner 进入 sub-agent 协作计划。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="评估当前项目架构和代码重复率，给出优化计划")]

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(action="collaboration", confidence=0.94, reason="planner 判断为复杂评估任务"),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["tool_selection"]["action"], "collaboration")
        self.assertEqual(result["plan"]["mode"], "collaboration")
        self.assertEqual(result["plan"]["intent"], "collaboration")

    def test_planning_node_weather_question_records_candidate_tool(self):
        """天气问题只记录天气候选工具。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气如何")]
        state["input_context"] = {"normalized_text": "今天天气如何", "candidate_tool_names": ["get_weather"]}

        result = planning_node(state)

        self.assertEqual(result["plan"]["candidate_tool_names"], ["get_weather"])

    def test_planning_node_uses_planner_when_candidate_is_not_hard_guard(self):
        """非确定性候选工具由 planner 决定。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="你好")]
        state["input_context"] = {"normalized_text": "你好", "candidate_tool_names": ["web_search"]}

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="chat",
                args={"_candidate_tool_names": []},
                confidence=0.91,
                reason="planner 判断为普通问候",
            ),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["candidate_tool_names"], [])

    def test_planning_node_uses_chat_plan_for_rag_context(self):
        """RAG 命中时由 planner 使用检索上下文回答，不进入工具 agent。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答：chunks.jsonl 是做什么的？")]
        state["input_context"] = {
            "normalized_text": "根据知识库回答：chunks.jsonl 是做什么的？",
            "should_retrieve": True,
            "candidate_tool_names": [],
        }

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(action="chat", confidence=0.92, reason="planner 判断使用 RAG 上下文回答"),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertEqual(result["plan"]["decision_reason"], "planner 判断使用 RAG 上下文回答")

    def test_planning_node_knowledge_list_question_uses_rag_list_plan(self):
        """知识库列表请求由 planner 生成 rag_list plan。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="知识库有哪些")]
        state["input_context"] = {
            "normalized_text": "知识库有哪些",
            "should_retrieve": True,
            "candidate_tool_names": [],
        }

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(action="rag_list", confidence=0.95, reason="planner 判断为知识库清单查询"),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "rag_list")
        self.assertEqual(result["plan"]["intent"], "rag_list")

    def test_planning_node_knowledge_list_falls_back_to_rag_list(self):
        """planner 未识别知识库清单时，本地兜底为 rag_list。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="知识库有哪些")]
        state["input_context"] = {
            "normalized_text": "知识库有哪些",
            "should_retrieve": True,
            "candidate_tool_names": [],
        }

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="auto", confidence=0.0, reason="规划失败")) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "rag_list")
        self.assertEqual(result["plan"]["decision_reason"], "本地兜底：列出知识库文档")

    def test_planning_node_rag_with_external_request_uses_planner(self):
        """RAG 命中但用户明确要求联网时交给 planner。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答，并联网查一下最新变化")]
        state["input_context"] = {
            "normalized_text": "根据知识库回答，并联网查一下最新变化",
            "should_retrieve": True,
            "candidate_tool_names": [],
        }

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="tool_agent",
                args={"_candidate_tool_names": ["web_search"]},
                confidence=0.9,
                reason="planner 判断需要联网补充",
            ),
        ) as planner:
            result = planning_node(state)

        planner.assert_called_once()
        self.assertEqual(result["plan"]["mode"], "tool_agent")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])

    def test_planning_node_multilingual_chat_skips_tool_selector(self):
        """多语言普通问候由 planner 判断为 chat。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="こんにちは")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="chat", confidence=0.92, reason="planner 判断为普通聊天")):
            result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")

    def test_planning_node_planner_failure_falls_back_chat(self):
        """planner 失败时回退 chat，避免空白输出。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="帮我想一个项目名")]

        with patch("agent_app.nodes.planning.select_plan", return_value=ToolSelection(action="auto", confidence=0.0, reason="规划失败：invalid json")):
            result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "chat")
        self.assertIn("规划失败", result["plan"]["decision_reason"])

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

    def test_planning_node_tool_plan_strips_internal_candidate_names(self):
        """直接工具计划不会把内部候选工具字段传给工具参数。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="查一下 OpenAI")]

        with patch(
            "agent_app.nodes.planning.select_plan",
            return_value=ToolSelection(
                action="tool",
                tool_name="web_search",
                args={"_candidate_tool_names": ["web_search"], "query": "OpenAI"},
                confidence=0.95,
                reason="planner 确定直接搜索",
            ),
        ):
            result = planning_node(state)

        self.assertEqual(result["plan"]["mode"], "tool")
        self.assertEqual(result["plan"]["candidate_tool_names"], ["web_search"])
        self.assertEqual(result["plan"]["plan_steps"][0]["args"], {"query": "OpenAI"})


if __name__ == "__main__":
    unittest.main()
