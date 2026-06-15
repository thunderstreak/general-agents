"""位置工具测试。"""

import unittest
from unittest.mock import patch

import requests

from agent_app.tools import location


class FakeResponse:
    """模拟 requests 响应。"""

    def __init__(self, payload=None, error=None, json_error=None):
        self.payload = payload or {}
        self.error = error
        self.json_error = json_error

    def raise_for_status(self):
        """模拟状态码检查。"""
        if self.error:
            raise self.error

    def json(self):
        """模拟 JSON 解析。"""
        if self.json_error:
            raise self.json_error
        return self.payload


class LocationToolTest(unittest.TestCase):
    """公网 IP 定位工具测试。"""

    def test_fetch_location_data_falls_back_to_http(self):
        """HTTPS 请求失败时会集中降级到 HTTP。"""
        payload = {"status": "success", "city": "长沙"}
        with patch(
            "agent_app.tools.location.requests.get",
            side_effect=[
                requests.RequestException("https blocked"),
                FakeResponse(payload),
            ],
        ) as get:
            data, error = location._fetch_location_data()

        self.assertEqual(data["city"], "长沙")
        self.assertEqual(error, "")
        self.assertEqual(get.call_count, 2)
        self.assertTrue(get.call_args_list[0].args[0].startswith("https://"))
        self.assertTrue(get.call_args_list[1].args[0].startswith("http://"))

    def test_fetch_location_data_returns_request_error(self):
        """请求全部失败时返回错误文本。"""
        with patch("agent_app.tools.location.requests.get", side_effect=requests.RequestException("network down")):
            data, error = location._fetch_location_data()

        self.assertEqual(data, {})
        self.assertIn("network down", error)

    def test_fetch_location_data_returns_json_error(self):
        """JSON 解析失败时返回明确错误。"""
        with patch("agent_app.tools.location.requests.get", return_value=FakeResponse(json_error=ValueError("bad json"))):
            data, error = location._fetch_location_data()

        self.assertEqual(data, {})
        self.assertIn("数据格式无法解析", error)

    def test_locate_city_by_ip_returns_city_on_success(self):
        """城市定位成功时返回城市名。"""
        with patch("agent_app.tools.location._fetch_location_data", return_value=({"status": "success", "city": "长沙"}, "")):
            self.assertEqual(location.locate_city_by_ip(), "长沙")

    def test_get_location_returns_error_message(self):
        """定位失败时返回用户可读错误。"""
        with patch("agent_app.tools.location._fetch_location_data", return_value=({}, "失败")):
            result = location.get_location.invoke({})

        self.assertIn("位置查询失败：失败", result)


if __name__ == "__main__":
    unittest.main()
