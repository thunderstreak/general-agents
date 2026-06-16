"""CLI RAG 命令处理。"""

from collections.abc import Callable
from dataclasses import dataclass

from agent_app.rag import KnowledgeBaseError


@dataclass(frozen=True)
class RagOperations:
    """RAG 命令依赖操作。"""

    add_document: Callable[[str], dict]
    list_documents: Callable[[], list[dict]]
    delete_document: Callable[[str], bool]
    clear_knowledge_base: Callable[[], int]
    sync_knowledge_base: Callable[[], dict]
    rebuild_knowledge_base: Callable[[], dict]


def handle_rag_command(arg: str, run_cancellable: Callable[[Callable[[], object]], object], operations: RagOperations) -> None:
    """处理 RAG 知识库命令。"""
    subcommand, _, value = arg.partition(" ")
    subcommand = subcommand.strip()
    value = value.strip()

    if subcommand == "add":
        if not value:
            print("用法：/rag add <文件路径>\n")
            return
        run_cancellable(lambda: _rag_add(value, operations))
        return

    if subcommand == "list":
        _rag_list(operations)
        return

    if subcommand == "delete":
        if not value:
            print("用法：/rag delete <document_id>\n")
            return
        _rag_delete(value, operations)
        return

    if subcommand == "clear":
        run_cancellable(lambda: _rag_clear(operations))
        return

    if subcommand == "sync":
        run_cancellable(lambda: _rag_sync(operations))
        return

    if subcommand == "rebuild":
        run_cancellable(lambda: _rag_rebuild(operations))
        return

    print("RAG 命令：/rag add <文件路径>、/rag list、/rag delete <document_id>、/rag clear、/rag sync、/rag rebuild\n")


def _rag_add(path: str, operations: RagOperations) -> None:
    """导入知识库文档。"""
    path = path.strip().removeprefix("@").strip("\"'")
    try:
        result = operations.add_document(path)
    except KnowledgeBaseError as exc:
        print(f"导入失败：{exc}\n")
        return
    document = result["document"]
    status = "已更新" if result["status"] == "updated" else "已导入"
    if result["status"] == "unchanged":
        status = "内容未变化"
    print(f"{status}：{document['document_id']} | {document['title']} | {document['chunk_count']} 个片段\n")


def _rag_list(operations: RagOperations) -> None:
    """打印知识库文档列表。"""
    documents = operations.list_documents()
    if not documents:
        print("知识库暂无文档。\n")
        return

    print("知识库文档：")
    for item in documents:
        document_id = item.get("document_id", "未知 ID")
        title = item.get("title") or item.get("source") or document_id
        chunk_count = item.get("chunk_count", 0)
        path = item.get("path") or item.get("source") or ""
        print(f"- {document_id} | {title} | {chunk_count} 个片段 | {path}")
    print()


def _rag_delete(document_id: str, operations: RagOperations) -> None:
    """删除知识库文档。"""
    if operations.delete_document(document_id):
        print(f"已删除知识库文档：{document_id}\n")
    else:
        print(f"知识库文档不存在：{document_id}\n")


def _rag_clear(operations: RagOperations) -> None:
    """清空知识库。"""
    count = operations.clear_knowledge_base()
    print(f"已清空知识库，共删除 {count} 个文档。\n")


def _rag_sync(operations: RagOperations) -> None:
    """同步知识库文档。"""
    summary = operations.sync_knowledge_base()
    print(
        "知识库同步完成："
        f"检查 {summary['checked']} 个，"
        f"更新 {summary['updated']} 个，"
        f"未变化 {summary['unchanged']} 个，"
        f"缺失 {summary['missing']} 个，"
        f"失败 {summary['failed']} 个。\n"
    )


def _rag_rebuild(operations: RagOperations) -> None:
    """重建知识库索引。"""
    summary = operations.rebuild_knowledge_base()
    print(
        "知识库重建完成："
        f"检查 {summary['checked']} 个，"
        f"重建 {summary['rebuilt']} 个，"
        f"缺失 {summary['missing']} 个，"
        f"失败 {summary['failed']} 个。\n"
    )
