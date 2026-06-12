"""URL Fetch 工具测试。"""

import unittest
from unittest.mock import patch

import requests

from agent_app.tools import tool_metadata_by_name, tools_by_name
from agent_app.tools.url_fetch import fetch_url


class FakeResponse:
    """模拟 requests.Response。"""

    def __init__(self, url="https://example.com", content_type="text/html", body=b"", status_error=None):
        self.url = url
        self.headers = {"Content-Type": content_type}
        self._body = body
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def iter_content(self, chunk_size=8192):
        for index in range(0, len(self._body), chunk_size):
            yield self._body[index : index + chunk_size]


class UrlFetchToolTest(unittest.TestCase):
    """URL Fetch 工具行为测试。"""

    def test_fetch_url_rejects_non_http_protocol(self):
        """非 HTTP 协议会被拒绝。"""
        result = fetch_url.invoke({"url": "ftp://example.com/file.txt"})

        self.assertIn("仅支持 http:// 或 https://", result)

    def test_fetch_url_rejects_localhost(self):
        """localhost 会被拒绝。"""
        result = fetch_url.invoke({"url": "http://127.0.0.1:8000"})

        self.assertIn("禁止访问", result)

    def test_fetch_url_reads_html_title_and_text(self):
        """HTML 响应会提取标题和正文。"""
        body = b"""
        <html>
          <head><title>Example Title</title><script>ignore()</script></head>
          <body><h1>Hello</h1><p>Readable content.</p><style>.x{}</style></body>
        </html>
        """

        with patch("agent_app.tools.url_fetch.requests.get", return_value=FakeResponse(body=body)):
            result = fetch_url.invoke({"url": "https://example.com/page"})

        self.assertIn("标题：Example Title", result)
        self.assertIn("Hello", result)
        self.assertIn("Readable content.", result)
        self.assertNotIn("ignore()", result)

    def test_fetch_url_reads_json_text(self):
        """JSON 响应会作为文本返回。"""
        body = b'{"name":"LangGraph","ok":true}'

        with patch(
            "agent_app.tools.url_fetch.requests.get",
            return_value=FakeResponse(content_type="application/json", body=body),
        ):
            result = fetch_url.invoke({"url": "https://example.com/data.json"})

        self.assertIn('"name": "LangGraph"', result)
        self.assertIn('"ok": true', result)

    def test_fetch_url_rejects_binary_content(self):
        """图片等二进制内容不抓取正文。"""
        with patch(
            "agent_app.tools.url_fetch.requests.get",
            return_value=FakeResponse(content_type="image/png", body=b"PNG"),
        ):
            result = fetch_url.invoke({"url": "https://example.com/image.png"})

        self.assertIn("不支持正文抓取", result)

    def test_fetch_url_handles_request_error(self):
        """请求异常返回统一错误文本。"""
        with patch("agent_app.tools.url_fetch.requests.get", side_effect=requests.RequestException("timeout")):
            result = fetch_url.invoke({"url": "https://example.com"})

        self.assertIn("URL 抓取失败", result)
        self.assertIn("timeout", result)

    def test_fetch_url_is_registered(self):
        """工具注册表包含 fetch_url。"""
        self.assertIn("fetch_url", tools_by_name)
        self.assertIn("fetch_url", tool_metadata_by_name)
        self.assertEqual(tool_metadata_by_name["fetch_url"].category, "fetch")


if __name__ == "__main__":
    unittest.main()
