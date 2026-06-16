"""网页搜索工具。"""

from langchain_core.tools import tool
from langchain_core.tools import ToolException
from langchain_tavily import TavilySearch

from agent_app.config import TAVILY_API_KEY, WEB_SEARCH_MAX_RESULTS, WEB_SEARCH_SEARCH_DEPTH
from agent_app.tools.runtime import ToolMetadata


TOOL_METADATA = ToolMetadata(
    name="web_search",
    category="search",
    description="按关键词搜索外部网页，返回标题、链接和摘要。",
    timeout_seconds=10,
    max_retries=1,
    trigger_keywords=(
        "搜索",
        "查一下",
        "查询",
        "最新",
        "新闻",
        "search",
        "google",
        "bing",
        "联网",
        "实时",
        "当前",
        "today",
        "now",
        "current",
        "recent",
        "股票",
        "股市",
        "行情",
        "市场",
        "汇率",
        "价格",
        "走势",
        "金价",
        "黄金",
        "贵金属",
        "预测",
        "forecast",
        "price",
        "政策",
        "法规",
        "公告",
        "release",
    ),
)


def _format_search_results(results: list[dict]) -> str:
    """将搜索结果格式化为适合模型阅读的文本。"""
    if not results:
        return "未搜索到相关结果。"

    lines = []
    for index, result in enumerate(results[:WEB_SEARCH_MAX_RESULTS], start=1):
        title = str(result.get("title") or "无标题").strip()
        url = str(result.get("url") or "").strip()
        snippet = str(result.get("content") or result.get("snippet") or "").strip()

        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"链接: {url}")
        if snippet:
            lines.append(f"摘要: {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


def _create_tavily_search() -> TavilySearch:
    """创建 Tavily 搜索工具。"""
    return TavilySearch(
        max_results=WEB_SEARCH_MAX_RESULTS,
        search_depth=WEB_SEARCH_SEARCH_DEPTH,
    )


def _extract_results(payload) -> list[dict]:
    """从 Tavily 返回值中提取结果列表。"""
    if isinstance(payload, tuple) and len(payload) >= 2:
        return _extract_results(payload[1])
    if isinstance(payload, dict):
        results = payload.get("results") or []
        return results if isinstance(results, list) else []
    if isinstance(payload, list):
        return payload
    return []


@tool
def web_search(query: str) -> str:
    """当用户询问实时信息、新闻、网页资料或外部知识时，按关键词搜索外部网页。query 参数为搜索关键词。"""
    query = str(query or "").strip()
    if not query:
        return "缺少搜索关键词。请提供要搜索的内容。"
    if not TAVILY_API_KEY:
        return "网页搜索配置错误：缺少 TAVILY_API_KEY。请在 .env 中配置 Tavily Search API key。"

    tavily_search = _create_tavily_search()
    try:
        payload = tavily_search._run(query)
    except ToolException:
        return "未搜索到相关结果。"
    return _format_search_results(_extract_results(payload))
