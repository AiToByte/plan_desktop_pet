"""
天气信息获取模块
调用天气API获取实时天气数据

功能：
- 获取实时天气信息
- 支持多种天气图标映射
- 缓存机制减少API调用
- 根据Agent状态动态调整刷新频率
"""
import os
import time
import json
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

# 常量定义
DEFAULT_API_TIMEOUT: int = 10  # 秒
DEFAULT_UPDATE_INTERVAL: int = 1800  # 30分钟
DEFAULT_UPDATE_INTERVAL_IDLE: int = 3600  # 1小时
DEFAULT_UPDATE_INTERVAL_WORKING: int = 600  # 10分钟
DEFAULT_CITY: str = "Beijing"
DEFAULT_TEMPERATURE: float = 22.0
DEFAULT_HUMIDITY: int = 45
DEFAULT_WIND_SPEED: float = 3.5
DEFAULT_DESCRIPTION: str = "晴"
DEFAULT_ICON_CODE: str = "01d"
MOCK_CITY_SUFFIX: str = "_mock"


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
    """天气服务
    
    Attributes:
        BASE_URL: OpenWeatherMap API地址
        ICON_MAP: 天气图标代码到ESP32显示名称的映射
    """
    
    # OpenWeatherMap API
    BASE_URL: str = "https://api.openweathermap.org/data/2.5/weather"
    
    # 天气图标映射 (用于ESP32显示)
    ICON_MAP: Dict[str, str] = {
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
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """初始化天气服务
        
        Args:
            config: 配置字典，包含api_key, city, update_interval等
        """
        self.api_key: str = config.get("api_key", "")
        self.city: str = config.get("city", DEFAULT_CITY)
        self.update_interval: int = config.get("update_interval", DEFAULT_UPDATE_INTERVAL)
        self.update_interval_idle: int = config.get("update_interval_idle", DEFAULT_UPDATE_INTERVAL_IDLE)
        self.update_interval_working: int = config.get("update_interval_working", DEFAULT_UPDATE_INTERVAL_WORKING)
        self.cache_file: str = config.get("cache_file", "weather_cache.json")
        self._cached_weather: Optional[Dict[str, Any]] = None
        self._last_update: float = 0.0
        self._agent_status: str = "idle"
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
        """获取天气信息
        
        优先使用缓存，缓存过期则请求API。API失败时返回缓存或模拟数据。
        
        Returns:
            WeatherInfo对象，失败时返回模拟数据
        """
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
            params: Dict[str, str] = {
                "q": self.city,
                "appid": self.api_key,
                "units": "metric",
                "lang": "zh_cn"
            }
            
            response = requests.get(
                self.BASE_URL, 
                params=params, 
                timeout=DEFAULT_API_TIMEOUT
            )
            response.raise_for_status()
            
            data: Dict[str, Any] = response.json()
            self._cached_weather = data
            self._last_update = now
            self._save_cache(data)
            
            return self._parse_weather(data)
            
        except Timeout:
            logger.error("天气API请求超时")
        except RequestException as e:
            logger.error(f"天气API请求失败: {e}")
        except (ValueError, KeyError) as e:
            logger.error(f"天气数据解析错误: {e}")
        except Exception as e:
            logger.error(f"获取天气时发生未知错误: {e}", exc_info=True)
        
        # 降级：返回缓存或模拟数据
        if self._cached_weather:
            logger.info("使用缓存的天气数据")
            return self._parse_weather(self._cached_weather)
        return self._get_mock_weather()
    
    def _parse_weather(self, data: Dict[str, Any]) -> Optional[WeatherInfo]:
        """解析天气API返回的数据
        
        Args:
            data: OpenWeatherMap API返回的JSON数据
            
        Returns:
            WeatherInfo对象，解析失败返回None
        """
        try:
            main: Dict[str, Any] = data.get("main", {})
            weather_list: list = data.get("weather", [{}])
            weather: Dict[str, Any] = weather_list[0] if weather_list else {}
            wind: Dict[str, Any] = data.get("wind", {})
            
            return WeatherInfo(
                city=str(data.get("name", self.city)),
                temperature=float(main.get("temp", 0)),
                feels_like=float(main.get("feels_like", 0)),
                humidity=int(main.get("humidity", 0)),
                description=str(weather.get("description", "未知")),
                icon_code=str(weather.get("icon", DEFAULT_ICON_CODE)),
                wind_speed=float(wind.get("speed", 0)),
                timestamp=time.time()
            )
        except (ValueError, KeyError, IndexError, TypeError) as e:
            logger.error(f"解析天气数据失败: {e}")
            return None
    
    def _get_mock_weather(self) -> WeatherInfo:
        """返回模拟天气数据（API不可用时的降级方案）"""
        return WeatherInfo(
            city=self.city,
            temperature=DEFAULT_TEMPERATURE,
            feels_like=DEFAULT_TEMPERATURE - 1.0,
            humidity=DEFAULT_HUMIDITY,
            description=DEFAULT_DESCRIPTION,
            icon_code=DEFAULT_ICON_CODE,
            wind_speed=DEFAULT_WIND_SPEED,
            timestamp=time.time()
        )
    
    def get_icon_name(self, icon_code: str) -> str:
        """获取图标名称"""
        return self.ICON_MAP.get(icon_code, "cloud")
