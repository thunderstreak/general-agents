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

MEMORY_FILE_PATH = os.getenv("MEMORY_FILE_PATH", ".agent_memory.json")
MEMORY_MAX_ITEMS = int(os.getenv("MEMORY_MAX_ITEMS", "50"))

ORCHESTRATOR_MAX_STEPS = int(os.getenv("ORCHESTRATOR_MAX_STEPS", "8"))

OUTPUT_DEBUG = os.getenv("OUTPUT_DEBUG", "false").lower() in {"1", "true", "yes", "y"}
CLI_STREAM = os.getenv("CLI_STREAM", "true").lower() in {"1", "true", "yes", "y"}
CLI_STREAM_PROGRESS = os.getenv("CLI_STREAM_PROGRESS", "true").lower() in {"1", "true", "yes", "y"}
CLI_INPUT_HISTORY_FILE = os.getenv("CLI_INPUT_HISTORY_FILE", ".agent_input_history")

SESSION_STORE_DIR = os.getenv("SESSION_STORE_DIR", ".agent_sessions")
SESSION_AUTO_SAVE = os.getenv("SESSION_AUTO_SAVE", "true").lower() in {"1", "true", "yes", "y"}
