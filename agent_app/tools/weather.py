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
    trigger_keywords=("天气", "气温", "下雨", "weather"),
)
FORECAST_TOOL_METADATA = ToolMetadata(
    name="get_weather_forecast",
    category="weather",
    description="查询指定城市未来多天天气预报；支持 days 参数，默认 7 天，未提供城市时自动使用 IP 定位城市。",
    timeout_seconds=10,
    max_retries=1,
    trigger_keywords=("未来", "预报", "明天", "后天", "三天", "3天", "一周", "forecast"),
)


@tool
def get_weather(city: str = "") -> str:
    """查询指定城市的实时天气。city 参数为城市中文名；如果用户没有提供城市，传空字符串，将自动使用当前 IP 定位城市。"""
    data, city, error = _fetch_weather_data(city)
    if error:
        return error

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


@tool
def get_weather_forecast(city: str = "", days: int | str = 7) -> str:
    """查询指定城市未来多天天气预报。city 为城市中文名；days 为天数，默认 7 天，最多 7 天；city 为空时自动使用当前 IP 定位城市。"""
    data, city, error = _fetch_weather_data(city)
    if error:
        return error

    days = _normalize_days(days)
    open_meteo_result = _format_open_meteo_forecast(data, city, days)
    if open_meteo_result:
        return open_meteo_result

    weather_items = data.get("weather", [])
    if not weather_items:
        return f"{city}天气预报查询失败：天气服务未返回预报数据。"

    area = data.get("nearest_area", [{}])[0]
    area_name = area.get("areaName", [{}])[0].get("value", city)
    region = area.get("region", [{}])[0].get("value", "")
    available_days = min(days, len(weather_items))
    lines = [f"{city}未来 {available_days} 天天气预报（数据源：wttr.in，观测地点：{area_name} {region}）："]
    if available_days < days:
        lines.append(f"说明：当前数据源只返回 {available_days} 天预报，少于请求的 {days} 天。")

    for item in weather_items[:days]:
        hourly_items = item.get("hourly", [])
        noon = _pick_noon_weather(hourly_items)
        desc = _weather_description(noon) if noon else "未知"
        chance_of_rain = noon.get("chanceofrain", "未知") if noon else "未知"
        wind_speed = noon.get("windspeedKmph", "未知") if noon else "未知"
        lines.extend(
            [
                f"- 日期：{item.get('date', '未知')}",
                f"  - 天气：{desc}",
                f"  - 最高/最低：{item.get('maxtempC', '未知')}°C / {item.get('mintempC', '未知')}°C",
                f"  - 降雨概率：{chance_of_rain}%",
                f"  - 风速：{wind_speed} km/h",
            ]
        )

    return "\n".join(lines)


def _format_open_meteo_forecast(wttr_data: dict, city: str, days: int) -> str:
    """使用 Open-Meteo 按经纬度获取 7 天内预报。"""
    area = wttr_data.get("nearest_area", [{}])[0]
    latitude = area.get("latitude")
    longitude = area.get("longitude")
    if not latitude or not longitude:
        return ""

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
        "forecast_days": days,
        "timezone": "auto",
    }
    try:
        response = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return ""

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return ""

    area_name = area.get("areaName", [{}])[0].get("value", city)
    region = area.get("region", [{}])[0].get("value", "")
    lines = [f"{city}未来 {len(dates)} 天天气预报（数据源：Open-Meteo，定位参考：{area_name} {region}）："]
    for index, date in enumerate(dates):
        lines.extend(
            [
                f"- 日期：{date}",
                f"  - 天气：{_weather_code_text(_daily_value(daily, 'weather_code', index))}",
                f"  - 最高/最低：{_daily_value(daily, 'temperature_2m_max', index)}°C / {_daily_value(daily, 'temperature_2m_min', index)}°C",
                f"  - 最高降雨概率：{_daily_value(daily, 'precipitation_probability_max', index)}%",
                f"  - 最大风速：{_daily_value(daily, 'wind_speed_10m_max', index)} km/h",
            ]
        )
    return "\n".join(lines)


def _fetch_weather_data(city: str) -> tuple[dict, str, str]:
    """请求天气数据。"""
    if not city:
        city = locate_city_by_ip()
        if not city:
            return {}, "", "天气查询失败：用户没有提供城市，且无法通过当前 IP 定位城市。请提供城市名后再查询。"

    url = f"https://wttr.in/{quote_plus(city)}?format=j1&lang=zh"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json(), city, ""
    except requests.RequestException as exc:
        return {}, city, f"天气查询失败：{exc}"
    except ValueError:
        return {}, city, "天气查询失败：天气服务返回的数据格式无法解析。"


def _normalize_days(days: int | str) -> int:
    """规范化预报天数。"""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return 7
    return max(1, min(value, 7))


def _pick_noon_weather(hourly_items: list[dict]) -> dict:
    """优先取中午时段天气，缺失时取第一条。"""
    if not hourly_items:
        return {}
    for item in hourly_items:
        if str(item.get("time")) == "1200":
            return item
    return hourly_items[0]


def _weather_description(item: dict) -> str:
    """读取中文天气描述。"""
    return item.get("lang_zh", [{}])[0].get("value") or item.get("weatherDesc", [{}])[0].get("value", "未知")


def _daily_value(daily: dict, key: str, index: int) -> str:
    """读取 Open-Meteo daily 数组值。"""
    values = daily.get(key, [])
    if not isinstance(values, list) or index >= len(values):
        return "未知"
    value = values[index]
    return "未知" if value is None else str(value)


def _weather_code_text(value: str) -> str:
    """转换 Open-Meteo 天气代码为中文描述。"""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "未知"

    mapping = {
        0: "晴",
        1: "大部晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "大毛毛雨",
        56: "冻毛毛雨",
        57: "强冻毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "强冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        85: "小阵雪",
        86: "强阵雪",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }
    return mapping.get(code, f"天气代码 {code}")
