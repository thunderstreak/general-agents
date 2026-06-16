"""RAG 意图辅助判断。"""


def is_knowledge_list_query(text: str) -> bool:
    """判断是否为知识库文档清单查询。"""
    normalized = " ".join(str(text or "").split()).strip().lower()
    if not normalized:
        return False
    knowledge_keywords = ("知识库", "资料库", "文档库", "knowledge base")
    list_keywords = (
        "有哪些",
        "有什么",
        "列表",
        "列出",
        "已导入",
        "已收录",
        "收录了",
        "导入了",
        "文档",
        "文件",
        "资料",
        "list",
    )
    return any(keyword in normalized for keyword in knowledge_keywords) and any(keyword in normalized for keyword in list_keywords)
