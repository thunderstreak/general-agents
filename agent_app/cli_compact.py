"""CLI 上下文压缩兼容入口。"""

import sys

from agent_app.cli import compact as _compact

sys.modules[__name__] = _compact
