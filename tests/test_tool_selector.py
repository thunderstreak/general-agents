"""规划选择器测试。"""

import importlib
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent_app.tool_selector import parse_planner_payload, select_plan, should_enter_tool_mode
from agent_app.tools import candidate_tool_names_for_text


class ToolSelectorTest(unittest.TestCase):
    """规划选择器本地校验测试。"""

    def test_parse_planner_payload_tool_agent(self):
        """合法 tool_agent JSON 转换为候选工具计划。"""
        selection = parse_planner_payload(
            {
                "mode": "tool_agent",
                "intent": "search_events",
                "candidate_tool_names": ["web_search", "unknown"],
                "tool_name": "",
                "args": {},
                "confidence": 0.94,
                "reason": "需要外部资料",
            }
        )

        self.assertEqual(selection.action, "tool_agent")
        self.assertEqual(selection.args["_candidate_tool_names"], ["web_search"])

    def test_parse_planner_payload_tool_adds_candidate(self):
        """直接工具模式自动补齐候选工具名。"""
        selection = parse_planner_payload(
            {
                "mode": "tool",
                "candidate_tool_names": [],
                "tool_name": "web_search",
                "args": {"query": "OpenAI"},
                "confidence": 0.95,
                "reason": "直接搜索",
            }
        )

        self.assertEqual(selection.action, "tool")
        self.assertEqual(selection.tool_name, "web_search")
        self.assertEqual(selection.args["_candidate_tool_names"], ["web_search"])
        self.assertEqual(selection.args["query"], "OpenAI")

    def test_parse_planner_payload_clarification(self):
        """clarification JSON 转换为追问计划。"""
        selection = parse_planner_payload(
            {
                "mode": "clarification",
                "candidate_tool_names": [],
                "tool_name": "",
                "args": {},
                "clarification_question": "你想查询什么内容？请补充关键词或范围。",
                "missing_info": "查询内容",
                "confidence": 0.9,
                "reason": "缺少查询对象",
            }
        )

        self.assertEqual(selection.action, "clarification")
        self.assertEqual(selection.args["missing_info"], "查询内容")
        self.assertIn("查询什么内容", selection.args["question"])

    def test_parse_planner_payload_invalid_mode(self):
        """非法 mode 回退 auto。"""
        selection = parse_planner_payload({"mode": "browse", "confidence": 0.9})

        self.assertEqual(selection.action, "auto")
        self.assertIn("未知 mode", selection.reason)

    def test_parse_planner_payload_unknown_tool(self):
        """未知工具回退 auto。"""
        selection = parse_planner_payload(
            {
                "mode": "tool",
                "tool_name": "search_internet",
                "args": {},
                "confidence": 0.9,
            }
        )

        self.assertEqual(selection.action, "auto")
        self.assertIn("未知工具", selection.reason)

    def test_parse_planner_payload_low_confidence_tool_falls_back_chat(self):
        """低置信度工具决策回退 chat。"""
        selection = parse_planner_payload(
            {
                "mode": "tool_agent",
                "candidate_tool_names": ["web_search"],
                "args": {},
                "confidence": 0.3,
                "reason": "不确定",
            }
        )

        self.assertEqual(selection.action, "chat")
        self.assertIn("低置信度", selection.reason)

    def test_select_plan_uses_planner_prompt_and_nostream_model(self):
        """select_plan 调用结构化 planner prompt。"""
        payload = {
            "mode": "tool_agent",
            "intent": "search",
            "candidate_tool_names": ["web_search"],
            "tool_name": "",
            "args": {},
            "confidence": 0.95,
            "reason": "需要搜索",
        }
        fake_model = unittest.mock.Mock()
        fake_model.invoke.return_value = AIMessage(content=json.dumps(payload, ensure_ascii=False))

        with patch("agent_app.tool_selector._get_selector_llm", return_value=fake_model):
            selection = select_plan("总结去年一年发生的世界大事件", {"normalized_text": "总结去年一年发生的世界大事件"})

        self.assertEqual(selection.action, "tool_agent")
        self.assertEqual(selection.args["_candidate_tool_names"], ["web_search"])
        system_message = fake_model.invoke.call_args.args[0][0]
        self.assertIn("结构化规划器", system_message.content)
        self.assertIn("web_search", system_message.content)

    def test_select_plan_invalid_json_falls_back_auto(self):
        """planner 非法 JSON 回退 auto。"""
        fake_model = unittest.mock.Mock()
        fake_model.invoke.return_value = AIMessage(content="不是 JSON")

        with patch("agent_app.tool_selector._get_selector_llm", return_value=fake_model):
            selection = select_plan("讲个笑话", {})

        self.assertEqual(selection.action, "auto")
        self.assertIn("规划失败", selection.reason)

    def test_should_enter_tool_mode_keeps_lightweight_compatibility(self):
        """旧兼容函数只做轻量明确工具判断。"""
        self.assertFalse(should_enter_tool_mode("你好"))
        self.assertTrue(should_enter_tool_mode("总结 https://example.com 这篇文章"))
        self.assertTrue(should_enter_tool_mode("今天天气如何"))
        self.assertFalse(should_enter_tool_mode("请记住我喜欢中文回答"))

    def test_candidate_tools_keep_deterministic_candidates(self):
        """候选工具仍保留确定性筛选能力。"""
        self.assertEqual(candidate_tool_names_for_text("总结 https://example.com 这篇文章"), ["fetch_url"])
        self.assertEqual(candidate_tool_names_for_text("今天天气如何"), ["get_weather"])
        self.assertEqual(candidate_tool_names_for_text("长沙未来三天天气如何"), ["get_weather_forecast"])

    def test_tool_selector_import_does_not_initialize_model(self):
        """导入 tool_selector 时不初始化规划模型。"""
        import agent_app.tool_selector as tool_selector_module

        with patch(
            "agent_app.tool_selector.get_tool_selector_model",
            side_effect=AssertionError("不应导入时初始化模型"),
        ):
            reloaded = importlib.reload(tool_selector_module)

        self.assertIsNone(reloaded._selector_llm)


if __name__ == "__main__":
    unittest.main()
