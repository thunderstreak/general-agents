"""搜索结果 HTML 解析器。"""

from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse


class DuckDuckGoHTMLParser(HTMLParser):
    """解析 DuckDuckGo HTML 搜索结果。"""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._capture = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")

        if tag == "a" and "result__a" in class_name:
            self._current = {"title": "", "url": self._clean_url(attrs_dict.get("href", "")), "snippet": ""}
            self._capture = "title"
            self._text_parts = []
        elif self._current and tag == "a" and "result__snippet" in class_name:
            self._capture = "snippet"
            self._text_parts = []

    def handle_data(self, data):
        if self._capture:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    def handle_endtag(self, tag):
        if not self._current or not self._capture:
            return

        if tag == "a" and self._capture == "title":
            self._current["title"] = " ".join(self._text_parts)
            self._capture = None
            self._text_parts = []
        elif tag == "a" and self._capture == "snippet":
            self._current["snippet"] = " ".join(self._text_parts)
            self.results.append(self._current)
            self._current = None
            self._capture = None
            self._text_parts = []

    @staticmethod
    def _clean_url(url: str) -> str:
        """提取 DuckDuckGo 跳转链接中的真实目标 URL。"""
        if not url:
            return ""

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "uddg" in params and params["uddg"]:
            return unquote(params["uddg"][0])
        return url


class BingHTMLParser(HTMLParser):
    """解析 Bing HTML 搜索结果，作为 DuckDuckGo 不可用时的备用方案。"""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._capture = None
        self._text_parts = []
        self._in_result = False
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")

        if tag == "li" and "b_algo" in class_name:
            self._finish_current()
            self._current = {"title": "", "url": "", "snippet": ""}
            self._in_result = True
        elif self._in_result and tag == "h2":
            self._in_h2 = True
        elif self._in_result and self._in_h2 and tag == "a":
            self._current["url"] = attrs_dict.get("href", "")
            self._capture = "title"
            self._text_parts = []
        elif self._in_result and tag == "p" and self._current and not self._current["snippet"]:
            self._capture = "snippet"
            self._text_parts = []

    def handle_data(self, data):
        if self._capture:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    def handle_endtag(self, tag):
        if self._capture == "title" and tag == "a":
            self._current["title"] = " ".join(self._text_parts)
            self._capture = None
            self._text_parts = []
        elif self._capture == "snippet" and tag == "p":
            self._current["snippet"] = " ".join(self._text_parts)
            self._capture = None
            self._text_parts = []
        elif self._in_h2 and tag == "h2":
            self._in_h2 = False
        elif self._in_result and tag == "li":
            self._finish_current()

    def close(self):
        super().close()
        self._finish_current()

    def _finish_current(self):
        if self._current and self._current["title"] and self._current["url"]:
            self.results.append(self._current)
        self._current = None
        self._capture = None
        self._text_parts = []
        self._in_result = False
        self._in_h2 = False
