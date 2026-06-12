"""工具注册中心。"""

from agent_app.tools.location import TOOL_METADATA as LOCATION_METADATA, get_location
from agent_app.tools.url_fetch import TOOL_METADATA as URL_FETCH_METADATA, fetch_url
from agent_app.tools.weather import TOOL_METADATA as WEATHER_METADATA, get_weather
from agent_app.tools.web_search import TOOL_METADATA as WEB_SEARCH_METADATA, web_search


tools = [get_location, get_weather, web_search, fetch_url]
tools_by_name = {tool.name: tool for tool in tools}
tool_metadata = [LOCATION_METADATA, WEATHER_METADATA, WEB_SEARCH_METADATA, URL_FETCH_METADATA]
tool_metadata_by_name = {metadata.name: metadata for metadata in tool_metadata}


def candidate_tool_names_for_text(text: str) -> list[str]:
    """根据本地触发词筛选候选工具名，用于减少绑定给模型的工具集合。"""
    normalized = _normalize_tool_text(text)
    if not normalized:
        return []

    candidates = []
    for metadata in tool_metadata:
        if any(str(keyword).lower() in normalized for keyword in metadata.trigger_keywords):
            candidates.append(metadata.name)
    return candidates


def candidate_tools_for_text(text: str):
    """根据用户输入返回候选工具；没有命中时回退到全部工具。"""
    candidate_names = candidate_tool_names_for_text(text)
    if not candidate_names:
        return tools
    return [tools_by_name[name] for name in candidate_names if name in tools_by_name]


def _normalize_tool_text(text: str) -> str:
    """标准化工具触发判断文本。"""
    return str(text or "").strip().lower()
