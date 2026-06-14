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
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Callable

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from modules.agent_monitor import AgentMonitor, AgentStatus
from modules.token_stats import TokenTracker
from modules.weather import WeatherService
from modules.communication import create_communication, DeviceMessage
from modules.otlp_receiver import OTLPReceiver
from tray_app import TrayApp

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
# --- 常量 (main) ---
MAIN_LOOP_INTERVAL = 1        # 主循环轮询间隔 (秒)
DEFAULT_OTLP_PORT = 4318      # OTLP 默认端口



class DesktopPetMonitor:
    """桌面电子宠物监控主程序"""
    
    config: Dict[str, Any]
    running: bool
    agent_monitor: AgentMonitor
    token_tracker: TokenTracker
    weather_service: WeatherService
    communication: Any
    _otlp_receiver: OTLPReceiver
    last_status: Optional[Any]
    last_token_stats: Optional[Any]
    last_weather: Optional[Any]
    _last_token_update: float
    _last_weather_update: float
    
    def __init__(self, config_path: str = "config/config.json") -> None:
        self.config = self._load_config(config_path)
        self.running = False
        
        # 初始化模块
        self.agent_monitor = AgentMonitor(self.config.get("agent_monitor", {}))
        self.token_tracker = TokenTracker(self.config.get("token_stats", {}))
        self.weather_service = WeatherService(self.config.get("weather", {}))
        self.communication = create_communication(self.config.get("communication", {}))
        
        # OTLP接收器
        otlp_port = self.config.get("otlp", {}).get("port", DEFAULT_OTLP_PORT)
        self._otlp_receiver = OTLPReceiver(port=otlp_port)
        self._otlp_receiver.set_span_callback(self._on_otlp_span)
        
        # 状态
        self.last_status = None
        self.last_token_stats = None
        self.last_weather = None
        
        # 定时器记录
        self._last_token_update = 0.0
        self._last_weather_update = 0.0
        self._tray_app = None  # 托盘应用引用
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 验证配置
            errors = self._validate_config(config)
            if errors:
                for err in errors:
                    logger.warning(f"配置验证警告: {err}")
            return config
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return {}
    
    def _validate_config(self, config: Dict[str, Any]) -> list:
        """验证配置有效性，返回警告列表"""
        warnings = []
        
        # 检查agent_monitor配置
        if "agent_monitor" in config:
            am = config["agent_monitor"]
            if not isinstance(am.get("url", ""), str):
                warnings.append("agent_monitor.url 应为字符串类型")
        
        # 检查communication配置
        if "communication" in config:
            comm = config["communication"]
            if "mode" in comm and comm["mode"] not in ["serial", "wifi"]:
                warnings.append(f"communication.mode 值 '{comm['mode']}' 无效，应为 'serial' 或 'wifi'")
            if comm.get("mode") == "serial":
                if "port" not in comm:
                    warnings.append("串口模式缺少 communication.port 配置")
            elif comm.get("mode") == "wifi":
                if "tcp_port" not in comm:
                    warnings.append("WiFi模式缺少 communication.tcp_port 配置")
        
        # 检查token_stats配置
        if "token_stats" in config:
            ts = config["token_stats"]
            if "log_file" in ts:
                import os
                log_path = os.path.expanduser(ts["log_file"])
                if not os.path.exists(log_path):
                    warnings.append(f"token_stats.log_file 路径不存在: {log_path}")
        
        return warnings
    
    def _on_device_message(self, msg: DeviceMessage) -> None:
        """处理设备消息"""
        logger.info(f"收到设备消息: {msg.msg_type} - {msg.data}")
        
        # 处理设备请求
        if msg.msg_type == "request_status":
            self._send_status_update()
        elif msg.msg_type == "request_weather":
            self._send_weather_update()
        elif msg.msg_type == "request_tokens":
            self._send_token_update()
    
    def _send_status_update(self) -> None:
        """发送Agent状态更新"""
        state = self.agent_monitor.get_state()
        
        # 同步Agent状态给天气服务，激活自适应刷新率
        self.weather_service.set_agent_status(state.status.value)
        
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
        self._forward_to_tray({
            'status': state.status.value,
            'cpu': round(state.cpu_percent, 1),
            'mem': round(state.memory_mb, 1),
            'uptime': int(state.uptime_seconds),
        })
        logger.info(f"状态已发送: {state.status.value}")
    
    def _send_weather_update(self) -> None:
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
    
    def _send_token_update(self) -> None:
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
        self._forward_to_tray({
            'input_tokens': stats.total_input_tokens,
            'output_tokens': stats.total_output_tokens,
            'requests': stats.total_requests,
        })
        logger.info(f"Token统计已发送: {stats.total_requests} 次请求")
    
    def set_tray_app(self, tray_app) -> None:
        """设置托盘应用引用，用于实时推送指标"""
        self._tray_app = tray_app

    def _forward_to_tray(self, data: dict) -> None:
        """将指标数据转发给托盘面板"""
        if self._tray_app:
            try:
                self._tray_app.update_metrics(data)
            except Exception as e:
                logger.debug(f"Tray update error: {e}")

    def _periodic_update(self) -> None:
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
    
    def start(self) -> bool:
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
        
        # 启动OTLP接收器
        self._otlp_receiver.start()
        logger.info(f"OTLP接收器已启动，端口: {otlp_port}")
        
        # 启动定时更新线程
        update_thread = threading.Thread(target=self._periodic_update, daemon=True)
        update_thread.start()
        
        logger.info("监控程序已启动，等待设备请求...")
        
        # 主循环
        try:
            while self.running:
                time.sleep(MAIN_LOOP_INTERVAL)
        except KeyboardInterrupt:
            logger.info("收到退出信号")
        finally:
            self.stop()
        
        return True
    
    def stop(self) -> None:
        """停止监控程序"""
        logger.info("正在停止监控程序...")
        self.running = False
        self._otlp_receiver.stop()
        self.communication.disconnect()
        logger.info("监控程序已停止")
    
    def _on_otlp_span(self, span: Any) -> None:
        """处理OTLP接收的span，转发给ESP32显示"""
        status_mapping = {
            "agent.idle": "idle",
            "agent.thinking": "working",
            "agent.generating": "working",
            "agent.tool_call": "working",
            "agent.waiting": "idle",
            "agent.error": "offline",
            "agent.complete": "idle",
        }
        detail_mapping = {
            "agent.idle": "空闲",
            "agent.thinking": "思考中...",
            "agent.generating": "生成中...",
            "agent.tool_call": f"调用 {span.attributes.get('tool.name', '工具')}...",
            "agent.waiting": "等待输入",
            "agent.error": f"错误: {span.status_message or '未知'}",
            "agent.complete": "完成",
        }
        
        if span.name not in status_mapping:
            return
        
        device_status = status_mapping[span.name]
        detail = detail_mapping.get(span.name, "")
        
        # 工具调用时优先用自定义detail
        if span.name == "agent.tool_call" and span.attributes.get('agent.detail'):
            detail = span.attributes.get('agent.detail')
        
        msg = DeviceMessage(
            msg_type="status",
            data={
                "agent_status": device_status,
                "agent_name": span.attributes.get("agent.name", "AI Agent"),
                "task_desc": detail,
                "timestamp": span.start_time / 1e9 if span.start_time else time.time()
            },
            timestamp=time.time()
        )
        
        if self.communication.is_connected():
            self.communication.send_message(msg)
            logger.debug(f"OTLP转发: {span.name} → {device_status}")


def _simulate_tray(app: TrayApp) -> None:
    """模拟数据（仅 --tray-only 调试模式）"""
    import random
    while True:
        app.update_metrics({
            'status': random.choice(['Idle', 'Working', 'Auth']),
            'cpu': random.uniform(5, 80),
            'mem': random.uniform(100, 500),
            'uptime': f"{random.randint(0, 24)}h {random.randint(0, 59)}m",
            'crash_count': 0,
            'input_tokens': random.randint(100, 2000),
            'output_tokens': random.randint(50, 800),
        })
        time.sleep(2)


def main() -> None:
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description="ESP32 桌面宠物 PC监控程序")
    parser.add_argument('--tray', action='store_true', help='启动系统托盘GUI面板')
    parser.add_argument('--tray-only', action='store_true', help='仅启动托盘面板（模拟数据调试模式）')
    args = parser.parse_args()

    os.chdir(Path(__file__).parent)

    # --tray-only: 仅启动托盘（调试用）
    if args.tray_only:
        app = TrayApp()
        threading.Thread(target=lambda: _simulate_tray(app), daemon=True).start()
        app.run()
        return

    monitor = DesktopPetMonitor()

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info(f"收到信号 {sig}")
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.tray:
        # 托盘模式：后台监控 + 前台GUI
        if not monitor.communication.connect():
            logger.error("无法连接到ESP32设备")
            sys.exit(1)
        monitor.communication.set_message_callback(monitor._on_device_message)
        monitor.running = True
        monitor._otlp_receiver.start()

        app = TrayApp(on_exit_callback=lambda: (setattr(monitor, 'running', False), monitor.stop()))
        monitor.set_tray_app(app)

        update_thread = threading.Thread(target=monitor._periodic_update, daemon=True)
        update_thread.start()
        logger.info("监控+托盘GUI已启动")

        app.run()  # 主线程tkinter事件循环
        monitor.stop()
    else:
        # 纯命令行模式
        success = monitor.start()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
