"""位置相关工具。"""

import requests
from langchain_core.tools import tool

from agent_app.tools.runtime import ToolMetadata


TOOL_METADATA = ToolMetadata(
    name="get_location",
    category="location",
    description="通过当前公网 IP 查询大致位置。",
    timeout_seconds=10,
    max_retries=1,
    trigger_keywords=("我在哪", "当前位置", "定位", "location", "ip"),
)

LOCATION_URLS = (
    "https://ip-api.com/json/?lang=zh-CN",
    "http://ip-api.com/json/?lang=zh-CN",
)


@tool
def get_location() -> str:
    """通过当前公网 IP 查询大致位置。"""
    data, error = _fetch_location_data()
    if error:
        return f"位置查询失败：{error}"

    if data.get("status") != "success":
        return f"位置查询失败：{data.get('message', '未知错误')}"

    country = data.get("country", "")
    region = data.get("regionName", "")
    city = data.get("city", "")
    lat = data.get("lat", "未知")
    lon = data.get("lon", "未知")
    isp = data.get("isp", "未知")
    query_ip = data.get("query", "未知")

    return (
        "当前大致位置（基于公网 IP，可能与真实 GPS 位置有偏差）：\n"
        f"- 国家/地区：{country}\n"
        f"- 省份：{region}\n"
        f"- 城市：{city}\n"
        f"- 经纬度：{lat}, {lon}\n"
        f"- IP：{query_ip}\n"
        f"- 网络运营商：{isp}"
    )


def locate_city_by_ip() -> str:
    """通过公网 IP 获取城市名，失败时返回空字符串。"""
    data, error = _fetch_location_data()
    if error:
        return ""

    if data.get("status") != "success":
        return ""

    return data.get("city", "")


def _fetch_location_data() -> tuple[dict, str]:
    """请求公网 IP 定位服务，优先 HTTPS 并集中处理降级。"""
    last_error = ""
    for url in LOCATION_URLS:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json(), ""
        except requests.RequestException as exc:
            last_error = str(exc)
        except ValueError:
            return {}, "定位服务返回的数据格式无法解析。"
    return {}, last_error or "定位服务请求失败。"
