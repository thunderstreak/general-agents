"""CLI 流式输出兼容入口。"""

import sys

from agent_app.cli import stream as _stream

sys.modules[__name__] = _stream
