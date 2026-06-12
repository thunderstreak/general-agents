"""网页搜索工具。"""

from urllib.parse import quote_plus

import requests
from langchain_core.tools import tool

from agent_app.tools.parsers import BingHTMLParser, DuckDuckGoHTMLParser


def _format_search_results(results: list[dict[str, str]]) -> str:
    """将搜索结果格式化为适合模型阅读的文本。"""
    if not results:
        return "未搜索到相关结果。"

    lines = []
    for index, result in enumerate(results[:3], start=1):
        lines.append(f"{index}. {result['title']}")
        lines.append(f"链接: {result['url']}")
        if result["snippet"]:
            lines.append(f"摘要: {result['snippet']}")
        lines.append("")

    return "\n".join(lines).strip()


@tool
def web_search(query: str) -> str:
    """当用户询问实时信息、新闻、网页资料或外部知识时，按关键词搜索外部网页。query 参数为搜索关键词。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    }
    search_sources = [
        (f"https://duckduckgo.com/html/?q={quote_plus(query)}", DuckDuckGoHTMLParser),
        (f"https://www.bing.com/search?q={quote_plus(query)}", BingHTMLParser),
    ]
    errors = []

    for search_url, parser_class in search_sources:
        try:
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            errors.append(f"{search_url}: {exc}")
            continue

        parser = parser_class()
        parser.feed(response.text)
        parser.close()
        if parser.results:
            return _format_search_results(parser.results)

        errors.append(f"{search_url}: 未解析到搜索结果")

    return "网页搜索失败：" + "；".join(errors)
