"""RAG embedding 客户端测试。"""

import unittest
from unittest.mock import MagicMock, patch

from agent_app.rag.embeddings import OpenAICompatibleEmbeddings


class RagEmbeddingsTest(unittest.TestCase):
    """OpenAI-compatible embedding 客户端测试。"""

    def test_embed_documents_sends_raw_strings(self):
        """文档 embedding 请求应直接发送字符串数组。"""
        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [1, 2]},
                {"index": 1, "embedding": [3, 4]},
            ]
        }
        client = OpenAICompatibleEmbeddings(
            model="text-embedding-bge-small-zh-v1.5",
            base_url="http://127.0.0.1:1234/v1",
            api_key="not-needed",
            timeout=3,
        )

        with patch("agent_app.rag.embeddings.requests.post", return_value=response) as post:
            result = client.embed_documents(["第一段", "第二段"])

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["input"], ["第一段", "第二段"])
        self.assertEqual(result, [[1.0, 2.0], [3.0, 4.0]])

    def test_embed_query_returns_first_embedding(self):
        """查询 embedding 返回第一条向量。"""
        response = MagicMock()
        response.json.return_value = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        client = OpenAICompatibleEmbeddings("model", "http://127.0.0.1:1234/v1", "key")

        with patch("agent_app.rag.embeddings.requests.post", return_value=response):
            result = client.embed_query("问题")

        self.assertEqual(result, [0.1, 0.2])


if __name__ == "__main__":
    unittest.main()
