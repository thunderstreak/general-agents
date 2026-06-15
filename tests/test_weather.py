"""天气工具测试。"""

import unittest
from unittest.mock import patch

from agent_app.tools import tool_metadata_by_name, tools_by_name
from agent_app.tools.weather import get_weather_forecast


class FakeResponse:
    """模拟天气接口响应。"""

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        """模拟状态码检查。"""

    def json(self):
        """返回 JSON 数据。"""
        return self.payload


class WeatherToolTest(unittest.TestCase):
    """天气工具行为测试。"""

    def test_weather_forecast_is_registered(self):
        """天气预报工具已注册到工具中心。"""
        self.assertIn("get_weather_forecast", tools_by_name)
        self.assertIn("get_weather_forecast", tool_metadata_by_name)

    def test_get_weather_forecast_formats_three_days(self):
        """天气预报工具会格式化多日预报。"""
        payload = {
            "nearest_area": [
                {
                    "areaName": [{"value": "Changsha"}],
                    "region": [{"value": "Hunan"}],
                    "latitude": "28.2",
                    "longitude": "112.967",
                }
            ],
            "weather": [
                _weather_day("2026-06-15", "多云", "31", "21", "20", "4"),
                _weather_day("2026-06-16", "小雨", "29", "22", "70", "8"),
                _weather_day("2026-06-17", "晴", "33", "24", "10", "6"),
            ],
        }

        with patch(
            "agent_app.tools.weather.requests.get",
            side_effect=[FakeResponse(payload), FakeResponse(_open_meteo_payload(3))],
        ):
            result = get_weather_forecast.invoke({"city": "长沙", "days": 3})

        self.assertIn("长沙未来 3 天天气预报", result)
        self.assertIn("数据源：Open-Meteo", result)
        self.assertIn("日期：2026-06-15", result)
        self.assertIn("日期：2026-06-17", result)
        self.assertIn("最高降雨概率：30%", result)

    def test_get_weather_forecast_formats_seven_days(self):
        """天气预报工具支持 7 天预报。"""
        payload = {
            "nearest_area": [{"areaName": [{"value": "Changsha"}], "region": [{"value": "Hunan"}], "latitude": "28.2", "longitude": "112.967"}],
            "weather": [_weather_day("2026-06-15", "多云", "31", "21", "20", "4")],
        }

        with patch(
            "agent_app.tools.weather.requests.get",
            side_effect=[FakeResponse(payload), FakeResponse(_open_meteo_payload(7))],
        ):
            result = get_weather_forecast.invoke({"city": "长沙", "days": 7})

        self.assertIn("长沙未来 7 天天气预报", result)
        self.assertIn("日期：2026-06-21", result)

    def test_get_weather_forecast_normalizes_days(self):
        """预报天数会被限制在可控范围内。"""
        payload = {
            "nearest_area": [{"areaName": [{"value": "Changsha"}], "region": [{"value": "Hunan"}], "latitude": "28.2", "longitude": "112.967"}],
            "weather": [_weather_day("2026-06-15", "多云", "31", "21", "20", "4")],
        }

        with patch("agent_app.tools.weather.requests.get", side_effect=[FakeResponse(payload), FakeResponse(_open_meteo_payload(7))]):
            result = get_weather_forecast.invoke({"city": "长沙", "days": "invalid"})

        self.assertIn("长沙未来 7 天天气预报", result)

    def test_get_weather_forecast_falls_back_to_wttr_when_open_meteo_fails(self):
        """Open-Meteo 失败时回退 wttr.in，并说明可用天数不足。"""
        payload = {
            "nearest_area": [{"areaName": [{"value": "Changsha"}], "region": [{"value": "Hunan"}], "latitude": "28.2", "longitude": "112.967"}],
            "weather": [
                _weather_day("2026-06-15", "多云", "31", "21", "20", "4"),
                _weather_day("2026-06-16", "小雨", "29", "22", "70", "8"),
                _weather_day("2026-06-17", "晴", "33", "24", "10", "6"),
            ],
        }

        with patch("agent_app.tools.weather.requests.get", side_effect=[FakeResponse(payload), ValueError("bad json")]):
            result = get_weather_forecast.invoke({"city": "长沙", "days": 7})

        self.assertIn("长沙未来 3 天天气预报", result)
        self.assertIn("当前数据源只返回 3 天预报，少于请求的 7 天", result)


def _weather_day(date: str, desc: str, max_temp: str, min_temp: str, rain: str, wind: str) -> dict:
    """构造 wttr.in 单日预报结构。"""
    return {
        "date": date,
        "maxtempC": max_temp,
        "mintempC": min_temp,
        "hourly": [
            {
                "time": "1200",
                "lang_zh": [{"value": desc}],
                "chanceofrain": rain,
                "windspeedKmph": wind,
            }
        ],
    }


def _open_meteo_payload(days: int) -> dict:
    """构造 Open-Meteo daily 预报结构。"""
    dates = [f"2026-06-{day:02d}" for day in range(15, 15 + days)]
    return {
        "daily": {
            "time": dates,
            "weather_code": [0 if index % 2 == 0 else 61 for index in range(days)],
            "temperature_2m_max": [30 + index for index in range(days)],
            "temperature_2m_min": [20 + index for index in range(days)],
            "precipitation_probability_max": [10 * (index + 1) for index in range(days)],
            "wind_speed_10m_max": [4 + index for index in range(days)],
        }
    }


if __name__ == "__main__":
    unittest.main()
