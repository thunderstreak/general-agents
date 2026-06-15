"""统一 LLM 管理。"""

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agent_app.config import (
    BASE_URL,
    CHAT_MODEL_NAME,
    EMBEDDING_MODEL_NAME,
    FALLBACK_MODEL_NAME,
    MODEL_MAX_RETRIES,
    MODEL_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    TOOL_SELECTOR_MODEL_NAME,
    VISION_MODEL_NAME,
)


@lru_cache(maxsize=32)
def _get_chat_model(model_name: str, temperature: float | None = None) -> ChatOpenAI:
    """创建 ChatOpenAI 模型实例。"""
    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature

    return ChatOpenAI(
        model=model_name,
        base_url=BASE_URL,
        openai_api_key=OPENAI_API_KEY,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
        **kwargs,
    )


def get_chat_model() -> ChatOpenAI:
    """获取主聊天模型。"""
    return _get_chat_model(CHAT_MODEL_NAME)


def get_tool_selector_model() -> ChatOpenAI:
    """获取工具选择模型。"""
    return _get_chat_model(TOOL_SELECTOR_MODEL_NAME, temperature=0).with_config(tags=["nostream"])


def get_vision_model() -> ChatOpenAI:
    """获取多模态视觉模型。"""
    return _get_chat_model(VISION_MODEL_NAME)


def get_fallback_model() -> ChatOpenAI | None:
    """获取备用聊天模型。"""
    if not FALLBACK_MODEL_NAME:
        return None
    return _get_chat_model(FALLBACK_MODEL_NAME)


def invoke_with_fallback(messages, tags: list[str] | None = None):
    """调用主聊天模型；失败时尝试 fallback 模型。"""
    model = get_chat_model()
    if tags:
        model = model.with_config(tags=tags)
    try:
        return model.invoke(messages)
    except Exception:
        fallback_model = get_fallback_model()
        if fallback_model is None:
            raise
        if tags:
            fallback_model = fallback_model.with_config(tags=tags)
        return fallback_model.invoke(messages)


@lru_cache(maxsize=4)
def get_embedding_model() -> OpenAIEmbeddings:
    """获取 embedding 模型，为后续 RAG 预留。"""
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL_NAME,
        base_url=BASE_URL,
        openai_api_key=OPENAI_API_KEY,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
