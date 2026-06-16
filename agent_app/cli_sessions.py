"""CLI 会话命令兼容入口。"""

import sys

from agent_app.cli import sessions as _sessions

sys.modules[__name__] = _sessions
