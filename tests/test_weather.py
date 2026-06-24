"""
Weather模块单元测试
"""
import os
import json
import time
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

from modules.weather import WeatherInfo, WeatherService
from requests.exceptions import Timeout, RequestException


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
        # 确保缓存干净，避免测试间状态污染
        self.service._cached_weather = None
        self.service._last_update = 0

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


class TestAgentStatusAndInterval(unittest.TestCase):
    """测试Agent状态和刷新间隔逻辑"""

    def setUp(self):
        config = {"api_key": "test_key", "city": "Test"}
        self.service = WeatherService(config)

    def test_set_agent_status_working(self):
        """L102: set_agent_status设置working"""
        self.service.set_agent_status("working")
        self.assertEqual(self.service._agent_status, "working")

    def test_set_agent_status_idle(self):
        """L102: set_agent_status设置idle"""
        self.service.set_agent_status("idle")
        self.assertEqual(self.service._agent_status, "idle")

    def test_effective_interval_working(self):
        """L106-107: working状态返回短间隔"""
        self.service.set_agent_status("working")
        interval = self.service._get_effective_interval()
        self.assertEqual(interval, self.service.update_interval_working)

    def test_effective_interval_idle(self):
        """L108-109: idle状态返回长间隔"""
        self.service.set_agent_status("idle")
        interval = self.service._get_effective_interval()
        self.assertEqual(interval, self.service.update_interval_idle)

    def test_effective_interval_offline(self):
        """L108-109: offline状态返回长间隔"""
        self.service.set_agent_status("offline")
        interval = self.service._get_effective_interval()
        self.assertEqual(interval, self.service.update_interval_idle)

    def test_effective_interval_default(self):
        """L110: 其他状态返回默认间隔"""
        self.service.set_agent_status("unknown_status")
        interval = self.service._get_effective_interval()
        self.assertEqual(interval, self.service.update_interval)


class TestCacheLoadSave(unittest.TestCase):
    """测试缓存加载和保存"""

    def test_load_cache_from_file(self):
        """L116-118: 从文件加载缓存"""
        import tempfile
        cache_data = {"name": "Cached", "main": {"temp": 20}, "timestamp": 99999}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(cache_data, f)
            cache_path = f.name
        try:
            config = {"api_key": "key", "city": "Test", "cache_file": cache_path}
            service = WeatherService(config)
            self.assertEqual(service._cached_weather["name"], "Cached")
            self.assertEqual(service._last_update, 99999)
        finally:
            os.unlink(cache_path)

    def test_load_cache_no_file(self):
        """L115: 缓存文件不存在时不报错"""
        config = {"api_key": "key", "city": "Test", "cache_file": "/nonexistent/cache.json"}
        service = WeatherService(config)
        self.assertIsNone(service._cached_weather)

    def test_load_cache_corrupted_file(self):
        """L119-120: 缓存文件损坏时警告"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json {{{")
            cache_path = f.name
        try:
            config = {"api_key": "key", "city": "Test", "cache_file": cache_path}
            # 应不抛异常，只是warning
            service = WeatherService(config)
            self.assertIsNone(service._cached_weather)
        finally:
            os.unlink(cache_path)

    def test_save_cache(self):
        """L125-126: 保存缓存到文件"""
        import tempfile
        cache_path = tempfile.mktemp(suffix='.json')
        try:
            config = {"api_key": "key", "city": "Test", "cache_file": cache_path}
            service = WeatherService(config)
            test_data = {"name": "SaveTest", "main": {"temp": 25}}
            service._save_cache(test_data)
            with open(cache_path, 'r') as f:
                loaded = json.load(f)
            self.assertEqual(loaded["name"], "SaveTest")
        finally:
            if os.path.exists(cache_path):
                os.unlink(cache_path)

    def test_save_cache_permission_error(self):
        """L127-128: 保存缓存失败时警告"""
        config = {"api_key": "key", "city": "Test", "cache_file": "/invalid_dir/cache.json"}
        service = WeatherService(config)
        # 应不抛异常，只是warning
        service._save_cache({"test": True})


class TestFetchWeather(unittest.TestCase):
    """测试fetch_weather完整流程"""

    def setUp(self):
        config = {"api_key": "test_key", "city": "Shanghai", "update_interval": 1800}
        self.service = WeatherService(config)

    def test_fetch_cache_hit(self):
        """L138-143: 缓存有效时直接返回缓存数据"""
        cached = {"name": "Cached", "main": {"temp": 20}, "weather": [{"description": "缓存", "icon": "01d"}], "wind": {"speed": 1}, "timestamp": time.time()}
        self.service._cached_weather = cached
        self.service._last_update = time.time()
        result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Cached")

    def test_fetch_no_api_key(self):
        """L146-148: 无API Key时返回模拟数据"""
        self.service.api_key = ""
        result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Shanghai")

    def test_fetch_placeholder_api_key(self):
        """L146: 占位符API Key返回模拟数据"""
        self.service.api_key = "YOUR_API_KEY"
        result = self.service.fetch_weather()
        self.assertIsNotNone(result)

    def test_fetch_api_success(self):
        """L150-170: API请求成功"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "Shanghai",
            "main": {"temp": 30, "feels_like": 29, "humidity": 70},
            "weather": [{"description": "晴", "icon": "01d"}],
            "wind": {"speed": 5}
        }
        mock_response.raise_for_status = MagicMock()
        with patch.object(self.service._session, 'get', return_value=mock_response):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Shanghai")
        self.assertAlmostEqual(result.temperature, 30)
        self.assertIsNotNone(self.service._cached_weather)

    def test_fetch_timeout_with_cache(self):
        """L172-184: 超时时降级到缓存"""
        cached = {"name": "Cached", "main": {"temp": 18}, "weather": [{}], "wind": {}}
        self.service._cached_weather = cached
        self.service._last_update = 0  # 过期缓存
        with patch.object(self.service._session, 'get', side_effect=Timeout("timeout")):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Cached")

    def test_fetch_timeout_no_cache(self):
        """L172-185: 超时无缓存时返回模拟数据"""
        self.service._cached_weather = None
        with patch.object(self.service._session, 'get', side_effect=Timeout("timeout")):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "Shanghai")  # mock weather

    def test_fetch_request_exception(self):
        """L174-175: RequestException降级到缓存"""
        cached = {"name": "Cached", "main": {"temp": 15}, "weather": [{}], "wind": {}}
        self.service._cached_weather = cached
        self.service._last_update = 0
        with patch.object(self.service._session, 'get', side_effect=RequestException("network error")):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)

    def test_fetch_value_error(self):
        """L176-177: ValueError降级到缓存"""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("bad json")
        self.service._cached_weather = {"name": "X", "main": {}, "weather": [{}], "wind": {}}
        self.service._last_update = 0
        with patch.object(self.service._session, 'get', return_value=mock_response):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)

    def test_fetch_unknown_exception(self):
        """L178-179: 未知异常降级"""
        self.service._cached_weather = None
        with patch.object(self.service._session, 'get', side_effect=RuntimeError("unexpected")):
            result = self.service.fetch_weather()
        self.assertIsNotNone(result)  # mock weather

    def test_fetch_cache_expired_by_working_status(self):
        """L141-143: working状态下缓存过期但未超interval"""
        self.service.set_agent_status("working")
        cached = {"name": "W", "main": {"temp": 25}, "weather": [{}], "wind": {}}
        self.service._cached_weather = cached
        self.service._last_update = time.time() - 100  # 100s前, working interval=600s

        result = self.service.fetch_weather()
        self.assertIsNotNone(result)
        self.assertEqual(result.city, "W")  # 仍在缓存有效期内


class TestParseWeatherEdgeCases(unittest.TestCase):
    """测试_parse_weather边界情况"""

    def setUp(self):
        config = {"api_key": "key", "city": "Test"}
        self.service = WeatherService(config)

    def test_parse_empty_weather_list(self):
        """L199: weather列表为空"""
        data = {"name": "Test", "main": {"temp": 10}, "weather": [], "wind": {"speed": 2}}
        result = self.service._parse_weather(data)
        self.assertIsNotNone(result)
        self.assertEqual(result.description, "未知")

    def test_parse_invalid_temp_type(self):
        """L212-214: temperature类型错误导致异常"""
        data = {"name": "Test", "main": {"temp": "not_a_number"}, "weather": [{}], "wind": {}}
        result = self.service._parse_weather(data)
        self.assertIsNone(result)

    def test_parse_invalid_humidity_type(self):
        """L212-214: humidity类型错误"""
        data = {"name": "Test", "main": {"temp": 10, "humidity": [1, 2]}, "weather": [{}], "wind": {}}
        result = self.service._parse_weather(data)
        self.assertIsNone(result)

    def test_parse_main_not_dict(self):
        """L212-214: main字段不是dict时被except捕获，返回None"""
        data = {"name": "Test", "main": "invalid", "weather": [{}], "wind": {}}
        result = self.service._parse_weather(data)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
