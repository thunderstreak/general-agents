"""URL 内容抓取工具。"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
from langchain_core.tools import tool

from agent_app.tools.runtime import ToolMetadata


MAX_CONTENT_BYTES = 200 * 1024
TEXT_PREVIEW_CHARS = 12000
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}
BLOCKED_IPS = {
    ipaddress.ip_address("0.0.0.0"),
    ipaddress.ip_address("169.254.169.254"),
}
TOOL_METADATA = ToolMetadata(
    name="fetch_url",
    category="fetch",
    description="抓取指定 HTTP/HTTPS URL 的网页正文内容。",
    timeout_seconds=10,
    max_retries=1,
    trigger_keywords=(
        "http://",
        "https://",
        "打开链接",
        "抓取网页",
        "读取网页",
        "总结这个链接",
        "分析这个链接",
        "fetch url",
        "open url",
        "read url",
        "summarize url",
    ),
)


class _ReadableHTMLParser(HTMLParser):
    """从 HTML 中提取标题和可读文本。"""

    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_stack: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_stack.append(tag)
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str):
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_stack:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return _normalize_text(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self.text_parts))


@tool
def fetch_url(url: str) -> str:
    """抓取指定 HTTP/HTTPS URL 的文本内容。url 参数为完整网页链接。"""
    try:
        _validate_public_url(url)
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                )
            },
            timeout=10,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()
        _validate_public_url(response.url)
        content = _read_limited_content(response)
    except ValueError as exc:
        return f"URL 抓取失败：{exc}"
    except requests.RequestException as exc:
        return f"URL 抓取失败：{exc}"

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if _is_html(content_type, response.url):
        return _format_html_result(response.url, content_type, content)
    if _is_text(content_type):
        return _format_text_result(response.url, content_type, content)
    return f"URL 抓取完成，但该内容类型不支持正文抓取：{content_type or 'unknown'}\n最终 URL：{response.url}"


def _validate_public_url(url: str) -> None:
    """校验 URL 协议和目标地址，避免访问本机或内网。"""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http:// 或 https:// URL。")
    if not parsed.hostname:
        raise ValueError("URL 缺少 hostname。")
    if _is_blocked_host(parsed.hostname):
        raise ValueError("禁止访问 localhost、内网地址或 metadata 地址。")


def _is_blocked_host(hostname: str) -> bool:
    """判断主机名是否指向本机、内网或特殊地址。"""
    host = hostname.strip().lower().rstrip(".")
    if host in BLOCKED_HOSTS:
        return True

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue

    return any(_is_blocked_ip(address) for address in addresses)


def _is_blocked_ip(address) -> bool:
    """判断 IP 是否属于禁止访问范围。"""
    return (
        address in BLOCKED_IPS
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _read_limited_content(response: requests.Response) -> bytes:
    """限制读取响应体大小。"""
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        remaining = MAX_CONTENT_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += len(chunk[:remaining])
    return b"".join(chunks)


def _is_html(content_type: str, url: str) -> bool:
    """判断内容是否为 HTML。"""
    return content_type in {"text/html", "application/xhtml+xml"} or urlparse(url).path.lower().endswith((".html", ".htm"))


def _is_text(content_type: str) -> bool:
    """判断内容是否可作为文本返回。"""
    return content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/javascript",
    }


def _format_html_result(url: str, content_type: str, content: bytes) -> str:
    """格式化 HTML 抓取结果。"""
    html = _decode_content(content)
    parser = _ReadableHTMLParser()
    parser.feed(html)
    parser.close()
    text = _truncate(parser.text or "未提取到正文文本。")
    title = parser.title or "无标题"
    return f"URL 抓取结果\n最终 URL：{url}\n内容类型：{content_type or 'text/html'}\n标题：{title}\n正文：\n{text}"


def _format_text_result(url: str, content_type: str, content: bytes) -> str:
    """格式化文本抓取结果。"""
    text = _decode_content(content)
    if content_type == "application/json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            pass
    return f"URL 抓取结果\n最终 URL：{url}\n内容类型：{content_type or 'text/plain'}\n正文：\n{_truncate(_normalize_text(text))}"


def _decode_content(content: bytes) -> str:
    """解码响应内容。"""
    return content.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    """压缩空白并反转义 HTML 实体。"""
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", unescape(text))).strip()


def _truncate(text: str) -> str:
    """截断过长文本。"""
    if len(text) <= TEXT_PREVIEW_CHARS:
        return text
    return text[:TEXT_PREVIEW_CHARS].rstrip() + "\n...[内容过长，已截断]"
