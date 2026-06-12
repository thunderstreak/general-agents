"""工具注册中心。"""

from agent_app.tools.location import get_location
from agent_app.tools.runtime import ToolMetadata
from agent_app.tools.weather import get_weather
from agent_app.tools.web_search import web_search


tools = [get_location, get_weather, web_search]
tools_by_name = {tool.name: tool for tool in tools}
tool_metadata = [
    ToolMetadata(
        name="get_location",
        category="location",
        description="通过当前公网 IP 查询大致位置。",
        timeout_seconds=10,
        max_retries=1,
    ),
    ToolMetadata(
        name="get_weather",
        category="weather",
        description="查询指定城市的实时天气；未提供城市时自动使用 IP 定位城市。",
        timeout_seconds=10,
        max_retries=1,
    ),
    ToolMetadata(
        name="web_search",
        category="search",
        description="按关键词搜索外部网页，返回标题、链接和摘要。",
        timeout_seconds=10,
        max_retries=1,
    ),
]
tool_metadata_by_name = {metadata.name: metadata for metadata in tool_metadata}
