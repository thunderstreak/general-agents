"""Agent 节点测试。"""

import importlib
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from agent_app.nodes.agent import agent_node, invoke_tool_agent, parse_pseudo_tool_calls, with_context
from tests.helpers import base_state


class AgentNodeTest(unittest.TestCase):
    """agent_node 行为测试。"""

    def test_agent_node_exceeds_max_steps(self):
        """超过最大步骤时进入错误状态。"""
        state = base_state()
        state["step_count"] = 8
        state["max_steps"] = 8

        result = agent_node(state)

        self.assertEqual(result["last_error"]["type"], "max_steps_exceeded")
        self.assertEqual(result["step_count"], 9)

    def test_agent_node_keeps_existing_tool_call(self):
        """已确认的 tool_call 不应被 agent_node 重新选择。"""
        state = base_state()
        tool_call = ToolCall(name="web_search", args={"query": "test"}, id="tool_1")
        state["messages"] = [HumanMessage(content="搜索 test"), AIMessage(content="", tool_calls=[tool_call])]

        result = agent_node(state)

        self.assertNotIn("messages", result)
        self.assertEqual(result["step_count"], 1)

    def test_agent_node_does_not_emit_thinking_for_existing_tool_call(self):
        """已有 tool_call 时不输出思考进度。"""
        state = base_state()
        tool_call = ToolCall(name="web_search", args={"query": "test"}, id="tool_1")
        state["messages"] = [HumanMessage(content="搜索 test"), AIMessage(content="", tool_calls=[tool_call])]

        with patch("agent_app.nodes.agent.emit_progress") as emit_progress:
            agent_node(state)

        emit_progress.assert_not_called()

    def test_agent_node_does_not_emit_thinking_when_selecting_tool(self):
        """首轮选择工具时不输出思考进度。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气 如何")]
        state["plan"] = {
            "intent": "use_tool:get_weather",
            "mode": "tool",
            "plan_steps": [{"step_id": "step_1", "action": "tool", "tool_name": "get_weather", "args": {"city": ""}, "reason": "需要查询天气"}],
            "current_step": 0,
            "decision_reason": "需要查询天气",
            "status": "ready",
        }

        with patch("agent_app.nodes.agent.emit_progress") as emit_progress:
            result = agent_node(state)

        emit_progress.assert_not_called()
        self.assertEqual(result["messages"][0].tool_calls[0]["name"], "get_weather")
        self.assertEqual(result["last_tool_request"]["tool_calls"][0]["name"], "get_weather")
        self.assertEqual(result["attempted_tools"], ["get_weather"])

    def test_agent_node_chat_plan_invokes_chat_model(self):
        """chat plan 调用普通聊天模型。"""
        state = base_state()
        state["plan"] = {
            "intent": "chat",
            "mode": "chat",
            "plan_steps": [{"step_id": "step_1", "action": "chat", "tool_name": "", "args": {}, "reason": "普通对话"}],
            "current_step": 0,
            "decision_reason": "普通对话",
            "status": "ready",
        }

        with patch("agent_app.nodes.agent.invoke_with_fallback", return_value=AIMessage(content="你好")) as invoke:
            result = agent_node(state)

        invoke.assert_called_once()
        self.assertEqual(result["messages"][0].content, "你好")

    def test_agent_node_chat_plan_retries_empty_response(self):
        """chat plan 空回答时重试一次，避免最终输出空白。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="如何安装安全审计协议")]
        state["plan"] = {
            "intent": "chat",
            "mode": "chat",
            "plan_steps": [{"step_id": "step_1", "action": "chat", "tool_name": "", "args": {}, "reason": "普通对话"}],
            "current_step": 0,
            "decision_reason": "普通对话",
            "status": "ready",
        }

        with patch(
            "agent_app.nodes.agent.invoke_with_fallback",
            side_effect=[AIMessage(content=""), AIMessage(content="请先确认安全审计协议的具体产品或标准。")],
        ) as invoke:
            result = agent_node(state)

        self.assertEqual(invoke.call_count, 2)
        self.assertIn("请先确认", result["messages"][0].content)

    def test_agent_node_empty_response_uses_generic_fallback(self):
        """模型连续空回答时输出通用兜底。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="如何安装安全审计协议")]
        state["plan"] = {
            "intent": "chat",
            "mode": "chat",
            "plan_steps": [{"step_id": "step_1", "action": "chat", "tool_name": "", "args": {}, "reason": "planner 错判普通回答"}],
            "current_step": 0,
            "decision_reason": "planner 错判普通回答",
            "status": "ready",
        }

        with patch("agent_app.nodes.agent.invoke_with_fallback", side_effect=[AIMessage(content=""), AIMessage(content="")]):
            result = agent_node(state)

        self.assertIn("我这次没有生成有效回答", result["messages"][0].content)
        self.assertIn("如何安装安全审计协议", result["messages"][0].content)

    def test_agent_node_chat_plan_does_not_emit_thinking_progress(self):
        """普通 chat plan 不输出思考进度。"""
        state = base_state()
        state["plan"] = {
            "intent": "chat",
            "mode": "chat",
            "plan_steps": [{"step_id": "step_1", "action": "chat", "tool_name": "", "args": {}, "reason": "普通对话"}],
            "current_step": 0,
            "decision_reason": "普通对话",
            "status": "ready",
        }

        with patch("agent_app.nodes.agent.invoke_with_fallback", return_value=AIMessage(content="你好")), patch(
            "agent_app.nodes.agent.emit_progress"
        ) as emit_progress:
            agent_node(state)

        emit_progress.assert_not_called()

    def test_agent_node_clarification_plan_returns_question_without_llm(self):
        """clarification plan 直接输出追问，不调用 LLM 或工具。"""
        state = base_state()
        state["plan"] = {
            "intent": "clarification",
            "mode": "clarification",
            "plan_steps": [
                {
                    "step_id": "step_1",
                    "action": "clarification",
                    "tool_name": "",
                    "args": {},
                    "reason": "本地判断：需要澄清",
                }
            ],
            "current_step": 0,
            "decision_reason": "本地判断：需要澄清",
            "clarification_question": "你想让我处理哪段内容？可以直接贴文本，或用 @文件路径 发给我。",
            "missing_info": "处理对象",
            "clarification_reason": "操作类请求缺少明确处理对象。",
            "status": "ready",
        }

        with (
            patch("agent_app.nodes.agent.invoke_with_fallback") as invoke,
            patch("agent_app.nodes.agent.get_llm_with_tools") as get_tools_model,
            patch("agent_app.nodes.agent.invoke_tool_agent") as invoke_tool,
        ):
            result = agent_node(state)

        invoke.assert_not_called()
        get_tools_model.assert_not_called()
        invoke_tool.assert_not_called()
        self.assertIn("哪段内容", result["messages"][0].content)
        self.assertEqual(result["clarification"]["missing_info"], "处理对象")
        self.assertEqual(result["clarification"]["reason"], "操作类请求缺少明确处理对象。")

    def test_agent_node_rag_list_plan_returns_documents_without_llm(self):
        """rag_list plan 直接输出知识库文档列表。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="知识库有哪些")]
        state["plan"] = {
            "intent": "rag_list",
            "mode": "rag_list",
            "plan_steps": [{"step_id": "step_1", "action": "rag_list", "tool_name": "", "args": {}, "reason": "列出知识库文档"}],
            "current_step": 0,
            "decision_reason": "列出知识库文档",
            "status": "ready",
        }

        with (
            patch(
                "agent_app.nodes.agent.list_documents",
                return_value=[{"document_id": "doc1", "title": "demo.md", "chunk_count": 2, "path": "/tmp/demo.md"}],
            ),
            patch("agent_app.nodes.agent.invoke_with_fallback") as invoke,
            patch("agent_app.nodes.agent.get_llm_with_tools") as get_tools_model,
        ):
            result = agent_node(state)

        invoke.assert_not_called()
        get_tools_model.assert_not_called()
        self.assertIn("知识库当前共有 1 个文档", result["messages"][0].content)
        self.assertIn("doc1 | demo.md | 2 个片段", result["messages"][0].content)

    def test_with_context_includes_conversation_summary(self):
        """有会话摘要时注入摘要上下文。"""
        messages = [HumanMessage(content="继续")]

        result = with_context(messages, {}, [], "用户之前要求实现上下文压缩。")

        self.assertEqual(result[0].type, "system")
        self.assertIn("[会话摘要]", result[0].content)
        self.assertIn("上下文压缩", result[0].content)
        self.assertEqual(result[-1].content, "继续")

    def test_with_context_omits_empty_conversation_summary(self):
        """没有会话摘要时不额外注入。"""
        messages = [HumanMessage(content="你好")]

        result = with_context(messages, {}, [], "")

        self.assertEqual(result, messages)

    def test_agent_node_tool_summary_streams_without_converting_pseudo_tool_call(self):
        """工具结果总结可流式输出，但伪工具调用不应再次触发工具。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="长沙未来三天天气如何"), ToolMessage(content="天气结果", tool_call_id="tool_1")]
        pseudo_tool_call = AIMessage(
            content=(
                "<tool_call>"
                "<function=web_search><parameter=query>长沙未来三天天气</parameter></function>"
                "</tool_call>"
            )
        )

        with patch("agent_app.nodes.agent.invoke_with_fallback", return_value=pseudo_tool_call) as invoke, patch(
            "agent_app.nodes.agent.emit_progress"
        ) as emit_progress:
            result = agent_node(state)

        emit_progress.assert_called_once_with("正在整理工具结果...", event="summary_started", node="agent")
        invoke.assert_called_once()
        self.assertNotIn("tags", invoke.call_args.kwargs)
        self.assertEqual(result["messages"][0].content, pseudo_tool_call.content)
        self.assertFalse(getattr(result["messages"][0], "tool_calls", []))
        self.assertNotIn("last_tool_request", result)

    def test_agent_node_tool_agent_plan_invokes_llm_with_tools(self):
        """tool_agent plan 调用绑定工具模型。"""
        class FakeToolModel:
            def __init__(self):
                self.called = False

            def invoke(self, messages):
                self.called = True
                return AIMessage(content="")

        state = base_state()
        state["plan"] = {
            "intent": "tool_agent",
            "mode": "tool_agent",
            "plan_steps": [{"step_id": "step_1", "action": "tool_agent", "tool_name": "", "args": {}, "reason": "需要工具"}],
            "current_step": 0,
            "decision_reason": "需要工具",
            "status": "ready",
        }
        fake_model = FakeToolModel()

        with patch("agent_app.nodes.agent.get_llm_with_tools", return_value=fake_model), patch(
            "agent_app.nodes.agent.invoke_with_fallback", return_value=AIMessage(content="")
        ):
            result = agent_node(state)

        self.assertTrue(fake_model.called)
        self.assertIn("没能生成有效", result["messages"][0].content)

    def test_agent_node_converts_pseudo_tool_call_to_real_tool_call(self):
        """模型误吐的伪工具调用会转换为真实 tool_calls。"""
        class FakeToolModel:
            def with_config(self, tags):
                self.tags = tags
                return self

            def invoke(self, messages):
                return AIMessage(
                    content=(
                        "<tool_call>\n"
                        "<function=web_search>\n"
                        "<parameter=query>今日黄金价格</parameter>\n"
                        "<parameter=max_results>5</parameter>\n"
                        "</function>\n"
                        "</tool_call>"
                    )
                )

        state = base_state()
        state["messages"] = [HumanMessage(content="今天金价")]
        state["plan"] = {
            "intent": "tool_agent",
            "mode": "tool_agent",
            "plan_steps": [{"step_id": "step_1", "action": "tool_agent", "tool_name": "", "args": {}, "reason": "需要实时价格"}],
            "current_step": 0,
            "decision_reason": "需要实时价格",
            "candidate_tool_names": ["web_search"],
            "status": "ready",
        }
        fake_model = FakeToolModel()

        with patch("agent_app.nodes.agent.get_chat_llm") as get_chat_llm:
            get_chat_llm.return_value.bind_tools.return_value = fake_model
            result = agent_node(state)

        tool_calls = result["messages"][0].tool_calls
        self.assertEqual(tool_calls[0]["name"], "web_search")
        self.assertEqual(tool_calls[0]["args"], {"query": "今日黄金价格"})
        self.assertEqual(result["last_tool_request"]["tool_calls"][0]["name"], "web_search")
        self.assertEqual(result["attempted_tools"], ["web_search"])
        self.assertEqual(fake_model.tags, ["nostream"])

    def test_agent_node_tool_agent_falls_back_to_web_search_call(self):
        """工具模式下模型未调用工具时兜底生成搜索工具调用。"""
        class FakeToolModel:
            def with_config(self, tags):
                self.tags = tags
                return self

            def invoke(self, messages):
                return AIMessage(content="未来金价可能上涨。")

        state = base_state()
        state["messages"] = [HumanMessage(content="做一个未来3-6个月的金价预测")]
        state["input_context"] = {"normalized_text": "做一个未来3-6个月的金价预测"}
        state["plan"] = {
            "intent": "tool_agent",
            "mode": "tool_agent",
            "plan_steps": [{"step_id": "step_1", "action": "tool_agent", "tool_name": "", "args": {}, "reason": "需要外部信息"}],
            "current_step": 0,
            "decision_reason": "需要外部信息",
            "candidate_tool_names": ["web_search"],
            "status": "ready",
        }
        fake_model = FakeToolModel()

        with patch("agent_app.nodes.agent.get_chat_llm") as get_chat_llm:
            get_chat_llm.return_value.bind_tools.return_value = fake_model
            result = agent_node(state)

        tool_calls = result["messages"][0].tool_calls
        self.assertEqual(tool_calls[0]["name"], "web_search")
        self.assertEqual(tool_calls[0]["args"], {"query": "做一个未来3-6个月的金价预测"})
        self.assertEqual(result["attempted_tools"], ["web_search"])

    def test_parse_pseudo_tool_calls_ignores_unknown_tools(self):
        """伪工具调用只接受已注册工具。"""
        content = (
            "<tool_call>"
            "<function=unknown_tool><parameter=query>test</parameter></function>"
            "<function=web_search><parameter=query>LangGraph</parameter></function>"
            "</tool_call>"
        )

        tool_calls = parse_pseudo_tool_calls(content)

        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "web_search")
        self.assertEqual(tool_calls[0]["args"], {"query": "LangGraph"})

    def test_invoke_tool_agent_binds_candidate_tools_only(self):
        """tool_agent 只绑定 plan 中记录的候选工具。"""
        class FakeToolModel:
            def invoke(self, messages):
                return AIMessage(content="")

        class FakeLLM:
            def __init__(self):
                self.bound_tool_names = []

            def bind_tools(self, bound_tools):
                self.bound_tool_names = [tool.name for tool in bound_tools]
                return FakeToolModel()

        fake_llm = FakeLLM()

        with patch("agent_app.nodes.agent.get_chat_llm", return_value=fake_llm):
            invoke_tool_agent([], {"candidate_tool_names": ["fetch_url"]})

        self.assertEqual(fake_llm.bound_tool_names, ["fetch_url"])

    def test_nodes_import_does_not_initialize_chat_model(self):
        """导入 agent 节点模块时不初始化聊天模型。"""
        import agent_app.nodes.agent as agent_module

        with patch("agent_app.nodes.agent.get_chat_model", side_effect=AssertionError("不应导入时初始化模型")):
            reloaded = importlib.reload(agent_module)

        self.assertIsNone(reloaded._chat_llm)
        self.assertIsNone(reloaded._llm_with_tools)


if __name__ == "__main__":
    unittest.main()
