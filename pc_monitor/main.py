"""
桌面电子宠物 - PC端监控程序
主程序入口
"""
import os
import sys
import json
import time
import signal
import logging
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from modules.agent_monitor import AgentMonitor, AgentStatus
from modules.token_stats import TokenTracker
from modules.weather import WeatherService
from modules.communication import create_communication, DeviceMessage

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pc_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DesktopPetMonitor:
    """桌面电子宠物监控主程序"""
    
    def __init__(self, config_path: str = "config/config.json"):
        self.config = self._load_config(config_path)
        self.running = False
        
        # 初始化模块
        self.agent_monitor = AgentMonitor(self.config.get("agent_monitor", {}))
        self.token_tracker = TokenTracker(self.config.get("token_stats", {}))
        self.weather_service = WeatherService(self.config.get("weather", {}))
        self.communication = create_communication(self.config.get("communication", {}))
        
        # 状态
        self.last_status = None
        self.last_token_stats = None
        self.last_weather = None
        
        # 定时器记录
        self._last_token_update = 0
        self._last_weather_update = 0
        
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return {}
    
    def _on_device_message(self, msg: DeviceMessage):
        """处理设备消息"""
        logger.info(f"收到设备消息: {msg.msg_type} - {msg.data}")
        
        # 处理设备请求
        if msg.msg_type == "request_status":
            self._send_status_update()
        elif msg.msg_type == "request_weather":
            self._send_weather_update()
        elif msg.msg_type == "request_tokens":
            self._send_token_update()
    
    def _send_status_update(self):
        """发送Agent状态更新"""
        state = self.agent_monitor.get_state()
        
        msg = DeviceMessage(
            msg_type="status",
            data={
                "status": state.status.value,
                "process": state.process_name,
                "cpu": round(state.cpu_percent, 1),
                "memory": round(state.memory_mb, 1),
                "uptime": int(state.uptime_seconds)
            },
            timestamp=time.time()
        )
        
        self.communication.send_message(msg)
        logger.info(f"状态已发送: {state.status.value}")
    
    def _send_weather_update(self):
        """发送天气更新"""
        weather = self.weather_service.fetch_weather()
        if not weather:
            return
        
        icon_name = self.weather_service.get_icon_name(weather.icon_code)
        
        msg = DeviceMessage(
            msg_type="weather",
            data={
                "city": weather.city,
                "temp": weather.temperature,
                "feels_like": weather.feels_like,
                "humidity": weather.humidity,
                "desc": weather.description,
                "icon": icon_name,
                "wind": weather.wind_speed
            },
            timestamp=time.time()
        )
        
        self.communication.send_message(msg)
        logger.info(f"天气已发送: {weather.description} {weather.temperature}℃")
    
    def _send_token_update(self):
        """发送Token统计更新"""
        stats = self.token_tracker.get_stats()
        
        msg = DeviceMessage(
            msg_type="token",
            data={
                "input": stats.total_input_tokens,
                "output": stats.total_output_tokens,
                "requests": stats.total_requests,
                "hour": stats.tokens_last_hour,
                "cost": round(stats.estimated_cost_usd, 2)
            },
            timestamp=time.time()
        )
        
        self.communication.send_message(msg)
        logger.info(f"Token统计已发送: {stats.total_requests} 次请求")
    
    def _periodic_update(self):
        """定时更新任务"""
        update_interval = self.config.get("display", {}).get("update_interval", 5)
        token_interval = self.config.get("token_stats", {}).get("update_interval", 30)
        weather_interval = self.config.get("weather", {}).get("update_interval", 1800)
        
        now = time.time()
        self._last_token_update = now
        self._last_weather_update = now
        
        while self.running:
            now = time.time()
            
            # 每次循环都发送状态更新
            self._send_status_update()
            
            # Token统计：按配置间隔更新
            if now - self._last_token_update >= token_interval:
                self._last_token_update = now
                self._send_token_update()
            
            # 天气：按配置间隔更新
            if now - self._last_weather_update >= weather_interval:
                self._last_weather_update = now
                self._send_weather_update()
            
            time.sleep(update_interval)
    
    def start(self):
        """启动监控程序"""
        logger.info("=" * 50)
        logger.info("桌面电子宠物监控程序启动")
        logger.info("=" * 50)
        
        # 连接设备
        if not self.communication.connect():
            logger.error("无法连接到ESP32设备，请检查连接设置")
            return False
        
        # 设置消息回调
        self.communication.set_message_callback(self._on_device_message)
        
        self.running = True
        
        # 启动定时更新线程
        import threading
        update_thread = threading.Thread(target=self._periodic_update, daemon=True)
        update_thread.start()
        
        logger.info("监控程序已启动，等待设备请求...")
        
        # 主循环
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到退出信号")
        finally:
            self.stop()
        
        return True
    
    def stop(self):
        """停止监控程序"""
        logger.info("正在停止监控程序...")
        self.running = False
        self.communication.disconnect()
        logger.info("监控程序已停止")


def main():
    """主函数"""
    # 设置工作目录
    os.chdir(Path(__file__).parent)
    
    # 信号处理
    monitor = DesktopPetMonitor()
    
    def signal_handler(sig, frame):
        logger.info(f"收到信号 {sig}")
        monitor.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动监控
    success = monitor.start()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
