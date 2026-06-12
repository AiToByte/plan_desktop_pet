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
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeviceMessage:
    """设备消息"""
    msg_type: str       # 消息类型: status, token, weather, animation
    data: dict          # 消息数据
    timestamp: float    # 时间戳


class CommunicationBase:
    """通信基类"""
    
    def __init__(self):
        self._connected = False
        self._message_callback: Optional[Callable] = None
        self._running = False
    
    def set_message_callback(self, callback: Callable):
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


class SerialCommunication(CommunicationBase):
    """串口通信"""
    
    def __init__(self, config: dict):
        super().__init__()
        self.port = config.get("serial_port", "COM3")
        self.baudrate = config.get("serial_baud", 115200)
        self._serial: Optional[serial.Serial] = None
        self._read_thread: Optional[threading.Thread] = None
    
    def connect(self) -> bool:
        """连接串口"""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1
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
            return False
        
        try:
            payload = json.dumps({
                "type": msg.msg_type,
                "data": msg.data,
                "ts": msg.timestamp
            })
            frame = f"LEN:{len(payload)}\n{payload}\n"
            self._serial.write(frame.encode('utf-8'))
            return True
            
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
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
                    time.sleep(0.01)
                    
            except Exception as e:
                logger.error(f"读取串口数据错误: {e}")
                time.sleep(0.1)
    
    def _process_received(self, data: str):
        """处理接收到的数据"""
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


class WiFiCommunication(CommunicationBase):
    """WiFi通信（PC端作为TCP Server，等待ESP32连接）"""
    
    def __init__(self, config: dict):
        super().__init__()
        self.host = config.get("wifi_host", "0.0.0.0")
        self.port = config.get("wifi_port", 19876)
        self.retry_interval = config.get("retry_interval", 5)
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._client_addr: Optional[tuple] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._read_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """启动TCP Server，等待ESP32连接"""
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.settimeout(1)
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(1)
            
            self._connected = True
            self._running = True
            
            # 启动接受连接线程
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()
            
            logger.info(f"TCP Server 已启动，监听 {self.host}:{self.port}，等待ESP32连接...")
            return True
            
        except Exception as e:
            logger.error(f"TCP Server 启动失败: {e}")
            return False
    
    def _accept_loop(self):
        """接受客户端连接循环"""
        while self._running:
            try:
                client_socket, client_addr = self._server_socket.accept()
                client_socket.settimeout(5)
                
                with self._lock:
                    # 如果已有连接，关闭旧连接
                    if self._client_socket:
                        try:
                            self._client_socket.close()
                        except:
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
    
    def disconnect(self):
        """断开连接并关闭服务器"""
        self._running = False
        self._connected = False
        
        with self._lock:
            if self._client_socket:
                try:
                    self._client_socket.close()
                except:
                    pass
                self._client_socket = None
                self._client_addr = None
            
            if self._server_socket:
                try:
                    self._server_socket.close()
                except:
                    pass
                self._server_socket = None
        
        logger.info("TCP Server 已关闭")
    
    def send_message(self, msg: DeviceMessage) -> bool:
        """发送消息到已连接的ESP32（带长度前缀帧）"""
        with self._lock:
            if not self._client_socket:
                return False
            
            try:
                payload = json.dumps({
                    "type": msg.msg_type,
                    "data": msg.data,
                    "ts": msg.timestamp
                })
                frame = f"LEN:{len(payload)}\n{payload}\n"
                self._client_socket.sendall(frame.encode('utf-8'))
                return True
                
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                self._client_socket = None
                self._client_addr = None
                self._connected = False
                return False
    
    def _read_loop(self):
        """读取客户端数据循环（支持长度前缀帧 + 旧格式fallback）"""
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
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    
                    if expected_len is not None:
                        payload_buf += line
                        if len(payload_buf) >= expected_len:
                            self._process_received(payload_buf[:expected_len])
                            expected_len = None
                            payload_buf = ""
                    elif line.startswith("LEN:"):
                        try:
                            expected_len = int(line[4:])
                            payload_buf = ""
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
        """处理接收到的数据"""
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


def create_communication(config: dict) -> CommunicationBase:
    """工厂函数：根据配置创建通信实例"""
    mode = config.get("mode", "wifi")
    
    if mode == "serial":
        return SerialCommunication(config)
    else:
        return WiFiCommunication(config)
