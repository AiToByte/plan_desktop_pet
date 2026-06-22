"""
通信模块Mock对象
模拟串口和WiFi通信，无需真实硬件
"""
import json
import time
from typing import Optional, List, Callable, Any
from queue import Queue


class MockSerial:
    """模拟pyserial串口对象"""
    
    def __init__(self, port: str = "COM99", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.is_open = True
        self._read_buffer = Queue()
        self._write_log: List[bytes] = []
        self._in_waiting = 0
    
    def write(self, data: bytes) -> int:
        """记录写入数据"""
        self._write_log.append(data)
        return len(data)
    
    def read(self, size: int = 1) -> bytes:
        """从mock缓冲区读取"""
        if self._read_buffer.empty():
            return b""
        return self._read_buffer.get_nowait()
    
    def readline(self) -> bytes:
        """读取一行"""
        if self._read_buffer.empty():
            return b""
        return self._read_buffer.get_nowait()
    
    def inject_data(self, data: bytes):
        """测试用：注入数据到读缓冲区"""
        self._read_buffer.put(data)
        self._in_waiting = len(data)
    
    def inject_json(self, obj: dict):
        """测试用：注入JSON数据（带LEN帧）"""
        json_bytes = json.dumps(obj).encode('utf-8')
        # 模拟LEN帧协议: 2字节长度 + JSON
        frame = len(json_bytes).to_bytes(2, 'little') + json_bytes
        self.inject_data(frame)
    
    @property
    def in_waiting(self) -> int:
        return self._in_waiting
    
    def close(self):
        self.is_open = False
    
    def reset_input_buffer(self):
        while not self._read_buffer.empty():
            self._read_buffer.get_nowait()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


class MockCommunication:
    """模拟CommunicationBase接口"""
    
    def __init__(self):
        self._connected = False
        self._callback: Optional[Callable] = None
        self._sent_messages: List[Any] = []
        self._running = False
    
    def set_message_callback(self, callback: Callable):
        self._callback = callback
    
    def connect(self) -> bool:
        self._connected = True
        return True
    
    def disconnect(self):
        self._connected = False
    
    def send_message(self, msg) -> bool:
        if not self._connected:
            return False
        self._sent_messages.append(msg)
        return True
    
    def is_connected(self) -> bool:
        return self._connected
    
    def simulate_receive(self, msg_dict: dict):
        """测试用：模拟接收到消息"""
        if self._callback:
            # 构造DeviceMessage-like对象
            from types import SimpleNamespace
            msg = SimpleNamespace(
                msg_type=msg_dict.get("type", "unknown"),
                data=msg_dict.get("data", {}),
                timestamp=msg_dict.get("ts", time.time()),
            )
            self._callback(msg)
    
    def get_sent_messages(self) -> list:
        return self._sent_messages
    
    def clear_sent(self):
        self._sent_messages.clear()


class MockSocket:
    """模拟socket对象"""
    
    def __init__(self):
        self._sent: List[bytes] = []
        self._recv_queue = Queue()
        self.is_closed = False
    
    def sendall(self, data: bytes):
        self._sent.append(data)
    
    def send(self, data: bytes) -> int:
        self._sent.append(data)
        return len(data)
    
    def recv(self, bufsize: int) -> bytes:
        if self._recv_queue.empty():
            return b""
        return self._recv_queue.get_nowait()
    
    def inject_response(self, data: bytes):
        self._recv_queue.put(data)
    
    def close(self):
        self.is_closed = True
    
    def settimeout(self, timeout):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
