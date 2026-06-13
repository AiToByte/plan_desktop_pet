"""
Weather模块单元测试
"""
import time
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

from modules.weather import WeatherInfo, WeatherService


class TestWeatherInfo(unittest.TestCase):
    """测试WeatherInfo数据类"""

    def test_creation(self):
        """测试创建WeatherInfo"""
        info = WeatherInfo(
            city="Beijing",
            temperature=25.0,
            feels_like=24.0,
            humidity=50,
            description="晴",
            icon_code="01d",
            wind_speed=3.5,
            timestamp=time.time()
        )
        self.assertEqual(info.city, "Beijing")
        self.assertAlmostEqual(info.temperature, 25.0)
        self.assertEqual(info.humidity, 50)

    def test_dataclass_fields(self):
        """测试字段类型"""
        info = WeatherInfo(
            city="Test",
            temperature=20.0,
            feels_like=19.0,
            humidity=60,
            description="多云",
            icon_code="03d",
            wind_speed=2.0,
            timestamp=1234567890.0
        )
        self.assertIsInstance(info.city, str)
        self.assertIsInstance(info.temperature, float)
        self.assertIsInstance(info.humidity, int)
        self.assertIsInstance(info.wind_speed, float)


class TestWeatherService(unittest.TestCase):
    """测试WeatherService"""

    def setUp(self):
        """创建WeatherService实例"""
        config = {
            "api_key": "test_key",
            "city": "Shanghai",
            "update_interval": 1800,
        }
        self.service = WeatherService(config)

    def test_initialization(self):
        """测试初始化"""
        self.assertEqual(self.service.api_key, "test_key")
        self.assertEqual(self.service.city, "Shanghai")
        self.assertEqual(self.service.update_interval, 1800)

    def test_icon_map(self):
        """测试图标映射完整性"""
        expected_icons = [
            "01d", "01n", "02d", "02n", "03d", "03n",
            "04d", "04n", "09d", "09n", "10d", "10n",
            "11d", "11n", "13d", "13n", "50d", "50n"
        ]
        for icon in expected_icons:
            self.assertIn(icon, self.service.ICON_MAP, f"Missing icon: {icon}")

    def test_get_icon_name(self):
        """测试图标名称获取"""
        self.assertEqual(self.service.get_icon_name("01d"), "sun")
        self.assertEqual(self.service.get_icon_name("01n"), "moon")
        self.assertEqual(self.service.get_icon_name("10d"), "rain")
        self.assertEqual(self.service.get_icon_name("unknown"), "cloud")

    def test_mock_weather(self):
        """测试模拟天气数据"""
        mock = self.service._get_mock_weather()
        self.assertIsInstance(mock, WeatherInfo)
        self.assertEqual(mock.city, "Shanghai")
        self.assertAlmostEqual(mock.temperature, 22.0)
        self.assertEqual(mock.icon_code, "01d")

    def test_parse_weather_valid(self):
        """测试解析有效天气数据"""
        data = {
            "name": "Beijing",
            "main": {
                "temp": 28.5,
                "feels_like": 27.0,
                "humidity": 65
            },
            "weather": [{
                "description": "晴",
                "icon": "01d"
            }],
            "wind": {
                "speed": 4.2
            }
        }
        result = self.service._parse_weather(data)
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Beijing")
        self.assertAlmostEqual(result.temperature, 28.5)
        self.assertEqual(result.humidity, 65)
        self.assertEqual(result.description, "晴")
        self.assertEqual(result.icon_code, "01d")
        self.assertAlmostEqual(result.wind_speed, 4.2)

    def test_parse_weather_missing_fields(self):
        """测试解析缺少字段的数据"""
        data = {
            "name": "Test",
            "main": {},
            "weather": [{}],
            "wind": {}
        }
        result = self.service._parse_weather(data)
        self.assertIsNotNone(result)
        self.assertEqual(result.temperature, 0)
        self.assertEqual(result.humidity, 0)

    def test_parse_weather_empty(self):
        """测试解析空数据"""
        data = {}
        result = self.service._parse_weather(data)
        self.assertIsNotNone(result)

    def test_cache_initially_empty(self):
        """测试初始缓存为空"""
        self.assertIsNone(self.service._cached_weather)
        self.assertEqual(self.service._last_update, 0)


if __name__ == "__main__":
    unittest.main()
