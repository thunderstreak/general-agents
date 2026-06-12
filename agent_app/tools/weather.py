"""天气相关工具。"""

from urllib.parse import quote_plus

import requests
from langchain_core.tools import tool

from agent_app.tools.location import locate_city_by_ip
from agent_app.tools.runtime import ToolMetadata


TOOL_METADATA = ToolMetadata(
    name="get_weather",
    category="weather",
    description="查询指定城市的实时天气；未提供城市时自动使用 IP 定位城市。",
    timeout_seconds=10,
    max_retries=1,
    trigger_keywords=("天气", "气温", "下雨", "weather", "forecast"),
)


@tool
def get_weather(city: str = "") -> str:
    """查询指定城市的实时天气。city 参数为城市中文名；如果用户没有提供城市，传空字符串，将自动使用当前 IP 定位城市。"""
    if not city:
        city = locate_city_by_ip()
        if not city:
            return "天气查询失败：用户没有提供城市，且无法通过当前 IP 定位城市。请提供城市名后再查询。"

    url = f"https://wttr.in/{quote_plus(city)}?format=j1&lang=zh"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"天气查询失败：{exc}"
    except ValueError:
        return "天气查询失败：天气服务返回的数据格式无法解析。"

    current = data.get("current_condition", [{}])[0]
    today = data.get("weather", [{}])[0]
    area = data.get("nearest_area", [{}])[0]
    area_name = area.get("areaName", [{}])[0].get("value", city)
    region = area.get("region", [{}])[0].get("value", "")

    weather_desc = current.get("lang_zh", [{}])[0].get("value") or current.get("weatherDesc", [{}])[0].get("value", "未知")
    date = today.get("date", "今天")
    max_temp = today.get("maxtempC", "未知")
    min_temp = today.get("mintempC", "未知")

    return (
        f"{city}实时天气（数据源：wttr.in，观测地点：{area_name} {region}）：\n"
        f"- 日期：{date}\n"
        f"- 天气：{weather_desc}\n"
        f"- 当前温度：{current.get('temp_C', '未知')}°C\n"
        f"- 体感温度：{current.get('FeelsLikeC', '未知')}°C\n"
        f"- 今日最高/最低：{max_temp}°C / {min_temp}°C\n"
        f"- 湿度：{current.get('humidity', '未知')}%\n"
        f"- 风速：{current.get('windspeedKmph', '未知')} km/h\n"
        f"- 降水量：{current.get('precipMM', '未知')} mm\n"
        f"- 观测时间：{current.get('observation_time', '未知')} UTC"
    )
