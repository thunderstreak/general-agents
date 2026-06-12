"""Response 节点测试。"""

import unittest

from langchain_core.messages import AIMessage

from agent_app.graph import response_node
from agent_app.output import build_response
from tests.helpers import base_state


class ResponseNodeTest(unittest.TestCase):
    """response_node 行为测试。"""

    def test_response_node_builds_final_response(self):
        """response node 输出统一结构。"""
        state = base_state()
        state["messages"].append(AIMessage(content="回答内容"))
        state["tool_calls"] = [{"tool_name": "web_search"}]
        state["memory_updated"] = True

        result = response_node(state)

        self.assertEqual(result["final_response"]["content"], "回答内容")
        self.assertEqual(result["final_response"]["tool_calls"], [{"tool_name": "web_search"}])
        self.assertTrue(result["final_response"]["memory_updated"])

    def test_build_response_includes_error(self):
        """统一输出包含错误信息。"""
        state = base_state()
        state["messages"].append(AIMessage(content="失败"))
        state["last_error"] = {"message": "工具失败"}

        response = build_response(state)

        self.assertEqual(response["errors"][0]["message"], "工具失败")

    def test_response_node_renders_reflection_question(self):
        """reflection 追问输出面向用户的问题。"""
        state = base_state()
        state["reflection"] = {
            "status": "ask_user",
            "reason": "请提供城市名",
            "next_action": "response",
            "missing_info": "城市",
            "retry_count": 0,
        }
        state["tool_errors"] = [{"message": "请提供城市名"}]

        result = response_node(state)

        self.assertEqual(result["final_response"]["content"], "我还需要你补充城市后才能继续。")
        self.assertEqual(result["final_response"]["status"], "success")
        self.assertEqual(result["final_response"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
