"""RAG 知识库接口。"""

from agent_app.rag.store import (
    KnowledgeBaseError,
    add_document,
    clear_knowledge_base,
    delete_document,
    list_documents,
    rebuild_knowledge_base,
    search_knowledge,
    sync_knowledge_base,
)


__all__ = [
    "KnowledgeBaseError",
    "add_document",
    "clear_knowledge_base",
    "delete_document",
    "list_documents",
    "rebuild_knowledge_base",
    "search_knowledge",
    "sync_knowledge_base",
]
