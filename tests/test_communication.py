"""
通信模块测试
覆盖: DeviceMessage、WiFi通信、串口通信、工厂函数
注意: DeviceMessage是纯dataclass，序列化由通信层内部json处理
"""
import json
import time
import socket
import threading
from queue import Queue, Empty
from unittest.mock import MagicMock, patch, call

import pytest

from modules.communication import (
    DeviceMessage,
    CommunicationBase,
    SerialCommunication,
    WiFiCommunication,
    create_communication,
    DEFAULT_WIFI_HOST,
    DEFAULT_WIFI_PORT,
    DEFAULT_SERIAL_PORT,
    DEFAULT_SERIAL_BAUD,
    KEEPALIVE_INTERVAL,
    KEEPALIVE_TIMEOUT,
    SEND_QUEUE_MAXSIZE,
)


# ============================================================
# DeviceMessage 测试
# ============================================================
class TestDeviceMessage:
    """DeviceMessage 纯数据类测试（无序列化方法）"""

    def test_default_fields(self):
        """默认字段正确：空data, 自动timestamp"""
        msg = DeviceMessage(msg_type="status")
        assert msg.msg_type == "status"
        assert msg.data == {}
        assert isinstance(msg.timestamp, float)
        assert msg.timestamp > 0

    def test_custom_fields(self):
        """自定义字段"""
        msg = DeviceMessage(msg_type="token", data={"count": 100}, timestamp=123.456)
        assert msg.msg_type == "token"
        assert msg.data == {"count": 100}
        assert msg.timestamp == 123.456

    def test_dataclass_equality(self):
        """同类同值相等"""
        msg1 = DeviceMessage(msg_type="ping", data={}, timestamp=1.0)
        msg2 = DeviceMessage(msg_type="ping", data={}, timestamp=1.0)
        assert msg1 == msg2

    def test_dataclass_inequality(self):
        """不同类型不等"""
        msg1 = DeviceMessage(msg_type="ping", data={}, timestamp=1.0)
        msg2 = DeviceMessage(msg_type="pong", data={}, timestamp=1.0)
        assert msg1 != msg2

    def test_data_mutable(self):
        """data字典可修改"""
        msg = DeviceMessage(msg_type="test")
        msg.data["key"] = "value"
        assert msg.data["key"] == "value"


# ============================================================
# CommunicationBase 序列化测试（通过子类WiFiCommunication测）
# ============================================================
class TestSerialization:
    """测试通信层内部JSON序列化/反序列化（dict↔DeviceMessage）"""

    def _make_comm(self):
        config = {"wifi_host": "127.0.0.1", "wifi_port": 19876}
        return WiFiCommunication(config)

    def test_process_received_normal(self):
        """正常JSON→DeviceMessage→回调"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)

        payload = json.dumps({"type": "status", "data": {"state": "idle"}, "ts": 123.0})
        comm._process_received(payload)

        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert isinstance(msg, DeviceMessage)
        assert msg.msg_type == "status"
        assert msg.data == {"state": "idle"}
        assert msg.timestamp == 123.0

    def test_process_received_pong_no_callback(self):
        """pong消息不触发回调"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)
        comm._last_pong_time = 0
        comm._ping_pending = True

        payload = json.dumps({"type": "pong", "data": {}, "ts": time.time()})
        comm._process_received(payload)

        assert comm._ping_pending is False
        assert comm._last_pong_time > 0
        callback.assert_not_called()

    def test_process_received_crash_report(self):
        """crash_report触发回调（含logger.critical日志）"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)

        payload = json.dumps({
            "type": "crash_report",
            "data": {"reason": "wdt_reset", "count": 3, "stack": "backtrace..."},
            "ts": time.time(),
        })
        comm._process_received(payload)

        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg.msg_type == "crash_report"
        assert msg.data["reason"] == "wdt_reset"

    def test_process_received_invalid_json(self):
        """无效JSON不崩溃、不触发回调"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)
        comm._process_received("not json {{{")
        callback.assert_not_called()

    def test_process_received_missing_fields(self):
        """缺字段JSON使用默认值"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)

        comm._process_received('{"type": "ping"}')
        msg = callback.call_args[0][0]
        assert msg.msg_type == "ping"
        assert msg.data == {}

    def test_process_received_unknown_type(self):
        """未知type正常传递"""
        comm = self._make_comm()
        callback = MagicMock()
        comm.set_message_callback(callback)

        comm._process_received('{"type": "custom_event", "data": {"x": 1}}')
        msg = callback.call_args[0][0]
        assert msg.msg_type == "custom_event"
        assert msg.data == {"x": 1}

    def test_no_callback_no_crash(self):
        """无回调时不崩溃"""
        comm = self._make_comm()
        comm._process_received('{"type": "status", "data": {}}')
        # 不应抛异常


# ============================================================
# WiFi通信 测试
# ============================================================
class TestWiFiCommunication:
    """WiFiCommunication 测试（mock socket）"""

    def _make_wifi(self, **overrides):
        config = {"wifi_host": "127.0.0.1", "wifi_port": 19876, **overrides}
        return WiFiCommunication(config)

    def test_init_defaults(self):
        """初始化默认值"""
        comm = self._make_wifi()
        assert comm.host == "127.0.0.1"
        assert comm.port == 19876
        assert not comm.is_connected()
        assert comm._running is False

    def test_connect_success(self):
        """connect创建TCP server并返回True"""
        comm = self._make_wifi()
        with patch("modules.communication.socket.socket") as mock_sock_cls:
            mock_server = MagicMock()
            mock_server.accept.side_effect = socket.timeout
            mock_sock_cls.return_value = mock_server

            result = comm.connect()
            assert result is True
            assert comm._running is True
            mock_server.bind.assert_called_once_with(("127.0.0.1", 19876))
            mock_server.listen.assert_called_once_with(1)
            mock_server.settimeout.assert_called()

            comm.disconnect()

    def test_connect_failure(self):
        """connect异常返回False"""
        comm = self._make_wifi()
        with patch("modules.communication.socket.socket") as mock_sock_cls:
            mock_server = MagicMock()
            mock_server.bind.side_effect = OSError("Address in use")
            mock_sock_cls.return_value = mock_server

            result = comm.connect()
            assert result is False
            assert comm._running is False

    def test_disconnect_cleanup(self):
        """disconnect关闭所有资源"""
        comm = self._make_wifi()
        with patch("modules.communication.socket.socket") as mock_sock_cls:
            mock_server = MagicMock()
            mock_server.accept.side_effect = socket.timeout
            mock_sock_cls.return_value = mock_server

            comm.connect()
            mock_client = MagicMock()
            comm._client_socket = mock_client
            comm._connected = True

            comm.disconnect()
            assert comm._running is False
            assert comm._connected is False
            assert comm._client_socket is None

    def test_send_when_disconnected(self):
        """未连接时发送返回False"""
        comm = self._make_wifi()
        msg = DeviceMessage(msg_type="test")
        assert comm.send_message(msg) is False

    def test_send_queues_message(self):
        """已连接时消息入队"""
        comm = self._make_wifi()
        comm._connected = True
        comm._running = True

        msg = DeviceMessage(msg_type="status", data={"state": "working"})
        assert comm.send_message(msg) is True
        assert not comm._send_queue.empty()

    def test_send_queue_full_returns_false(self):
        """队列满时丢弃返回False"""
        comm = self._make_wifi()
        comm._connected = True
        comm._running = True

        for _ in range(SEND_QUEUE_MAXSIZE):
            comm._send_queue.put_nowait(DeviceMessage(msg_type="fill"))

        msg = DeviceMessage(msg_type="overflow")
        assert comm.send_message(msg) is False

    def test_resolve_mdns_success(self):
        """mDNS解析成功"""
        with patch("modules.communication.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 80))
            ]
            ip = WiFiCommunication.resolve_mdns("deskpet.local")
            assert ip == "192.168.1.100"

    def test_resolve_mdns_failure(self):
        """mDNS解析失败返回None"""
        with patch("modules.communication.socket.getaddrinfo", side_effect=socket.gaierror):
            ip = WiFiCommunication.resolve_mdns("nonexistent.local")
            assert ip is None

    def test_get_local_ip_fallback(self):
        """无网络时返回127.0.0.1"""
        comm = self._make_wifi()
        with patch("modules.communication.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = OSError("No network")
            mock_sock_cls.return_value = mock_sock
            assert comm._get_local_ip() == "127.0.0.1"

    def test_callback_registration(self):
        """回调注册/替换"""
        comm = self._make_wifi()
        cb1, cb2 = MagicMock(), MagicMock()
        comm.set_message_callback(cb1)
        assert comm._message_callback is cb1
        comm.set_message_callback(cb2)
        assert comm._message_callback is cb2

    def test_default_constants(self):
        """常量合理"""
        assert KEEPALIVE_INTERVAL > 0
        assert KEEPALIVE_TIMEOUT > KEEPALIVE_INTERVAL
        assert SEND_QUEUE_MAXSIZE > 0


# ============================================================
# 串口通信 测试
# ============================================================
class TestSerialCommunication:
    """SerialCommunication 测试（mock serial）"""

    def _make_serial(self, **overrides):
        config = {"serial_port": "COM99", "serial_baud": 115200, **overrides}
        return SerialCommunication(config)

    def test_init_defaults(self):
        """初始化默认值"""
        comm = self._make_serial()
        assert comm.port == "COM99"
        assert comm.baudrate == 115200
        assert not comm.is_connected()

    @patch("modules.communication.serial.Serial")
    def test_connect_success(self, mock_serial_cls):
        """串口连接成功"""
        mock_ser = MagicMock()
        mock_ser.is_open = True
        # readline 返回空bytes让read_loop快速退出
        mock_ser.readline.return_value = b""
        mock_serial_cls.return_value = mock_ser

        comm = self._make_serial()
        result = comm.connect()
        assert result is True
        assert comm.is_connected()
        mock_serial_cls.assert_called_once_with(
            port="COM99", baudrate=115200, timeout=1
        )

        # 等read_loop线程退出
        time.sleep(0.1)
        comm.disconnect()

    @patch("modules.communication.serial.Serial")
    def test_connect_failure(self, mock_serial_cls):
        """串口连接失败"""
        mock_serial_cls.side_effect = Exception("Port not found")
        comm = self._make_serial()
        result = comm.connect()
        assert result is False
        assert not comm.is_connected()

    @patch("modules.communication.serial.Serial")
    def test_disconnect_closes_port(self, mock_serial_cls):
        """disconnect关闭串口"""
        mock_ser = MagicMock()
        mock_ser.readline.return_value = b""
        mock_serial_cls.return_value = mock_ser

        comm = self._make_serial()
        comm.connect()
        time.sleep(0.05)
        comm.disconnect()
        assert not comm.is_connected()
        mock_ser.close.assert_called()

    @patch("modules.communication.serial.Serial")
    def test_send_message_success(self, mock_serial_cls):
        """发送消息成功"""
        mock_ser = MagicMock()
        mock_ser.readline.return_value = b""
        mock_serial_cls.return_value = mock_ser

        comm = self._make_serial()
        comm.connect()
        time.sleep(0.05)

        msg = DeviceMessage(msg_type="status", data={"state": "idle"})
        result = comm.send_message(msg)
        assert result is True
        assert mock_ser.write.called

        comm.disconnect()

    def test_send_when_disconnected(self):
        """未连接时发送失败"""
        comm = self._make_serial()
        msg = DeviceMessage(msg_type="test")
        assert comm.send_message(msg) is False

    @patch("modules.communication.serial.Serial")
    def test_send_write_failure(self, mock_serial_cls):
        """写入异常返回False"""
        mock_ser = MagicMock()
        mock_ser.readline.return_value = b""
        mock_ser.write.side_effect = Exception("Write error")
        mock_serial_cls.return_value = mock_ser

        comm = self._make_serial()
        comm.connect()
        time.sleep(0.05)

        msg = DeviceMessage(msg_type="test")
        assert comm.send_message(msg) is False
        comm.disconnect()

    @patch("modules.communication.serial.Serial")
    def test_send_large_payload_uses_len_header(self, mock_serial_cls):
        """大payload使用LEN帧协议"""
        mock_ser = MagicMock()
        mock_ser.readline.return_value = b""
        mock_serial_cls.return_value = mock_ser

        comm = self._make_serial()
        comm.connect()
        time.sleep(0.05)

        big_data = {"payload": "x" * 500}
        msg = DeviceMessage(msg_type="big", data=big_data)
        result = comm.send_message(msg)
        assert result is True
        # 至少调用了write
        assert mock_ser.write.call_count >= 1
        comm.disconnect()


# ============================================================
# 工厂函数 测试
# ============================================================
class TestCreateCommunication:
    """create_communication 工厂函数"""

    def test_default_wifi(self):
        """默认模式→WiFi"""
        comm = create_communication({"wifi_port": 19876})
        assert isinstance(comm, WiFiCommunication)

    def test_explicit_wifi(self):
        """显式wifi→WiFi"""
        comm = create_communication({"mode": "wifi", "wifi_port": 19876})
        assert isinstance(comm, WiFiCommunication)

    def test_serial_mode(self):
        """serial→SerialCommunication"""
        comm = create_communication({"mode": "serial", "serial_port": "COM5"})
        assert isinstance(comm, SerialCommunication)

    def test_unknown_mode_defaults_wifi(self):
        """未知模式→WiFi"""
        comm = create_communication({"mode": "unknown"})
        assert isinstance(comm, WiFiCommunication)


# ============================================================
# Mock Helper 验证
# ============================================================
class TestMockHelpers:
    """验证conftest提供的mock helpers正确实现接口"""

    def test_mock_communication_lifecycle(self, mock_communication):
        """MockCommunication完整生命周期"""
        assert not mock_communication.is_connected()
        mock_communication.connect()
        assert mock_communication.is_connected()

        msg = DeviceMessage(msg_type="test", data={"x": 1})
        assert mock_communication.send_message(msg) is True
        assert len(mock_communication.get_sent_messages()) == 1
        assert mock_communication.get_sent_messages()[0].msg_type == "test"

        mock_communication.disconnect()
        assert not mock_communication.is_connected()

    def test_mock_communication_callback(self, mock_communication):
        """simulate_receive触发回调"""
        callback = MagicMock()
        mock_communication.set_message_callback(callback)
        mock_communication.connect()
        mock_communication.simulate_receive({"type": "status", "data": {"state": "idle"}})
        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg.msg_type == "status"

    def test_mock_serial_interface(self, mock_serial):
        """MockSerial基本接口"""
        assert mock_serial.is_open
        mock_serial.write(b"hello")
        assert len(mock_serial._write_log) == 1
        mock_serial.close()
        assert not mock_serial.is_open

    def test_mock_socket_interface(self, mock_socket):
        """MockSocket基本接口"""
        mock_socket.sendall(b"data")
        assert len(mock_socket._sent) == 1
        result = mock_socket.recv(1024)
        assert result == b""

# ============================================================
# 补充测试：communication.py 覆盖率提升 (132 miss lines)
# 覆盖: abstract基类/串口重连/串口读循环/WiFi线程/WiFi心跳/WiFi读循环
# ============================================================


class TestCommunicationBaseAbstract:
    """覆盖 CommunicationBase 抽象方法 (lines 69, 72, 75)"""

    def test_connect_raises(self):
        class Bare(CommunicationBase):
            def disconnect(self): pass
            def send_message(self, msg): return True
        with pytest.raises(NotImplementedError):
            Bare().connect()

    def test_disconnect_raises(self):
        class Bare(CommunicationBase):
            def connect(self): return True
            def send_message(self, msg): return True
        with pytest.raises(NotImplementedError):
            Bare().disconnect()

    def test_send_message_raises(self):
        class Bare(CommunicationBase):
            def connect(self): return True
            def disconnect(self): pass
        with pytest.raises(NotImplementedError):
            Bare().send_message(DeviceMessage(msg_type="test"))


class TestCommunicationBaseProcessReceived:
    """覆盖 CommunicationBase._process_received (lines 82-92)"""

    def _make_comm(self):
        class Bare(CommunicationBase):
            def connect(self): return True
            def disconnect(self): pass
            def send_message(self, msg): return True
        return Bare()

    def test_valid_json_with_callback(self):
        comm = self._make_comm()
        cb = MagicMock()
        comm.set_message_callback(cb)
        comm._process_received('{"type":"status","data":{"x":1},"ts":999.0}')
        cb.assert_called_once()
        msg = cb.call_args[0][0]
        assert msg.msg_type == "status"
        assert msg.data == {"x": 1}

    def test_valid_json_no_callback(self):
        comm = self._make_comm()
        comm._process_received('{"type":"ping","data":{},"ts":1.0}')

    def test_invalid_json(self):
        comm = self._make_comm()
        comm._process_received('not json')


class TestSerialReconnect:
    """覆盖串口重连路径 (lines 142, 169, 173-174)"""

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_reconnect_success_resets_attempts(self, mock_thread, mock_serial_cls):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_cls.return_value = mock_serial

        comm = SerialCommunication({"serial_port": "COM99", "serial_baud": 115200})
        comm._reconnect_attempts = 0

        msg = DeviceMessage(msg_type="test", data={}, timestamp=1.0)
        result = comm.send_message(msg)
        assert result is True
        assert comm._reconnect_attempts == 0

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_write_exception_retry_success(self, mock_thread_cls, mock_serial_cls):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.write.side_effect = [Exception("write fail"), None]
        mock_serial_cls.return_value = mock_serial

        comm = SerialCommunication({"serial_port": "COM99", "serial_baud": 115200})
        comm.connect()
        comm._reconnect_attempts = 0

        msg = DeviceMessage(msg_type="test", data={}, timestamp=1.0)
        result = comm.send_message(msg)
        assert result is True

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_write_exception_reconnect_fail(self, mock_thread_cls, mock_serial_cls):
        mock_serial_ok = MagicMock()
        mock_serial_ok.is_open = True
        mock_serial_ok.write.side_effect = Exception("write fail")
        mock_serial_cls.return_value = mock_serial_ok

        comm = SerialCommunication({"serial_port": "COM99", "serial_baud": 115200})
        comm.connect()
        comm._reconnect_attempts = 0

        mock_serial_cls.side_effect = Exception("port gone")

        msg = DeviceMessage(msg_type="test", data={}, timestamp=1.0)
        result = comm.send_message(msg)
        assert result is False
        assert comm._reconnect_attempts == 1


class TestSerialReadLoop:
    """覆盖串口 _read_loop (lines 188-207, 211-215)"""

    def _setup(self, mock_serial_cls, mock_thread_cls):
        from unittest.mock import PropertyMock
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_cls.return_value = mock_serial
        comm = SerialCommunication({"serial_port": "COM99", "serial_baud": 115200})
        comm.connect()
        comm._running = True
        comm._connected = True
        return comm, mock_serial, PropertyMock

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_len_header_and_payload(self, mock_thread_cls, mock_serial_cls):
        comm, mock_serial, PropertyMock = self._setup(mock_serial_cls, mock_thread_cls)

        payload = '{"type":"test","data":{}}'
        frame = f"LEN:{len(payload)}\n{payload}\n"
        buf = list(frame.encode('utf-8'))

        mock_serial.read = lambda size=1: bytes([buf.pop(0)]) if buf else b''
        type(mock_serial).in_waiting = PropertyMock(side_effect=lambda: len(buf))

        cb = MagicMock()
        comm.set_message_callback(cb)

        with patch('modules.communication.time.sleep') as mock_sleep:
            def stop_sleep(*a):
                if not buf:
                    comm._running = False
            mock_sleep.side_effect = stop_sleep
            comm._read_loop()

        cb.assert_called_once()
        assert cb.call_args[0][0].msg_type == "test"

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_legacy_json_line(self, mock_thread_cls, mock_serial_cls):
        comm, mock_serial, PropertyMock = self._setup(mock_serial_cls, mock_thread_cls)

        line = '{"type":"status","data":{"temp":25}}\n'
        buf = list(line.encode('utf-8'))

        mock_serial.read = lambda size=1: bytes([buf.pop(0)]) if buf else b''
        type(mock_serial).in_waiting = PropertyMock(side_effect=lambda: len(buf))

        cb = MagicMock()
        comm.set_message_callback(cb)

        with patch('modules.communication.time.sleep') as mock_sleep:
            def stop_sleep(*a):
                if not buf:
                    comm._running = False
            mock_sleep.side_effect = stop_sleep
            comm._read_loop()

        cb.assert_called_once()
        assert cb.call_args[0][0].msg_type == "status"

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_no_data_sleeps(self, mock_thread_cls, mock_serial_cls):
        comm, mock_serial, PropertyMock = self._setup(mock_serial_cls, mock_thread_cls)
        type(mock_serial).in_waiting = PropertyMock(return_value=0)

        with patch('modules.communication.time.sleep') as mock_sleep:
            mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)
            comm._read_loop()

        mock_sleep.assert_called()

    @patch('modules.communication.serial.Serial')
    @patch('modules.communication.threading.Thread')
    def test_read_exception_recovery(self, mock_thread_cls, mock_serial_cls):
        comm, mock_serial, PropertyMock = self._setup(mock_serial_cls, mock_thread_cls)
        type(mock_serial).in_waiting = PropertyMock(return_value=1)
        mock_serial.read.side_effect = Exception("serial error")

        with patch('modules.communication.time.sleep') as mock_sleep:
            mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)
            comm._read_loop()

        mock_sleep.assert_called()


class TestWiFiAcceptLoop:
    """覆盖 WiFi _accept_loop (lines 298-319, 323-326)"""

    @patch('modules.communication.threading.Thread')
    def test_accept_new_client(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        mock_thread_cls.return_value = mock_thread

        comm = WiFiCommunication({})
        comm._running = True
        comm._server_socket = MagicMock()
        comm._client_socket = None
        comm._read_thread = None

        mock_client = MagicMock()
        mock_addr = ("192.168.1.100", 12345)

        call_count = [0]
        def accept_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return (mock_client, mock_addr)
            comm._running = False
            raise socket.timeout

        comm._server_socket.accept.side_effect = accept_side_effect
        comm._accept_loop()

        assert comm._client_socket == mock_client
        assert comm._connected is True
        mock_client.settimeout.assert_called_once()

    @patch('modules.communication.threading.Thread')
    def test_accept_replace_old_client(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        mock_thread_cls.return_value = mock_thread

        comm = WiFiCommunication({})
        comm._running = True
        comm._server_socket = MagicMock()

        old_client = MagicMock()
        comm._client_socket = old_client
        comm._read_thread = MagicMock()
        comm._read_thread.is_alive.return_value = False

        mock_client = MagicMock()
        mock_addr = ("192.168.1.101", 12346)

        call_count = [0]
        def accept_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return (mock_client, mock_addr)
            comm._running = False
            raise socket.timeout

        comm._server_socket.accept.side_effect = accept_side_effect
        comm._accept_loop()

        old_client.close.assert_called_once()
        assert comm._client_socket == mock_client

    @patch('modules.communication.threading.Thread')
    def test_accept_old_thread_alive(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mock_thread_cls.return_value = mock_thread

        comm = WiFiCommunication({})
        comm._running = True
        comm._server_socket = MagicMock()
        comm._client_socket = None
        comm._read_thread = mock_thread

        mock_client = MagicMock()
        mock_addr = ("192.168.1.100", 12345)

        call_count = [0]
        def accept_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return (mock_client, mock_addr)
            comm._running = False
            raise socket.timeout

        comm._server_socket.accept.side_effect = accept_side_effect
        comm._accept_loop()

        mock_thread.join.assert_called_once()

    def test_accept_exception(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._server_socket = MagicMock()

        call_count = [0]
        def accept_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("accept failed")
            comm._running = False
            raise socket.timeout

        comm._server_socket.accept.side_effect = accept_side_effect

        with patch('modules.communication.time.sleep'):
            comm._accept_loop()


class TestWiFiUDPBroadcast:
    """覆盖 WiFi _udp_broadcast_loop (lines 355-356, 366-367)"""

    @patch('modules.communication.socket.socket')
    @patch('modules.communication.time.sleep')
    def test_sendto_exception(self, mock_sleep, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.sendto.side_effect = OSError("send failed")

        comm = WiFiCommunication({})
        comm._running = True
        comm._get_local_ip = MagicMock(return_value='192.168.1.100')

        mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)

        comm._udp_broadcast_loop()
        mock_sock.sendto.assert_called()

    @patch('modules.communication.socket.socket')
    @patch('modules.communication.time.sleep')
    def test_close_exception(self, mock_sleep, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.close.side_effect = OSError("close failed")

        comm = WiFiCommunication({})
        comm._running = True
        comm._get_local_ip = MagicMock(return_value='192.168.1.100')

        mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)

        comm._udp_broadcast_loop()
        mock_sock.close.assert_called()


class TestWiFiDisconnectExceptions:
    """覆盖 WiFi disconnect socket.close异常 (lines 379-380, 387-388)"""

    def test_client_close_exception(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True

        mock_client = MagicMock()
        mock_client.close.side_effect = OSError("close fail")
        comm._client_socket = mock_client
        comm._client_addr = ("192.168.1.1", 1234)

        mock_server = MagicMock()
        comm._server_socket = mock_server

        comm.disconnect()
        assert comm._client_socket is None
        assert comm._connected is False

    def test_server_close_exception(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        comm._client_socket = None

        mock_server = MagicMock()
        mock_server.close.side_effect = OSError("close fail")
        comm._server_socket = mock_server

        comm.disconnect()
        assert comm._server_socket is None


class TestWiFiSendQueueWorker:
    """覆盖 WiFi _send_queue_worker (lines 412, 415-417)"""

    def test_worker_flush_message(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._flush_send = MagicMock()

        msg = DeviceMessage(msg_type="test", data={}, timestamp=1.0)

        call_count = [0]
        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return msg
            comm._running = False
            raise Empty

        comm._send_queue.get = mock_get
        comm._send_queue_worker()
        comm._flush_send.assert_called_once_with(msg)

    def test_worker_exception_recovery(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._flush_send = MagicMock(side_effect=Exception("flush error"))

        msg = DeviceMessage(msg_type="test", data={}, timestamp=1.0)

        call_count = [0]
        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return msg
            comm._running = False
            raise Empty

        comm._send_queue.get = mock_get

        with patch('modules.communication.time.sleep') as mock_sleep:
            comm._send_queue_worker()
            mock_sleep.assert_called()

        comm._flush_send.assert_called_once()


class TestWiFiKeepaliveLoop:
    """覆盖 WiFi _keepalive_loop (lines 425-446)"""

    @patch('modules.communication.time.time')
    @patch('modules.communication.time.sleep')
    def test_keepalive_timeout(self, mock_sleep, mock_time):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        comm._ping_pending = False
        comm._last_pong_time = 100.0
        comm._client_socket = MagicMock()
        comm._lock = threading.Lock()

        mock_time.return_value = 100.0 + KEEPALIVE_TIMEOUT + 1
        mock_sleep.return_value = None

        comm._keepalive_loop()
        assert comm._connected is False

    @patch('modules.communication.time.time')
    @patch('modules.communication.time.sleep')
    def test_keepalive_send_ping(self, mock_sleep, mock_time):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        comm._ping_pending = False
        comm._last_pong_time = 100.0
        comm._client_socket = MagicMock()
        comm._flush_send = MagicMock()

        mock_time.return_value = 100.0 + KEEPALIVE_INTERVAL + 1
        mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)

        comm._keepalive_loop()
        comm._flush_send.assert_called_once()

    @patch('modules.communication.time.time')
    @patch('modules.communication.time.sleep')
    def test_keepalive_not_connected_continue(self, mock_sleep, mock_time):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = False
        comm._client_socket = None

        mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)

        comm._keepalive_loop()
        mock_time.assert_not_called()

    @patch('modules.communication.time.time')
    @patch('modules.communication.time.sleep')
    def test_keepalive_ping_exception(self, mock_sleep, mock_time):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        comm._ping_pending = False
        comm._last_pong_time = 100.0
        comm._client_socket = MagicMock()
        comm._flush_send = MagicMock(side_effect=Exception("send fail"))

        mock_time.return_value = 100.0 + KEEPALIVE_INTERVAL + 1
        mock_sleep.side_effect = lambda *a: setattr(comm, '_running', False)

        comm._keepalive_loop()
        comm._flush_send.assert_called_once()


class TestWiFiReadLoop:
    """覆盖 WiFi _read_loop (lines 449-508)"""

    def _make_comm_with_client(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        mock_client = MagicMock()
        comm._client_socket = mock_client
        comm._lock = threading.Lock()
        return comm, mock_client

    def test_len_header_and_payload(self):
        comm, mock_client = self._make_comm_with_client()

        payload = '{"type":"sensor","data":{"temp":25}}'
        frame = f"LEN:{len(payload)}\n{payload}\n".encode('utf-8')

        call_count = [0]
        def recv_side_effect(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return frame
            comm._running = False
            raise socket.timeout

        mock_client.recv.side_effect = recv_side_effect

        cb = MagicMock()
        comm.set_message_callback(cb)

        comm._read_loop()
        cb.assert_called_once()
        assert cb.call_args[0][0].msg_type == "sensor"

    def test_legacy_json_line(self):
        comm, mock_client = self._make_comm_with_client()

        data = '{"type":"ping","data":{}}\n'.encode('utf-8')

        call_count = [0]
        def recv_side_effect(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return data
            comm._running = False
            raise socket.timeout

        mock_client.recv.side_effect = recv_side_effect

        cb = MagicMock()
        comm.set_message_callback(cb)

        comm._read_loop()
        cb.assert_called_once()

    def test_empty_data_disconnect(self):
        comm, mock_client = self._make_comm_with_client()
        mock_client.recv.return_value = b''

        comm._read_loop()
        assert comm._connected is False

    def test_socket_timeout_continue(self):
        comm, mock_client = self._make_comm_with_client()

        call_count = [0]
        def recv_side_effect(*args):
            call_count[0] += 1
            if call_count[0] >= 3:
                comm._running = False
            raise socket.timeout

        mock_client.recv.side_effect = recv_side_effect
        comm._read_loop()

    def test_general_exception_break(self):
        comm, mock_client = self._make_comm_with_client()
        mock_client.recv.side_effect = OSError("connection reset")

        comm._read_loop()
        assert comm._connected is False

    def test_invalid_len_header(self):
        comm, mock_client = self._make_comm_with_client()

        data = 'LEN:abc\n'.encode('utf-8')

        call_count = [0]
        def recv_side_effect(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return data
            comm._running = False
            raise socket.timeout

        mock_client.recv.side_effect = recv_side_effect
        comm._read_loop()

    def test_no_client_not_connected_break(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = False
        comm._client_socket = None
        comm._lock = threading.Lock()

        comm._read_loop()

    def test_no_client_breaks_loop(self):
        comm = WiFiCommunication({})
        comm._running = True
        comm._connected = True
        comm._client_socket = None
        comm._lock = threading.Lock()

        comm._read_loop()
        # 循环因无client直接break，不会hang
        assert True
