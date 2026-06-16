"""CLI RAG 命令兼容入口。"""

import sys

from agent_app.cli import rag as _rag

sys.modules[__name__] = _rag
