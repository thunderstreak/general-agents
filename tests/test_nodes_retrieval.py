"""Retrieval 节点测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agent_app.graph import retrieval_node
from agent_app.orchestrator import should_retrieve
from tests.helpers import base_state


class RetrievalNodeTest(unittest.TestCase):
    """retrieval_node 行为测试。"""

    def test_retrieval_placeholder(self):
        """RAG 预留节点在命中关键词时写入检索结果。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="根据知识库回答 LangGraph 是什么")]

        result = retrieval_node(state)

        self.assertTrue(should_retrieve("根据知识库回答 LangGraph 是什么"))
        self.assertEqual(result["retrieval_results"][0]["source"], "local_rag_placeholder")

    def test_retrieval_node_only_emits_progress_when_retrieving(self):
        """只有命中检索关键词时才输出检索进度。"""
        state = base_state()
        state["messages"] = [HumanMessage(content="今天天气 如何")]

        with patch("agent_app.nodes.retrieval.emit_progress") as emit_progress:
            retrieval_node(state)

        emit_progress.assert_not_called()

        state["messages"] = [HumanMessage(content="根据知识库回答 LangGraph 是什么")]
        with patch("agent_app.nodes.retrieval.emit_progress") as emit_progress:
            retrieval_node(state)

        emit_progress.assert_called_once_with("检索中...", node="retrieval")


if __name__ == "__main__":
    unittest.main()
