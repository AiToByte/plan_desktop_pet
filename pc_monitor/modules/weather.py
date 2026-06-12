"""
天气信息获取模块
调用天气API获取实时天气数据
"""
import os
import requests
import time
import json
import logging
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WeatherInfo:
    """天气信息"""
    city: str
    temperature: float      # 温度(℃)
    feels_like: float       # 体感温度(℃)
    humidity: int           # 湿度(%)
    description: str        # 天气描述
    icon_code: str          # 图标代码
    wind_speed: float       # 风速(m/s)
    timestamp: float


class WeatherService:
    """天气服务"""
    
    # OpenWeatherMap API
    BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
    
    # 天气图标映射 (用于ESP32显示)
    ICON_MAP = {
        "01d": "sun",           # 晴天
        "01n": "moon",          # 晴夜
        "02d": "cloud_sun",     # 少云
        "02n": "cloud_moon",    # 少云夜
        "03d": "cloud",         # 多云
        "03n": "cloud",
        "04d": "clouds",        # 阴天
        "04n": "clouds",
        "09d": "rain_light",    # 小雨
        "09n": "rain_light",
        "10d": "rain",          # 雨
        "10n": "rain",
        "11d": "thunder",       # 雷暴
        "11n": "thunder",
        "13d": "snow",          # 雪
        "13n": "snow",
        "50d": "fog",           # 雾
        "50n": "fog"
    }
    
    def __init__(self, config: dict):
        self.api_key = config.get("api_key", "")
        self.city = config.get("city", "Beijing")
        self.update_interval = config.get("update_interval", 1800)
        self.update_interval_idle = config.get("update_interval_idle", 3600)     # 空闲时刷新间隔(秒)
        self.update_interval_working = config.get("update_interval_working", 600) # 工作中刷新间隔(秒)
        self.cache_file = config.get("cache_file", "weather_cache.json")
        self._cached_weather = None
        self._last_update = 0
        self._agent_status = "idle"  # 当前Agent状态
        self._load_cache()
    
    def set_agent_status(self, status: str):
        """设置当前Agent状态，影响天气刷新频率"""
        self._agent_status = status
    
    def _get_effective_interval(self) -> int:
        """根据Agent状态返回对应的刷新间隔"""
        if self._agent_status == "working":
            return self.update_interval_working
        elif self._agent_status in ("idle", "offline"):
            return self.update_interval_idle
        return self.update_interval  # 默认间隔
    
    def _load_cache(self):
        """加载天气缓存"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    self._cached_weather = json.load(f)
                    self._last_update = self._cached_weather.get("timestamp", 0)
        except Exception as e:
            logger.warning(f"加载天气缓存失败: {e}")
    
    def _save_cache(self, weather: dict):
        """保存天气缓存"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(weather, f)
        except Exception as e:
            logger.warning(f"保存天气缓存失败: {e}")
    
    def fetch_weather(self) -> Optional[WeatherInfo]:
        """获取天气信息"""
        now = time.time()
        
        # 检查缓存是否有效（根据Agent状态动态调整间隔）
        effective_interval = self._get_effective_interval()
        if self._cached_weather and (now - self._last_update) < effective_interval:
            return self._parse_weather(self._cached_weather)
        
        # 检查API Key
        if not self.api_key or self.api_key == "YOUR_API_KEY":
            logger.warning("未配置天气API Key，返回模拟数据")
            return self._get_mock_weather()
        
        try:
            params = {
                "q": self.city,
                "appid": self.api_key,
                "units": "metric",
                "lang": "zh_cn"
            }
            
            response = requests.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self._cached_weather = data
            self._last_update = now
            self._save_cache(data)
            
            return self._parse_weather(data)
            
        except Exception as e:
            logger.error(f"获取天气失败: {e}")
            if self._cached_weather:
                return self._parse_weather(self._cached_weather)
            return self._get_mock_weather()
    
    def _parse_weather(self, data: dict) -> Optional[WeatherInfo]:
        """解析天气数据"""
        try:
            main = data.get("main", {})
            weather = data.get("weather", [{}])[0]
            wind = data.get("wind", {})
            
            return WeatherInfo(
                city=data.get("name", self.city),
                temperature=main.get("temp", 0),
                feels_like=main.get("feels_like", 0),
                humidity=main.get("humidity", 0),
                description=weather.get("description", "未知"),
                icon_code=weather.get("icon", "01d"),
                wind_speed=wind.get("speed", 0),
                timestamp=time.time()
            )
        except Exception as e:
            logger.error(f"解析天气数据失败: {e}")
            return None
    
    def _get_mock_weather(self) -> WeatherInfo:
        """返回模拟天气数据"""
        return WeatherInfo(
            city=self.city,
            temperature=22.0,
            feels_like=21.0,
            humidity=45,
            description="晴",
            icon_code="01d",
            wind_speed=3.5,
            timestamp=time.time()
        )
    
    def get_icon_name(self, icon_code: str) -> str:
        """获取图标名称"""
        return self.ICON_MAP.get(icon_code, "cloud")
