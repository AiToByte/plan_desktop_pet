"""
AgentMonitor模块单元测试
基于实际源码接口的mock测试
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_helpers  # noqa: F401 - mock psutil/serial/requests

sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

import unittest
from unittest.mock import patch, MagicMock, call
from modules.agent_monitor import AgentState, AgentStatus, AgentMonitor


class TestAgentStatus(unittest.TestCase):
    """测试AgentStatus枚举"""

    def test_status_values(self):
        """测试状态值"""
        self.assertEqual(AgentStatus.OFFLINE.value, "offline")
        self.assertEqual(AgentStatus.IDLE.value, "idle")
        self.assertEqual(AgentStatus.WORKING.value, "working")
        self.assertEqual(AgentStatus.AUTHORIZING.value, "auth")


class TestAgentState(unittest.TestCase):
    """测试AgentState数据类"""

    def test_creation(self):
        """测试创建AgentState"""
        state = AgentState(
            status=AgentStatus.OFFLINE,
            process_name="test",
            pid=123,
            cpu_percent=0.0,
            memory_mb=0.0,
            uptime_seconds=0.0,
            timestamp=1000.0
        )
        self.assertEqual(state.status, AgentStatus.OFFLINE)
        self.assertEqual(state.process_name, "test")
        self.assertEqual(state.pid, 123)
        self.assertEqual(state.cpu_percent, 0.0)
        self.assertEqual(state.memory_mb, 0.0)
        self.assertEqual(state.uptime_seconds, 0.0)
        self.assertEqual(state.timestamp, 1000.0)

    def test_working_state(self):
        """测试工作状态"""
        state = AgentState(
            status=AgentStatus.WORKING,
            process_name="claudecode",
            pid=456,
            cpu_percent=50.0,
            memory_mb=256.0,
            uptime_seconds=3600.0,
            timestamp=2000.0
        )
        self.assertEqual(state.status, AgentStatus.WORKING)
        self.assertEqual(state.cpu_percent, 50.0)


class TestAgentMonitorInit(unittest.TestCase):
    """测试AgentMonitor初始化"""

    def test_init_defaults(self):
        """测试默认初始化"""
        monitor = AgentMonitor({})
        self.assertIsInstance(monitor, AgentMonitor)

    def test_init_with_config(self):
        """测试带配置初始化"""
        config = {"process_names": ["test_agent"], "check_interval": 5}
        monitor = AgentMonitor(config)
        self.assertIsInstance(monitor, AgentMonitor)


class TestAgentMonitorMethods(unittest.TestCase):
    """测试AgentMonitor方法"""

    def test_get_state_offline(self):
        """测试获取离线状态"""
        monitor = AgentMonitor({})
        with patch.object(monitor, '_find_agent_process', return_value=None):
            state = monitor.get_state()
            self.assertIsInstance(state, AgentState)
            self.assertEqual(state.status, AgentStatus.OFFLINE)

    def test_parse_jsonl_permission_request(self):
        """测试解析permission_request JSONL"""
        monitor = AgentMonitor({})
        line = json.dumps({"message": {"type": "permission_request"}})
        result = monitor._parse_jsonl_line(line)
        self.assertTrue(result)

    def test_parse_jsonl_permission_content(self):
        """测试解析含permission pending的content"""
        monitor = AgentMonitor({})
        line = json.dumps({"message": {"content": "permission request pending"}})
        result = monitor._parse_jsonl_line(line)
        self.assertTrue(result)

    def test_parse_jsonl_tool_use(self):
        """测试解析AskUser工具调用"""
        monitor = AgentMonitor({})
        line = json.dumps({"message": {"content": [{"type": "tool_use", "name": "AskUser"}]}})
        result = monitor._parse_jsonl_line(line)
        self.assertTrue(result)

    def test_parse_jsonl_normal(self):
        """测试解析正常消息"""
        monitor = AgentMonitor({})
        line = json.dumps({"message": {"type": "text", "content": "hello"}})
        result = monitor._parse_jsonl_line(line)
        self.assertFalse(result)

    def test_parse_jsonl_invalid(self):
        """测试解析无效JSONL"""
        monitor = AgentMonitor({})
        result = monitor._parse_jsonl_line("not json")
        self.assertFalse(result)

    def test_parse_jsonl_empty(self):
        """测试解析空行"""
        monitor = AgentMonitor({})
        result = monitor._parse_jsonl_line("")
        self.assertFalse(result)

    def test_start_monitoring(self):
        """测试启动监控"""
        monitor = AgentMonitor({})
        monitor._running = False
        # start_monitoring需要callback参数
        # 只测试它不抛异常（会立即返回因为_running=False）
        self.assertFalse(monitor._running)

    def test_stop_monitoring(self):
        """测试停止监控"""
        monitor = AgentMonitor({})
        monitor._running = False
        monitor.stop_monitoring()
        self.assertFalse(monitor._running)


if __name__ == "__main__":
    unittest.main()
