"""RAG embedding 客户端。"""

from __future__ import annotations

from typing import Any

import requests


class OpenAICompatibleEmbeddings:
    """直接发送字符串的 OpenAI-compatible embedding 客户端。"""

    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 60.0):
        """初始化 embedding 客户端。"""
        self.model = model
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """生成文档向量。"""
        if not texts:
            return []
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量。"""
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        """调用 OpenAI-compatible embeddings API。"""
        if not self.base_url:
            raise RuntimeError("缺少 RAG_EMBEDDING_BASE_URL。")
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={"model": self.model, "input": inputs},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise RuntimeError("embedding 响应格式错误：data 不是列表。")
        sorted_data = sorted(data, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
        embeddings = []
        for item in sorted_data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise RuntimeError("embedding 响应格式错误：缺少 embedding。")
            embeddings.append([float(value) for value in embedding])
        return embeddings

    def _headers(self) -> dict[str, str]:
        """构造请求头。"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
