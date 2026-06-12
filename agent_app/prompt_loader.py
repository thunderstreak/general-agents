"""Prompt 文件加载工具。"""

from functools import lru_cache
from pathlib import Path


PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """从 `agent_app/prompts` 目录读取 prompt 内容。"""
    prompt_path = PROMPT_DIR / name
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt 文件不存在：{prompt_path}")

    return prompt_path.read_text(encoding="utf-8").strip()
