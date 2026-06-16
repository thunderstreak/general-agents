"""RAG 知识库存储测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from agent_app.rag import store


class RagStoreTest(unittest.TestCase):
    """RAG store 行为测试。"""

    def test_add_document_writes_metadata_and_vectors(self):
        """导入文档时写入 metadata 并调用 Chroma 写入向量。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("# LangGraph\nLangGraph 是图编排框架。", encoding="utf-8")
            vector_store = MagicMock()

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                result = store.add_document(str(file_path))
                documents = store.list_documents()
                chunks = store._load_chunk_records()

        self.assertEqual(result["status"], "added")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["title"], "demo.md")
        self.assertGreater(documents[0]["chunk_count"], 0)
        self.assertEqual(chunks[0]["document_id"], documents[0]["document_id"])
        self.assertIn("content", chunks[0])
        vector_store.add_documents.assert_called_once()

    def test_add_document_skips_unchanged_content(self):
        """重复导入未变化文档时不重复写入向量。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("同一份内容", encoding="utf-8")
            vector_store = MagicMock()

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                store.add_document(str(file_path))
                result = store.add_document(str(file_path))

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(vector_store.add_documents.call_count, 1)

    def test_delete_document_marks_inactive_and_deletes_vectors(self):
        """删除文档时删除向量并隐藏 metadata。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("需要删除的内容", encoding="utf-8")
            vector_store = MagicMock()
            raw_collection = MagicMock()

            with (
                _patch_rag_dirs(tmp_dir),
                patch("agent_app.rag.store._vector_store", return_value=vector_store),
                patch("agent_app.rag.store._raw_collection", return_value=raw_collection),
            ):
                document_id = store.add_document(str(file_path))["document"]["document_id"]
                deleted = store.delete_document(document_id)
                documents = store.list_documents()
                chunks = store._load_chunk_records()

        self.assertTrue(deleted)
        self.assertEqual(documents, [])
        self.assertEqual(chunks, [])
        raw_collection.delete.assert_called_once()

    def test_clear_does_not_create_embedding_vector_store(self):
        """清空知识库不应创建带 embedding 的 vector store。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store") as vector_store:
                count = store.clear_knowledge_base()

        self.assertEqual(count, 0)
        vector_store.assert_not_called()

    def test_add_document_rolls_back_on_cancel(self):
        """导入被取消时会回滚本轮 metadata。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("取消测试", encoding="utf-8")
            vector_store = MagicMock()
            vector_store.add_documents.side_effect = KeyboardInterrupt()

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                with self.assertRaises(KeyboardInterrupt):
                    store.add_document(str(file_path))
                documents = store.list_documents()
                chunks = store._load_chunk_records()

        self.assertEqual(documents, [])
        self.assertEqual(chunks, [])

    def test_search_knowledge_formats_results(self):
        """检索结果会转换为 retrieval_results 结构。"""
        document = Document(
            page_content="LangGraph 支持 StateGraph。",
            metadata={
                "source": "/tmp/demo.md",
                "title": "demo.md",
                "document_id": "doc1",
                "chunk_id": "chunk1",
                "chunk_index": 0,
                "document_version": "v1",
                "page": "3",
                "sheet": "Sheet1",
            },
        )
        vector_store = MagicMock()
        vector_store.similarity_search_with_relevance_scores.return_value = [(document, 0.87654)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                store._save_documents({"doc1": {"document_id": "doc1", "active": True, "updated_at": 1}})
                results = store.search_knowledge("LangGraph")

        self.assertEqual(results[0]["title"], "demo.md")
        self.assertEqual(results[0]["content"], "LangGraph 支持 StateGraph。")
        self.assertEqual(results[0]["vector_score"], 0.8765)
        self.assertGreaterEqual(results[0]["score"], results[0]["vector_score"])
        self.assertEqual(results[0]["document_version"], "v1")
        self.assertEqual(results[0]["page"], "3")
        self.assertEqual(results[0]["sheet"], "Sheet1")
        self.assertIn("vector_score", results[0])
        self.assertIn("keyword_score", results[0])

    def test_normalize_query_removes_rag_prefix(self):
        """查询规范化会去掉 RAG 触发前缀。"""
        query = store.normalize_query("根据知识库回答 LangGraph 是什么")

        self.assertEqual(query, "回答 LangGraph 是什么")

    def test_rerank_results_uses_keyword_boost(self):
        """rerank 会按关键词命中提升结果排序。"""
        results = [
            {"title": "A", "content": "无关内容", "vector_score": 0.8},
            {"title": "B", "content": "LangGraph 状态图", "vector_score": 0.7},
        ]

        with patch("agent_app.rag.store.RAG_KEYWORD_WEIGHT", 0.5):
            reranked = store.rerank_results("LangGraph 状态图", results)

        self.assertEqual(reranked[0]["title"], "B")
        self.assertGreater(reranked[0]["keyword_score"], 0)

    def test_add_document_writes_source_metadata(self):
        """导入文档时为 chunk 写入页码、sheet 和版本 metadata。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("## 第 2 页\nPDF 内容\n\n## 工作表：Sheet1\n表格内容", encoding="utf-8")
            vector_store = MagicMock()

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                store.add_document(str(file_path))

        documents_arg = vector_store.add_documents.call_args.args[0]
        metadata = documents_arg[0].metadata
        self.assertEqual(metadata["page"], "2")
        self.assertEqual(metadata["sheet"], "Sheet1")
        self.assertTrue(metadata["document_version"])

    def test_chroma_round_trip_with_fake_embeddings(self):
        """使用真实 Chroma 和假 embedding 完成写入与检索闭环。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("LangGraph 支持用 StateGraph 编排 agent。", encoding="utf-8")

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._embeddings", return_value=FakeEmbeddings()):
                store.add_document(str(file_path))
                results = store.search_knowledge("LangGraph")

        self.assertTrue(results)
        self.assertEqual(results[0]["title"], "demo.md")
        self.assertIn("LangGraph", results[0]["content"])

    def test_sync_updates_changed_document(self):
        """sync 会重新导入发生变化的文档。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("旧内容", encoding="utf-8")
            vector_store = MagicMock()

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._vector_store", return_value=vector_store):
                store.add_document(str(file_path))
                file_path.write_text("新内容", encoding="utf-8")
                summary = store.sync_knowledge_base()

        self.assertEqual(summary["checked"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(vector_store.add_documents.call_count, 2)

    def test_rebuild_recreates_index_from_metadata_paths(self):
        """rebuild 会根据 metadata 中的路径重建索引。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.md"
            file_path.write_text("LangGraph 重建测试。", encoding="utf-8")

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store._embeddings", return_value=FakeEmbeddings()):
                store.add_document(str(file_path))
                summary = store.rebuild_knowledge_base()
                results = store.search_knowledge("LangGraph")

        self.assertEqual(summary["rebuilt"], 1)
        self.assertTrue(results)
        self.assertEqual(results[0]["title"], "demo.md")

    def test_add_document_rejects_image(self):
        """RAG 知识库不接受图片文件。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "demo.png"
            image_path.write_bytes(b"fake")

            with _patch_rag_dirs(tmp_dir), patch("agent_app.rag.store.parse_file") as parse_file:
                parse_file.return_value = type("Parsed", (), {"error": "", "kind": "image", "content": "", "path": str(image_path)})()
                with self.assertRaises(store.KnowledgeBaseError):
                    store.add_document(str(image_path))

    def test_embeddings_can_use_openai_provider(self):
        """embedding provider 可切换为 OpenAI。"""
        with patch("agent_app.rag.store.RAG_EMBEDDING_PROVIDER", "openai"):
            result = store._embeddings()

        self.assertEqual(result.model, store.RAG_EMBEDDING_MODEL)


def _patch_rag_dirs(tmp_dir: str):
    """patch RAG 存储目录。"""
    return patch.multiple(
        store,
        RAG_STORE_DIR=str(Path(tmp_dir) / "knowledge"),
        CHROMA_PERSIST_DIR=str(Path(tmp_dir) / "knowledge" / "chroma"),
    )


class FakeEmbeddings:
    """测试用固定 embedding。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """生成文档向量。"""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量。"""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """生成简单确定性向量。"""
        if "LangGraph" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


if __name__ == "__main__":
    unittest.main()
