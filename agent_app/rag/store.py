"""本地 RAG 知识库存储。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent_app.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_CANDIDATE_K,
    RAG_EMBEDDING_API_KEY,
    RAG_EMBEDDING_BASE_URL,
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_PROVIDER,
    RAG_ENABLED,
    RAG_KEYWORD_WEIGHT,
    RAG_STORE_DIR,
    RAG_TOP_K,
    MODEL_TIMEOUT_SECONDS,
)
from agent_app.file_inputs.parser import parse_file
from agent_app.rag.embeddings import OpenAICompatibleEmbeddings
from agent_app.rag.metadata import (
    KnowledgeDocument,
    chunk_id,
    chunk_source_metadata,
    chunks_path,
    content_hash,
    document_id,
    documents_path,
    load_chunk_records,
    load_documents,
    nearest_marker_value,
    remove_chunk_records,
    replace_chunk_records,
    save_chunk_records,
    save_documents,
)
from agent_app.rag.query import keyword_score_for, normalize_query as _normalize_query, query_terms, rerank_results as _rerank_results
from agent_app.rag.vector_store import emit_progress, raw_collection, reset_vector_store


ProgressCallback = Callable[[str], None]
_EMBEDDINGS_CACHE: dict[tuple[Any, ...], Any] = {}


class KnowledgeBaseError(RuntimeError):
    """知识库操作失败。"""


def add_document(path: str) -> dict[str, Any]:
    """导入本地文档到 Chroma 知识库。"""
    _ensure_rag_enabled()
    file_path = Path(path).expanduser().resolve()
    parsed = parse_file(str(file_path))
    if parsed.error:
        raise KnowledgeBaseError(parsed.error)
    if parsed.kind == "image":
        raise KnowledgeBaseError("RAG 知识库暂不支持图片文件。")

    content = (parsed.content or "").strip()
    if not content:
        raise KnowledgeBaseError("文件未提取到可写入知识库的文本内容。")

    documents = _load_documents()
    document_id = _document_id(file_path)
    content_hash = _content_hash(content)
    document_version = content_hash[:12]
    current = documents.get(document_id)
    if current and current.get("active", True) and current.get("content_hash") == content_hash:
        return {"status": "unchanged", "document": current}

    if current and current.get("chunk_ids"):
        _delete_vectors(current.get("chunk_ids", []))

    chunks = _split_text(content)
    if not chunks:
        raise KnowledgeBaseError("文件切分后没有可写入知识库的文本片段。")

    chunk_ids = [_chunk_id(document_id, content_hash, index) for index, _ in enumerate(chunks)]
    chunk_records = []
    langchain_documents = []
    for index, chunk in enumerate(chunks):
        metadata = {
            "document_id": document_id,
            "chunk_id": chunk_ids[index],
            "chunk_index": index,
            "source": str(file_path),
            "title": file_path.name,
            "content_hash": content_hash,
            "document_version": document_version,
            **_chunk_source_metadata(content, chunk),
        }
        langchain_documents.append(Document(page_content=chunk, metadata=metadata))
        chunk_records.append({**metadata, "content": chunk})
    try:
        _vector_store().add_documents(langchain_documents, ids=chunk_ids)

        now = time.time()
        created_at = float(current.get("created_at", now)) if current else now
        document = KnowledgeDocument(
            document_id=document_id,
            title=file_path.name,
            path=str(file_path),
            content_hash=content_hash,
            created_at=created_at,
            updated_at=now,
            chunk_count=len(chunk_ids),
            chunk_ids=chunk_ids,
            active=True,
        ).to_dict()
        documents[document_id] = document
        _save_documents(documents)
        _replace_chunk_records(document_id, chunk_records)
        return {"status": "added" if not current else "updated", "document": document}
    except KeyboardInterrupt:
        _rollback_document_import(document_id, chunk_ids, current, documents)
        raise


def list_documents() -> list[dict[str, Any]]:
    """列出 active 知识库文档。"""
    documents = [item for item in _load_documents().values() if item.get("active", True)]
    return sorted(documents, key=lambda item: item.get("updated_at", 0), reverse=True)


def delete_document(document_id: str) -> bool:
    """删除指定知识库文档及其向量。"""
    documents = _load_documents()
    document = documents.get(document_id)
    if not document or not document.get("active", True):
        return False
    _delete_vectors(document.get("chunk_ids", []))
    _remove_chunk_records(document_id)
    document["active"] = False
    document["updated_at"] = time.time()
    documents[document_id] = document
    _save_documents(documents)
    return True


def clear_knowledge_base() -> int:
    """清空本地知识库。"""
    count = len(list_documents())
    _reset_vector_store()
    _save_documents({})
    _save_chunk_records([])
    return count


def sync_knowledge_base() -> dict[str, Any]:
    """同步所有 active 文档，文件内容变更时重新导入。"""
    summary = {"checked": 0, "updated": 0, "unchanged": 0, "missing": 0, "failed": 0, "errors": []}
    for document in list_documents():
        summary["checked"] += 1
        path = document.get("path", "")
        if not Path(path).expanduser().is_file():
            summary["missing"] += 1
            summary["errors"].append({"document_id": document.get("document_id", ""), "path": path, "error": "文件不存在。"})
            continue
        try:
            result = add_document(path)
        except KnowledgeBaseError as exc:
            summary["failed"] += 1
            summary["errors"].append({"document_id": document.get("document_id", ""), "path": path, "error": str(exc)})
            continue
        if result["status"] == "unchanged":
            summary["unchanged"] += 1
        else:
            summary["updated"] += 1
    return summary


def rebuild_knowledge_base() -> dict[str, Any]:
    """根据 metadata 中的 active 文档重建 Chroma 索引。"""
    active_documents = list_documents()
    paths = [item.get("path", "") for item in active_documents if item.get("path")]
    _reset_vector_store()
    _save_documents({})
    _save_chunk_records([])

    summary = {"checked": len(paths), "rebuilt": 0, "missing": 0, "failed": 0, "errors": []}
    for path in paths:
        if not Path(path).expanduser().is_file():
            summary["missing"] += 1
            summary["errors"].append({"path": path, "error": "文件不存在。"})
            continue
        try:
            add_document(path)
        except KnowledgeBaseError as exc:
            summary["failed"] += 1
            summary["errors"].append({"path": path, "error": str(exc)})
            continue
        summary["rebuilt"] += 1
    return summary


def search_knowledge(query: str, top_k: int | None = None, progress: ProgressCallback | None = None) -> list[dict[str, Any]]:
    """从 Chroma 知识库检索相关片段。"""
    normalized_query = normalize_query(query)
    if not RAG_ENABLED or not normalized_query or not list_documents():
        return []

    limit = top_k or RAG_TOP_K
    candidate_k = max(RAG_CANDIDATE_K, limit)
    vector_store = _vector_store(progress=progress)
    embeddings = _embeddings(progress=progress)
    _check_cancelled()
    _emit_progress(progress, "生成查询向量...")
    query_vector = embeddings.embed_query(normalized_query)
    _check_cancelled()
    _emit_progress(progress, "查询知识库...")
    results = vector_store.similarity_search_by_vector_with_relevance_scores(query_vector, k=candidate_k)
    _check_cancelled()
    _emit_progress(progress, "整理知识库结果...")
    retrieval_results = []
    for document, score in results:
        metadata = dict(getattr(document, "metadata", {}) or {})
        retrieval_results.append(
            {
                "source": metadata.get("source", ""),
                "title": metadata.get("title", ""),
                "document_id": metadata.get("document_id", ""),
                "chunk_id": metadata.get("chunk_id", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                "content_hash": metadata.get("content_hash", ""),
                "document_version": metadata.get("document_version", ""),
                "page": metadata.get("page", ""),
                "sheet": metadata.get("sheet", ""),
                "content": getattr(document, "page_content", ""),
                "vector_score": round(float(score), 4),
                "keyword_score": _keyword_score(normalized_query, metadata, getattr(document, "page_content", "")),
            }
        )
    return rerank_results(normalized_query, retrieval_results)[:limit]


def normalize_query(query: str) -> str:
    """规范化 RAG 查询文本。"""
    return _normalize_query(query)


def rerank_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """结合向量分数和关键词命中重排结果。"""
    return _rerank_results(query, results, RAG_KEYWORD_WEIGHT)


def _ensure_rag_enabled() -> None:
    """检查 RAG 是否开启。"""
    if not RAG_ENABLED:
        raise KnowledgeBaseError("RAG 知识库未开启，请设置 RAG_ENABLED=true。")


def _vector_store(progress: ProgressCallback | None = None) -> Chroma:
    """创建 Chroma vector store。"""
    return Chroma(
        collection_name=CHROMA_COLLECTION_NAME,
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=_embeddings(progress=progress),
    )


def _embeddings(progress: ProgressCallback | None = None):
    """创建 RAG embedding 模型。"""
    cache_key = _embedding_cache_key()
    if cache_key in _EMBEDDINGS_CACHE:
        return _EMBEDDINGS_CACHE[cache_key]

    if RAG_EMBEDDING_PROVIDER == "openai":
        embeddings = OpenAICompatibleEmbeddings(
            model=RAG_EMBEDDING_MODEL,
            base_url=RAG_EMBEDDING_BASE_URL,
            api_key=RAG_EMBEDDING_API_KEY,
            timeout=MODEL_TIMEOUT_SECONDS,
        )
        _EMBEDDINGS_CACHE[cache_key] = embeddings
        return embeddings
    if RAG_EMBEDDING_PROVIDER != "huggingface":
        raise KnowledgeBaseError(f"暂不支持的 RAG_EMBEDDING_PROVIDER：{RAG_EMBEDDING_PROVIDER}")
    _emit_progress(progress, "首次加载本地 embedding 模型...")
    _check_cancelled()
    embeddings = HuggingFaceEmbeddings(model_name=RAG_EMBEDDING_MODEL)
    _EMBEDDINGS_CACHE[cache_key] = embeddings
    return embeddings


def _embedding_cache_key() -> tuple[Any, ...]:
    """生成 embedding 缓存 key。"""
    return (
        RAG_EMBEDDING_PROVIDER,
        RAG_EMBEDDING_MODEL,
        RAG_EMBEDDING_BASE_URL,
        RAG_EMBEDDING_API_KEY,
        MODEL_TIMEOUT_SECONDS,
    )


def _clear_embeddings_cache() -> None:
    """清空 embedding 缓存，供测试使用。"""
    _EMBEDDINGS_CACHE.clear()


def _emit_progress(progress: ProgressCallback | None, message: str) -> None:
    """发送 RAG 内部阶段进度。"""
    emit_progress(progress, message)


def _check_cancelled() -> None:
    """在 RAG 阶段边界响应取消。"""
    return


def _split_text(content: str) -> list[str]:
    """切分文档文本。"""
    splitter = RecursiveCharacterTextSplitter(chunk_size=RAG_CHUNK_SIZE, chunk_overlap=RAG_CHUNK_OVERLAP)
    return [chunk.strip() for chunk in splitter.split_text(content) if chunk.strip()]


def _delete_vectors(chunk_ids: list[str]) -> None:
    """删除指定 chunk 向量。"""
    if not chunk_ids:
        return
    collection = _raw_collection()
    if collection is not None:
        collection.delete(ids=chunk_ids)


def _reset_vector_store() -> None:
    """清空 Chroma collection。"""
    reset_vector_store()


def _raw_collection():
    """获取不需要 embedding 的 Chroma collection。"""
    return raw_collection()


def _load_documents() -> dict[str, dict[str, Any]]:
    """读取文档 metadata。"""
    return load_documents(RAG_STORE_DIR)


def _save_documents(documents: dict[str, dict[str, Any]]) -> None:
    """保存文档 metadata。"""
    save_documents(documents, RAG_STORE_DIR)


def _documents_path() -> Path:
    """获取文档 metadata 路径。"""
    return documents_path(RAG_STORE_DIR)


def _chunks_path() -> Path:
    """获取 chunk metadata 路径。"""
    return chunks_path(RAG_STORE_DIR)


def _load_chunk_records() -> list[dict[str, Any]]:
    """读取 chunk metadata。"""
    return load_chunk_records(RAG_STORE_DIR)


def _save_chunk_records(records: list[dict[str, Any]]) -> None:
    """保存 chunk metadata。"""
    save_chunk_records(records, RAG_STORE_DIR)


def _replace_chunk_records(document_id: str, new_records: list[dict[str, Any]]) -> None:
    """替换单个文档的 chunk metadata。"""
    replace_chunk_records(document_id, new_records, RAG_STORE_DIR)


def _remove_chunk_records(document_id: str) -> None:
    """删除单个文档的 chunk metadata。"""
    remove_chunk_records(document_id, RAG_STORE_DIR)


def _rollback_document_import(document_id: str, chunk_ids: list[str], previous_document: dict | None, documents: dict[str, dict[str, Any]]) -> None:
    """导入被取消时尽量回滚新写入内容。"""
    _delete_vectors(chunk_ids)
    _remove_chunk_records(document_id)
    if previous_document:
        documents[document_id] = previous_document
    else:
        documents.pop(document_id, None)
    _save_documents(documents)


def _document_id(path: Path) -> str:
    """根据绝对路径生成稳定 document id。"""
    return document_id(path)


def _content_hash(content: str) -> str:
    """生成文档内容 hash。"""
    return content_hash(content)


def _chunk_id(document_id: str, content_hash: str, index: int) -> str:
    """生成稳定 chunk id。"""
    return chunk_id(document_id, content_hash, index)


def _chunk_source_metadata(content: str, chunk: str) -> dict[str, Any]:
    """提取 chunk 对应的轻量来源 metadata。"""
    return chunk_source_metadata(content, chunk)


def _nearest_marker_value(pattern, content: str, offset: int, group_name: str) -> str:
    """查找 offset 前最近的章节标记。"""
    return nearest_marker_value(pattern, content, offset, group_name)


def _keyword_score(query: str, metadata: dict[str, Any], content: str) -> float:
    """计算关键词命中分。"""
    return keyword_score_for(query, metadata, content)


def _query_terms(query: str) -> list[str]:
    """提取查询关键词。"""
    return query_terms(query)
