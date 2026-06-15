"""模型和外部服务配置。"""

import os

from dotenv import load_dotenv


load_dotenv()


def _get_required_env(name: str) -> str:
    """读取必需环境变量，缺失时给出明确错误。"""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少必需环境变量：{name}。请参考 .env.example 配置。")
    return value


MODEL_NAME = os.getenv("MODEL_NAME")
BASE_URL = os.getenv("BASE_URL")
OPENAI_API_KEY = _get_required_env("OPENAI_API_KEY")

CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", MODEL_NAME)
TOOL_SELECTOR_MODEL_NAME = os.getenv("TOOL_SELECTOR_MODEL_NAME", MODEL_NAME)
VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME", MODEL_NAME)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME", "")
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
MODEL_MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "2"))
MAX_FILE_SIZE_MB = float(os.getenv("MAX_FILE_SIZE_MB", "10"))

MEMORY_FILE_PATH = os.getenv("MEMORY_FILE_PATH", ".agent_memory.json")
MEMORY_MAX_ITEMS = int(os.getenv("MEMORY_MAX_ITEMS", "50"))

ORCHESTRATOR_MAX_STEPS = int(os.getenv("ORCHESTRATOR_MAX_STEPS", "8"))

RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() in {"1", "true", "yes", "y"}
RAG_STORE_DIR = os.getenv("RAG_STORE_DIR", ".agent_knowledge")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", ".agent_knowledge/chroma")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "agent_knowledge")
RAG_EMBEDDING_PROVIDER = os.getenv("RAG_EMBEDDING_PROVIDER", "huggingface")
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
RAG_EMBEDDING_BASE_URL = os.getenv("RAG_EMBEDDING_BASE_URL", BASE_URL or "")
RAG_EMBEDDING_API_KEY = os.getenv("RAG_EMBEDDING_API_KEY", OPENAI_API_KEY)
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "800"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
RAG_CANDIDATE_K = int(os.getenv("RAG_CANDIDATE_K", str(max(RAG_TOP_K * 3, RAG_TOP_K))))
RAG_KEYWORD_WEIGHT = float(os.getenv("RAG_KEYWORD_WEIGHT", "0.2"))

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_SEARCH_DEPTH = os.getenv("WEB_SEARCH_SEARCH_DEPTH", "basic")

OUTPUT_DEBUG = os.getenv("OUTPUT_DEBUG", "false").lower() in {"1", "true", "yes", "y"}
CLI_STREAM = os.getenv("CLI_STREAM", "true").lower() in {"1", "true", "yes", "y"}
CLI_STREAM_PROGRESS = os.getenv("CLI_STREAM_PROGRESS", "true").lower() in {"1", "true", "yes", "y"}
CLI_INPUT_HISTORY_FILE = os.getenv("CLI_INPUT_HISTORY_FILE", ".agent_input_history")

SESSION_STORE_DIR = os.getenv("SESSION_STORE_DIR", ".agent_sessions")
SESSION_AUTO_SAVE = os.getenv("SESSION_AUTO_SAVE", "true").lower() in {"1", "true", "yes", "y"}
