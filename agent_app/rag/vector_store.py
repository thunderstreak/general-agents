"""RAG 向量库与 embedding。"""

from __future__ import annotations

from typing import Callable

import chromadb

from agent_app.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
)


ProgressCallback = Callable[[str], None]


def delete_vectors(chunk_ids: list[str]) -> None:
    """删除指定 chunk 向量。"""
    if not chunk_ids:
        return
    collection = raw_collection()
    if collection is not None:
        collection.delete(ids=chunk_ids)


def reset_vector_store() -> None:
    """清空 Chroma collection。"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        try:
            client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
    except Exception:
        pass


def raw_collection():
    """获取不需要 embedding 的 Chroma collection。"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        return client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        return None


def emit_progress(progress: ProgressCallback | None, message: str) -> None:
    """发送 RAG 内部阶段进度。"""
    if progress is not None:
        progress(message)


def check_cancelled() -> None:
    """在 RAG 阶段边界响应取消。"""
    return
