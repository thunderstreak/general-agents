"""工具注册中心。"""

from agent_app.tools.location import get_location
from agent_app.tools.weather import get_weather
from agent_app.tools.web_search import web_search


tools = [get_location, get_weather, web_search]
tools_by_name = {tool.name: tool for tool in tools}
