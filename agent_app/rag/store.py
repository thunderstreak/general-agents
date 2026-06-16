"""本地 RAG 知识库存储。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import chromadb
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


DOCUMENTS_FILE_NAME = "documents.json"
CHUNKS_FILE_NAME = "chunks.jsonl"
PDF_PAGE_PATTERN = re.compile(r"^## 第 (?P<page>\d+) 页$", re.MULTILINE)
XLSX_SHEET_PATTERN = re.compile(r"^## 工作表：(?P<sheet>.+)$", re.MULTILINE)
ProgressCallback = Callable[[str], None]
_EMBEDDINGS_CACHE: dict[tuple[Any, ...], Any] = {}


class KnowledgeBaseError(RuntimeError):
    """知识库操作失败。"""


@dataclass
class KnowledgeDocument:
    """知识库文档 metadata。"""

    document_id: str
    title: str
    path: str
    content_hash: str
    created_at: float
    updated_at: float
    chunk_count: int
    chunk_ids: list[str]
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 字典。"""
        return asdict(self)


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
    text = str(query or "")
    for prefix in ("根据知识库", "根据文档", "根据资料", "从知识库", "检索", "查询知识库"):
        text = text.replace(prefix, " ")
    return " ".join(text.split())


def rerank_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """结合向量分数和关键词命中重排结果。"""
    reranked = []
    for item in results:
        vector_score = float(item.get("vector_score", item.get("score", 0.0)) or 0.0)
        keyword_score = float(item.get("keyword_score", _keyword_score(query, item, item.get("content", ""))) or 0.0)
        combined_score = vector_score + keyword_score * RAG_KEYWORD_WEIGHT
        updated = dict(item)
        updated["keyword_score"] = round(keyword_score, 4)
        updated["score"] = round(combined_score, 4)
        reranked.append(updated)
    return sorted(reranked, key=lambda item: item.get("score", 0.0), reverse=True)


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
    if progress is not None:
        progress(message)


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
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        try:
            client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
    except Exception:
        pass


def _raw_collection():
    """获取不需要 embedding 的 Chroma collection。"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        return client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        return None


def _load_documents() -> dict[str, dict[str, Any]]:
    """读取文档 metadata。"""
    path = _documents_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_documents = data.get("documents", []) if isinstance(data, dict) else data
    documents = {}
    for item in raw_documents:
        if isinstance(item, dict) and item.get("document_id"):
            documents[item["document_id"]] = item
    return documents


def _save_documents(documents: dict[str, dict[str, Any]]) -> None:
    """保存文档 metadata。"""
    path = _documents_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"documents": sorted(documents.values(), key=lambda item: item.get("updated_at", 0), reverse=True)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _documents_path() -> Path:
    """获取文档 metadata 路径。"""
    return Path(RAG_STORE_DIR) / DOCUMENTS_FILE_NAME


def _chunks_path() -> Path:
    """获取 chunk metadata 路径。"""
    return Path(RAG_STORE_DIR) / CHUNKS_FILE_NAME


def _load_chunk_records() -> list[dict[str, Any]]:
    """读取 chunk metadata。"""
    path = _chunks_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("chunk_id"):
            records.append(item)
    return records


def _save_chunk_records(records: list[dict[str, Any]]) -> None:
    """保存 chunk metadata。"""
    path = _chunks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _replace_chunk_records(document_id: str, new_records: list[dict[str, Any]]) -> None:
    """替换单个文档的 chunk metadata。"""
    records = [item for item in _load_chunk_records() if item.get("document_id") != document_id]
    records.extend(new_records)
    _save_chunk_records(records)


def _remove_chunk_records(document_id: str) -> None:
    """删除单个文档的 chunk metadata。"""
    records = [item for item in _load_chunk_records() if item.get("document_id") != document_id]
    _save_chunk_records(records)


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
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def _content_hash(content: str) -> str:
    """生成文档内容 hash。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunk_id(document_id: str, content_hash: str, index: int) -> str:
    """生成稳定 chunk id。"""
    return f"{document_id}:{content_hash[:12]}:{index}"


def _chunk_source_metadata(content: str, chunk: str) -> dict[str, Any]:
    """提取 chunk 对应的轻量来源 metadata。"""
    start = content.find(chunk)
    if start < 0:
        start = 0
    end = start + len(chunk)
    metadata: dict[str, Any] = {}
    page = _nearest_marker_value(PDF_PAGE_PATTERN, content, end, "page")
    if page:
        metadata["page"] = page
    sheet = _nearest_marker_value(XLSX_SHEET_PATTERN, content, end, "sheet")
    if sheet:
        metadata["sheet"] = sheet
    return metadata


def _nearest_marker_value(pattern: re.Pattern, content: str, offset: int, group_name: str) -> str:
    """查找 offset 前最近的章节标记。"""
    value = ""
    for match in pattern.finditer(content):
        if match.start() > offset:
            break
        value = match.group(group_name).strip()
    return value


def _keyword_score(query: str, metadata: dict[str, Any], content: str) -> float:
    """计算关键词命中分。"""
    terms = _query_terms(query)
    if not terms:
        return 0.0
    haystack = f"{metadata.get('title', '')} {metadata.get('source', '')} {content}".lower()
    hits = sum(1 for term in terms if term.lower() in haystack)
    return hits / len(terms)


def _query_terms(query: str) -> list[str]:
    """提取查询关键词。"""
    text = normalize_query(query)
    raw_terms = re.findall(r"[\w\u4e00-\u9fff]+", text)
    stopwords = {"根据", "知识库", "文档", "资料", "回答", "什么", "一下", "这个", "关于", "请", "帮我"}
    terms = [term for term in raw_terms if len(term) > 1 and term not in stopwords]
    return list(dict.fromkeys(terms))
