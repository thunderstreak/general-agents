"""RAG 文档与片段 metadata。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_app.config import RAG_STORE_DIR


DOCUMENTS_FILE_NAME = "documents.json"
CHUNKS_FILE_NAME = "chunks.jsonl"
PDF_PAGE_PATTERN = re.compile(r"^## 第 (?P<page>\d+) 页$", re.MULTILINE)
XLSX_SHEET_PATTERN = re.compile(r"^## 工作表：(?P<sheet>.+)$", re.MULTILINE)


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


def load_documents(store_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """读取文档 metadata。"""
    path = documents_path(store_dir)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_documents = data.get("documents", []) if isinstance(data, dict) else data
    documents = {}
    for item in raw_documents:
        if isinstance(item, dict) and item.get("document_id"):
            documents[item["document_id"]] = item
    return documents


def save_documents(documents: dict[str, dict[str, Any]], store_dir: str | None = None) -> None:
    """保存文档 metadata。"""
    path = documents_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"documents": sorted(documents.values(), key=lambda item: item.get("updated_at", 0), reverse=True)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def documents_path(store_dir: str | None = None) -> Path:
    """获取文档 metadata 路径。"""
    return Path(store_dir or RAG_STORE_DIR) / DOCUMENTS_FILE_NAME


def chunks_path(store_dir: str | None = None) -> Path:
    """获取 chunk metadata 路径。"""
    return Path(store_dir or RAG_STORE_DIR) / CHUNKS_FILE_NAME


def load_chunk_records(store_dir: str | None = None) -> list[dict[str, Any]]:
    """读取 chunk metadata。"""
    path = chunks_path(store_dir)
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


def save_chunk_records(records: list[dict[str, Any]], store_dir: str | None = None) -> None:
    """保存 chunk metadata。"""
    path = chunks_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def replace_chunk_records(document_id: str, new_records: list[dict[str, Any]], store_dir: str | None = None) -> None:
    """替换单个文档的 chunk metadata。"""
    records = [item for item in load_chunk_records(store_dir) if item.get("document_id") != document_id]
    records.extend(new_records)
    save_chunk_records(records, store_dir)


def remove_chunk_records(document_id: str, store_dir: str | None = None) -> None:
    """删除单个文档的 chunk metadata。"""
    records = [item for item in load_chunk_records(store_dir) if item.get("document_id") != document_id]
    save_chunk_records(records, store_dir)


def document_id(path: Path) -> str:
    """根据绝对路径生成稳定 document id。"""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def content_hash(content: str) -> str:
    """生成文档内容 hash。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_id(document_id: str, content_hash: str, index: int) -> str:
    """生成稳定 chunk id。"""
    return f"{document_id}:{content_hash[:12]}:{index}"


def chunk_source_metadata(content: str, chunk: str) -> dict[str, Any]:
    """提取 chunk 对应的轻量来源 metadata。"""
    start = content.find(chunk)
    if start < 0:
        start = 0
    end = start + len(chunk)
    metadata: dict[str, Any] = {}
    page = nearest_marker_value(PDF_PAGE_PATTERN, content, end, "page")
    if page:
        metadata["page"] = page
    sheet = nearest_marker_value(XLSX_SHEET_PATTERN, content, end, "sheet")
    if sheet:
        metadata["sheet"] = sheet
    return metadata


def nearest_marker_value(pattern: re.Pattern, content: str, offset: int, group_name: str) -> str:
    """查找 offset 前最近的章节标记。"""
    value = ""
    for match in pattern.finditer(content):
        if match.start() > offset:
            break
        value = match.group(group_name).strip()
    return value
