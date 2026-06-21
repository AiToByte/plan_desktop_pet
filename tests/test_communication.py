"""
Communication模块单元测试
基于实际源码接口的mock测试
"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_helpers  # noqa: F401 - mock psutil/serial/requests

sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

import unittest
from unittest.mock import patch, MagicMock, call
from modules.communication import (
    DeviceMessage, CommunicationBase, SerialCommunication, WiFiCommunication,
    DEFAULT_SERIAL_PORT, DEFAULT_SERIAL_BAUD, DEFAULT_WIFI_HOST, DEFAULT_WIFI_PORT,
    DEFAULT_RECONNECT_ATTEMPTS, DEFAULT_RECONNECT_DELAY
)


class TestDeviceMessage(unittest.TestCase):
    """测试DeviceMessage数据类"""

    def test_creation(self):
        """测试创建消息"""
        msg = DeviceMessage(
            msg_type="status",
            data={"cpu": 50.0},
            timestamp=1000.0
        )
        self.assertEqual(msg.msg_type, "status")
        self.assertEqual(msg.data["cpu"], 50.0)
        self.assertEqual(msg.timestamp, 1000.0)

    def test_creation_defaults(self):
        """测试默认值"""
        msg = DeviceMessage(msg_type="test")
        self.assertEqual(msg.msg_type, "test")
        self.assertEqual(msg.data, {})

    def test_attributes(self):
        """测试消息属性访问"""
        msg = DeviceMessage(
            msg_type="cmd",
            data={"action": "blink"},
            timestamp=1234.5
        )
        self.assertEqual(msg.msg_type, "cmd")
        self.assertEqual(msg.data["action"], "blink")
        self.assertEqual(msg.timestamp, 1234.5)


class TestCommunicationBase(unittest.TestCase):
    """测试通信基类"""

    def test_set_message_callback(self):
        """测试设置消息回调"""
        comm = CommunicationBase()
        callback = MagicMock()
        comm.set_message_callback(callback)
        self.assertEqual(comm._message_callback, callback)

    def test_is_connected_default(self):
        """测试默认未连接"""
        comm = CommunicationBase()
        self.assertFalse(comm.is_connected())

    def test_process_received_valid_json(self):
        """测试处理有效JSON数据"""
        comm = CommunicationBase()
        callback = MagicMock()
        comm.set_message_callback(callback)
        
        msg_data = {"type": "sensor", "data": {"temp": 25.0}, "timestamp": 1000.0}
        comm._process_received(json.dumps(msg_data))
        callback.assert_called_once()

    def test_process_received_invalid_json(self):
        """测试处理无效JSON"""
        comm = CommunicationBase()
        callback = MagicMock()
        comm.set_message_callback(callback)
        
        comm._process_received("not json")
        callback.assert_not_called()


class TestDefaultConstants(unittest.TestCase):
    """测试默认常量"""

    def test_serial_defaults(self):
        """测试串口默认值"""
        self.assertEqual(DEFAULT_SERIAL_PORT, "COM3")
        self.assertEqual(DEFAULT_SERIAL_BAUD, 115200)

    def test_wifi_defaults(self):
        """测试WiFi默认值"""
        self.assertEqual(DEFAULT_WIFI_HOST, "0.0.0.0")
        self.assertEqual(DEFAULT_WIFI_PORT, 19876)

    def test_reconnect_defaults(self):
        """测试重连默认值"""
        self.assertEqual(DEFAULT_RECONNECT_ATTEMPTS, 3)
        self.assertEqual(DEFAULT_RECONNECT_DELAY, 2)


class TestSerialCommunication(unittest.TestCase):
    """测试串口通信"""

    @patch('modules.communication.serial')
    def test_init_defaults(self, mock_serial):
        """测试默认初始化"""
        comm = SerialCommunication({})
        self.assertEqual(comm.port, "COM3")
        self.assertEqual(comm.baudrate, 115200)

    @patch('modules.communication.serial')
    def test_init_custom_config(self, mock_serial):
        """测试自定义配置"""
        comm = SerialCommunication({
            "serial_port": "COM5",
            "serial_baud": 9600
        })
        self.assertEqual(comm.port, "COM5")
        self.assertEqual(comm.baudrate, 9600)

    @patch('modules.communication.serial')
    def test_is_connected_default(self, mock_serial):
        """测试默认未连接"""
        comm = SerialCommunication({})
        self.assertFalse(comm.is_connected())

    @patch('modules.communication.serial')
    def test_disconnect_when_not_connected(self, mock_serial):
        """测试断开未连接状态"""
        comm = SerialCommunication({})
        comm.disconnect()
        self.assertFalse(comm.is_connected())


class TestWiFiCommunication(unittest.TestCase):
    """测试WiFi通信"""

    def test_init_defaults(self):
        """测试默认初始化"""
        comm = WiFiCommunication({})
        self.assertEqual(comm.host, "0.0.0.0")
        self.assertEqual(comm.port, 19876)

    def test_init_custom_config(self):
        """测试自定义配置"""
        comm = WiFiCommunication({
            "wifi_host": "192.168.1.100",
            "wifi_port": 8080
        })
        self.assertEqual(comm.host, "192.168.1.100")
        self.assertEqual(comm.port, 8080)

    def test_is_connected_default(self):
        """测试默认未连接"""
        comm = WiFiCommunication({})
        self.assertFalse(comm.is_connected())

    def test_disconnect_when_not_connected(self):
        """测试断开未连接状态"""
        comm = WiFiCommunication({})
        comm.disconnect()
        self.assertFalse(comm.is_connected())


class TestCommunicationCallback(unittest.TestCase):
    """测试通信回调机制"""

    def test_message_callback_set(self):
        """测试回调设置"""
        comm = CommunicationBase()
        cb = MagicMock()
        comm.set_message_callback(cb)
        self.assertEqual(comm._message_callback, cb)

    def test_message_callback_none_default(self):
        """测试默认无回调"""
        comm = CommunicationBase()
        self.assertIsNone(comm._message_callback)


class TestCommunicationReconnect(unittest.TestCase):
    """测试重连机制"""

    @patch('modules.communication.serial')
    def test_reconnect_attempts(self, mock_serial):
        """测试重连尝试次数"""
        comm = SerialCommunication({})
        self.assertEqual(comm._reconnect_attempts, 0)
        self.assertEqual(comm._max_reconnect_attempts, DEFAULT_RECONNECT_ATTEMPTS)

    def test_wifi_reconnect_attempts(self):
        """测试WiFi重连"""
        comm = WiFiCommunication({})
        self.assertEqual(comm._reconnect_attempts, 0)
        self.assertEqual(comm._max_reconnect_attempts, DEFAULT_RECONNECT_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
