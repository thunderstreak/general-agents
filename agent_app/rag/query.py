"""RAG 查询规范化与重排。"""

from __future__ import annotations

import re
from typing import Any

from agent_app.config import RAG_KEYWORD_WEIGHT


def normalize_query(query: str) -> str:
    """规范化 RAG 查询文本。"""
    text = str(query or "")
    for prefix in ("根据知识库", "根据文档", "根据资料", "从知识库", "检索", "查询知识库"):
        text = text.replace(prefix, " ")
    return " ".join(text.split())


def rerank_results(query: str, results: list[dict[str, Any]], keyword_weight: float | None = None) -> list[dict[str, Any]]:
    """结合向量分数和关键词命中重排结果。"""
    weight = RAG_KEYWORD_WEIGHT if keyword_weight is None else keyword_weight
    reranked = []
    for item in results:
        vector_score = float(item.get("vector_score", item.get("score", 0.0)) or 0.0)
        keyword_score = float(item.get("keyword_score", keyword_score_for(query, item, item.get("content", ""))) or 0.0)
        combined_score = vector_score + keyword_score * weight
        updated = dict(item)
        updated["keyword_score"] = round(keyword_score, 4)
        updated["score"] = round(combined_score, 4)
        reranked.append(updated)
    return sorted(reranked, key=lambda item: item.get("score", 0.0), reverse=True)


def keyword_score_for(query: str, metadata: dict[str, Any], content: str) -> float:
    """计算关键词命中分。"""
    terms = query_terms(query)
    if not terms:
        return 0.0
    haystack = f"{metadata.get('title', '')} {metadata.get('source', '')} {content}".lower()
    hits = sum(1 for term in terms if term.lower() in haystack)
    return hits / len(terms)


def query_terms(query: str) -> list[str]:
    """提取查询关键词。"""
    text = normalize_query(query)
    raw_terms = re.findall(r"[\w\u4e00-\u9fff]+", text)
    stopwords = {"根据", "知识库", "文档", "资料", "回答", "什么", "一下", "这个", "关于", "请", "帮我"}
    terms = [term for term in raw_terms if len(term) > 1 and term not in stopwords]
    return list(dict.fromkeys(terms))
