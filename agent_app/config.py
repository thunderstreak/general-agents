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


MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.5")
BASE_URL = os.getenv("BASE_URL", "https://tokendocker.com/v1")
OPENAI_API_KEY = _get_required_env("OPENAI_API_KEY")
