"""CLI 取消控制兼容入口。"""

import sys

from agent_app.cli import cancel as _cancel

sys.modules[__name__] = _cancel
