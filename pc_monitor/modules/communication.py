"""
通信模块
实现PC与ESP32之间的通信（串口/WiFi）
"""
import socket
import serial
import json
import time
import logging
import threading
from typing import Callable, Optional
from queue import Queue, Empty
import struct
from dataclasses import dataclass, field

# 默认配置常量
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_SERIAL_BAUD = 115200
DEFAULT_WIFI_HOST = "0.0.0.0"
DEFAULT_WIFI_PORT = 19876
DEFAULT_UDP_BROADCAST_PORT = 19877
DEFAULT_RETRY_INTERVAL = 5
DEFAULT_UDP_BROADCAST_INTERVAL = 5
DEFAULT_SERIAL_TIMEOUT = 1
DEFAULT_SOCKET_ACCEPT_TIMEOUT = 1
DEFAULT_SOCKET_CLIENT_TIMEOUT = 5
DEFAULT_RECONNECT_ATTEMPTS = 3
DEFAULT_RECONNECT_DELAY = 2
SERIAL_READ_POLL_INTERVAL = 0.01
ERROR_RECOVERY_DELAY = 0.1
BROADCAST_SLEEP_STEP = 0.1
RECV_BUFFER_SIZE = 4096
MDNS_HOSTNAME = "deskpet.local"
# Keep-Alive 配置
KEEPALIVE_INTERVAL = 10    # 每10秒发送ping
KEEPALIVE_TIMEOUT = 30     # 30秒无pong视为断连
SEND_QUEUE_MAXSIZE = 64    # 异步发送队列最大容量
# [Phase 2] 崩溃遥测配置
CRASH_REPORT_COOLDOWN = 60  # 崩溃报告冷却时间(秒)，防刷屏


logger = logging.getLogger(__name__)


@dataclass
class DeviceMessage:
    """设备消息"""
    msg_type: str                           # 消息类型: status, token, weather, animation
    data: dict = field(default_factory=dict) # 消息数据
    timestamp: float = field(default_factory=time.time)  # 时间戳


class CommunicationBase:
    """通信基类"""
    
    def __init__(self):
        self._connected = False
        self._message_callback: Optional[Callable[[DeviceMessage], None]] = None
        self._running = False
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = DEFAULT_RECONNECT_ATTEMPTS
        self._reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    
    def set_message_callback(self, callback: Callable[[DeviceMessage], None]):
        """设置消息回调"""
        self._message_callback = callback
    
    def connect(self) -> bool:
        raise NotImplementedError
    
    def disconnect(self):
        raise NotImplementedError
    
    def send_message(self, msg: DeviceMessage) -> bool:
        raise NotImplementedError
    
    def is_connected(self) -> bool:
        return self._connected

    def _process_received(self, data: str) -> None:
        """处理接收到的数据（解析JSON并触发回调）"""
        try:
            msg_data = json.loads(data)
            msg = DeviceMessage(
                msg_type=msg_data.get("type", "unknown"),
                data=msg_data.get("data", {}),
                timestamp=msg_data.get("ts", time.time())
            )
            if self._message_callback:
                self._message_callback(msg)
        except json.JSONDecodeError:
            logger.warning(f"收到无效JSON: {data}")


class SerialCommunication(CommunicationBase):
    """串口通信"""
    
    def __init__(self, config: dict):
        super().__init__()
        self.port = config.get("serial_port", DEFAULT_SERIAL_PORT)
        self.baudrate = config.get("serial_baud", DEFAULT_SERIAL_BAUD)
        self._serial: Optional[serial.Serial] = None
        self._read_thread: Optional[threading.Thread] = None
    
    def connect(self) -> bool:
        """连接串口"""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=DEFAULT_SERIAL_TIMEOUT
            )
            self._connected = True
            self._running = True
            
            # 启动读取线程
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
            
            logger.info(f"串口连接成功: {self.port}")
            return True
            
        except Exception as e:
            logger.error(f"串口连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开串口"""
        self._running = False
        self._connected = False
        if self._serial and self._serial.is_open:
            self._serial.close()
        logger.info("串口已断开")
    
    def send_message(self, msg: DeviceMessage) -> bool:
        """发送消息（带长度前缀帧）"""
        if not self._connected or not self._serial:
            # 尝试重连
            if self._reconnect_attempts < self._max_reconnect_attempts:
                logger.info(f"尝试重连 ({self._reconnect_attempts + 1}/{self._max_reconnect_attempts})")
                if self.connect():
                    self._reconnect_attempts = 0
                else:
                    self._reconnect_attempts += 1
                    time.sleep(self._reconnect_delay)
            return False
        
        try:
            payload = json.dumps({
                "type": msg.msg_type,
                "data": msg.data,
                "ts": msg.timestamp
            })
            frame = f"LEN:{len(payload)}\n{payload}\n"
            self._serial.write(frame.encode('utf-8'))
            self._reconnect_attempts = 0  # 发送成功，重置重连计数
            return True
            
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            # 尝试重连
            if self._reconnect_attempts < self._max_reconnect_attempts:
                logger.info(f"发送失败，尝试重连 ({self._reconnect_attempts + 1}/{self._max_reconnect_attempts})")
                if self.connect():
                    self._reconnect_attempts = 0
                    # 重新发送
                    try:
                        self._serial.write(frame.encode('utf-8'))
                        return True
                    except Exception as retry_e:
                        logger.error(f"重连后重试发送失败: {retry_e}")
                else:
                    self._reconnect_attempts += 1
                    time.sleep(self._reconnect_delay)
            return False
    
    def _read_loop(self):
        """读取数据循环（支持长度前缀帧 + 旧格式fallback）"""
        buffer = ""
        expected_len = None
        payload_buf = ""
        
        while self._running and self._connected:
            try:
                if self._serial and self._serial.in_waiting:
                    char = self._serial.read().decode('utf-8', errors='ignore')
                    if char == '\n':
                        line = buffer
                        buffer = ""
                        
                        if expected_len is not None:
                            # 正在读取帧payload
                            payload_buf += line
                            if len(payload_buf) >= expected_len:
                                self._process_received(payload_buf[:expected_len])
                                expected_len = None
                                payload_buf = ""
                        elif line.startswith("LEN:"):
                            # 新帧协议: LEN:NNNN
                            try:
                                expected_len = int(line[4:])
                                payload_buf = ""
                            except ValueError:
                                logger.warning(f"Invalid LEN line: {line}")
                        elif line:
                            # 旧格式fallback: 纯JSON行
                            self._process_received(line.strip())
                    else:
                        buffer += char
                else:
                    time.sleep(SERIAL_READ_POLL_INTERVAL)
                    
            except Exception as e:
                logger.error(f"读取串口数据错误: {e}")
                time.sleep(ERROR_RECOVERY_DELAY)
    

class WiFiCommunication(CommunicationBase):
    """WiFi通信（PC端作为TCP Server，等待ESP32连接）"""
    
    def __init__(self, config: dict):
        super().__init__()
        self.host = config.get("wifi_host", DEFAULT_WIFI_HOST)
        self.port = config.get("wifi_port", DEFAULT_WIFI_PORT)
        self.retry_interval = config.get("retry_interval", DEFAULT_RETRY_INTERVAL)
        self.udp_broadcast_port = config.get("udp_broadcast_port", DEFAULT_UDP_BROADCAST_PORT)
        self.udp_broadcast_interval = config.get("udp_broadcast_interval", DEFAULT_UDP_BROADCAST_INTERVAL)
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._client_addr: Optional[tuple] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._read_thread: Optional[threading.Thread] = None
        self._udp_broadcast_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # 异步发送队列 + 保活
        self._send_queue: Queue = Queue(maxsize=SEND_QUEUE_MAXSIZE)
        self._send_worker_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._last_pong_time: float = 0
        self._ping_pending: bool = False
    
    @staticmethod
    def resolve_mdns(hostname: str = MDNS_HOSTNAME) -> Optional[str]:
        """通过mDNS解析设备主机名，返回IP或None"""
        try:
            addr = socket.getaddrinfo(hostname, None, socket.AF_INET)
            if addr:
                ip = addr[0][4][0]
                logger.info(f"mDNS解析 {hostname} -> {ip}")
                return ip
        except (socket.gaierror, OSError):
            logger.debug(f"mDNS解析 {hostname} 失败")
        return None
    
    def connect(self) -> bool:
        """启动TCP Server，等待ESP32连接"""
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.settimeout(DEFAULT_SOCKET_ACCEPT_TIMEOUT)
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(1)
            
            self._connected = True
            self._running = True
            
            # 启动接受连接线程
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()
            
            # 启动UDP广播线程（设备自动发现）
            self._udp_broadcast_thread = threading.Thread(target=self._udp_broadcast_loop, daemon=True)
            self._udp_broadcast_thread.start()
            
            logger.info(f"TCP Server 已启动，监听 {self.host}:{self.port}，UDP广播端口 {self.udp_broadcast_port}")
            
            # 启动异步发送队列worker
            self._send_worker_thread = threading.Thread(target=self._send_queue_worker, daemon=True)
            self._send_worker_thread.start()
            
            # 启动Keep-Alive线程
            self._last_pong_time = time.time()
            self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._keepalive_thread.start()
            
            return True
            
        except Exception as e:
            logger.error(f"TCP Server 启动失败: {e}")
            return False
    
    def _accept_loop(self):
        """接受客户端连接循环"""
        while self._running:
            try:
                client_socket, client_addr = self._server_socket.accept()
                client_socket.settimeout(DEFAULT_SOCKET_CLIENT_TIMEOUT)
                
                with self._lock:
                    # 如果已有连接，关闭旧连接
                    if self._client_socket:
                        try:
                            self._client_socket.close()
                        except Exception:
                            pass
                    
                    self._client_socket = client_socket
                    self._client_addr = client_addr
                
                logger.info(f"ESP32 已连接: {client_addr[0]}:{client_addr[1]}")
                self._connected = True
                
                # 启动读取线程
                if self._read_thread and self._read_thread.is_alive():
                    # 旧的读取线程会因为 socket 关闭而退出
                    pass
                self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._read_thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"接受连接错误: {e}")
                time.sleep(1)
    
    def _get_local_ip(self) -> str:
        """获取本机局域网IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def _udp_broadcast_loop(self):
        """UDP广播循环：每N秒向局域网广播服务器地址"""
        local_ip = self._get_local_ip()
        msg = f"DESKTOP_PET_SERVER:{local_ip}:{self.port}"
        
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_sock.settimeout(1)
        
        logger.info(f"UDP广播已启动: {msg} -> port {self.udp_broadcast_port}")
        
        while self._running:
            try:
                udp_sock.sendto(msg.encode('utf-8'), ('<broadcast>', self.udp_broadcast_port))
            except Exception as e:
                logger.warning(f"UDP广播发送失败: {e}")
            
            # 分段sleep，快速响应_running变化
            for _ in range(int(self.udp_broadcast_interval * 10)):
                if not self._running:
                    break
                time.sleep(BROADCAST_SLEEP_STEP)
        
        try:
            udp_sock.close()
        except Exception:
            pass
        logger.info("UDP广播已停止")
    
    def disconnect(self):
        """断开连接并关闭服务器"""
        self._running = False
        self._connected = False
        
        with self._lock:
            if self._client_socket:
                try:
                    self._client_socket.close()
                except Exception:
                    pass
                self._client_socket = None
                self._client_addr = None
            
            if self._server_socket:
                try:
                    self._server_socket.close()
                except Exception:
                    pass
                self._server_socket = None
        
        logger.info("TCP Server 已关闭")
    
    def send_message(self, msg: DeviceMessage) -> bool:
        """发送消息到已连接的ESP32（带长度前缀帧）"""
        with self._lock:
            if not self._client_socket:
                # 尝试重连
                if self._reconnect_attempts < self._max_reconnect_attempts:
                    logger.info(f"无客户端连接，等待新连接 ({self._reconnect_attempts + 1}/{self._max_reconnect_attempts})")
                    self._reconnect_attempts += 1
                    time.sleep(self._reconnect_delay)
                return False
            
            try:
                payload = json.dumps({
                    "type": msg.msg_type,
                    "data": msg.data,
                    "ts": msg.timestamp
                })
                frame = f"LEN:{len(payload)}\n{payload}\n"
                self._client_socket.sendall(frame.encode('utf-8'))
                self._reconnect_attempts = 0  # 发送成功，重置重连计数
                return True
                
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                self._client_socket = None
                self._client_addr = None
                self._connected = False
                # 尝试重连
                if self._reconnect_attempts < self._max_reconnect_attempts:
                    logger.info(f"发送失败，等待新连接 ({self._reconnect_attempts + 1}/{self._max_reconnect_attempts})")
                    self._reconnect_attempts += 1
                    time.sleep(self._reconnect_delay)
                return False
    

    def _send_queue_worker(self):
        """后台worker：从队列取消息并同步发送"""
        while self._running:
            try:
                msg = self._send_queue.get(timeout=0.5)
                self._flush_send(msg)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"发送worker错误: {e}")
                time.sleep(0.1)
    
    def _keepalive_loop(self):
        """Keep-Alive心跳：定期发送ping，超时无pong则断连"""
        while self._running:
            time.sleep(KEEPALIVE_INTERVAL)
            if not self._running or not self._connected:
                break
            
            now = time.time()
            # 检查pong超时
            if self._last_pong_time > 0 and (now - self._last_pong_time) > KEEPALIVE_TIMEOUT:
                logger.warning(f"Keep-Alive超时({KEEPALIVE_TIMEOUT}s无pong)，断开连接")
                with self._lock:
                    if self._client_socket:
                        try: self._client_socket.close()
                        except Exception: pass
                        self._client_socket = None
                    self._connected = False
                break
            
            # 发送ping
            try:
                ping_msg = DeviceMessage(msg_type="ping", data={}, timestamp=time.time())
                self._flush_send(ping_msg)
                self._ping_pending = True
            except Exception as e:
                logger.warning(f"Keep-Alive ping失败: {e}")

    def _read_loop(self):
        buffer = ""
        expected_len = None
        payload_buf = ""
        
        while self._running:
            with self._lock:
                client = self._client_socket
            if not client:
                break
            
            try:
                data = client.recv(4096).decode('utf-8')
                if not data:
                    logger.info("ESP32 连接已断开")
                    with self._lock:
                        self._client_socket = None
                        self._client_addr = None
                    self._connected = False
                    break
                
                buffer += data
                
                while buffer:
                    if expected_len is not None:
                        # Payload模式：直接按字节切片，不依赖换行符
                        if len(buffer) >= expected_len:
                            payload = buffer[:expected_len]
                            buffer = buffer[expected_len:]
                            self._process_received(payload)
                            expected_len = None
                            # 跳过紧跟的换行符（如果有）
                            if buffer.startswith('\n'):
                                buffer = buffer[1:]
                        else:
                            break  # 数据不足，等待更多
                    else:
                        # 长度头模式：按换行符读取LEN行
                        nl_pos = buffer.find('\n')
                        if nl_pos == -1:
                            break  # 未收到完整行
                        line = buffer[:nl_pos]
                        buffer = buffer[nl_pos + 1:]
                        
                        if line.startswith("LEN:"):
                            try:
                                expected_len = int(line[4:])
                            except ValueError:
                                logger.warning(f"Invalid LEN line: {line}")
                        elif line.strip():
                            self._process_received(line.strip())
                        
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"读取数据错误: {e}")
                with self._lock:
                    self._client_socket = None
                    self._client_addr = None
                self._connected = False
                break
    
    def _process_received(self, data: str):
        """处理接收到的数据（含pong心跳响应处理）"""
        try:
            msg_data = json.loads(data)
            msg_type = msg_data.get("type", "unknown")
            
            # 处理pong心跳响应
            if msg_type == "pong":
                self._last_pong_time = time.time()
                self._ping_pending = False
                return  # pong不传递给上层回调
            
            # [Phase 2] 崩溃遥测：记录并转发crash_report
            if msg_type == "crash_report":
                crash_data = msg_data.get("data", {})
                logger.critical(
                    f"[Crash] ESP32报告崩溃! "
                    f"reason={crash_data.get('reason', '?')}, "
                    f"count={crash_data.get('count', '?')}, "
                    f"stack={crash_data.get('stack', 'N/A')[:200]}"
                )
                # 仍传递给上层回调，让tray_app显示崩溃计数
            
            msg = DeviceMessage(
                msg_type=msg_type,
                data=msg_data.get("data", {}),
                timestamp=msg_data.get("ts", time.time())
            )
            
            if self._message_callback:
                self._message_callback(msg)
                
        except json.JSONDecodeError:
            logger.warning(f"收到无效JSON: {data}")


def create_communication(config: dict) -> CommunicationBase:
    """工厂函数：根据配置创建通信实例"""
    mode = config.get("mode", "wifi")
    
    if mode == "serial":
        return SerialCommunication(config)
    else:
        return WiFiCommunication(config)
