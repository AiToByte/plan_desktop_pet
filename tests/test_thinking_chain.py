"""
ThinkingChain模块单元测试
覆盖ThinkingState/ThinkingStep/ThinkingChainTracker + Opt18 socket清理
"""
import sys
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, str(Path(__file__).parent))
import test_helpers  # noqa: F401

sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

from modules.thinking_chain import (
    ThinkingState, ThinkingStep, ThinkingChainTracker
)


class MockSpan:
    """模拟OTLPSpan对象"""
    def __init__(self, name="tool_call", trace_id="t1", span_id="s1",
                 service_name="agent", attributes=None, events=None,
                 status_code="OK", duration_ms=100.0, start_time=1000.0):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.service_name = service_name
        self.attributes = attributes or {}
        self.events = events or []
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.start_time = start_time


class TestThinkingState(unittest.TestCase):
    """测试ThinkingState枚举"""

    def test_enum_values(self):
        """测试枚举值"""
        self.assertEqual(ThinkingState.IDLE.value, "idle")
        self.assertEqual(ThinkingState.THINKING.value, "thinking")
        self.assertEqual(ThinkingState.TOOL_CALL.value, "tool_call")
        self.assertEqual(ThinkingState.RESPONDING.value, "responding")
        self.assertEqual(ThinkingState.ERROR.value, "error")
        self.assertEqual(ThinkingState.DONE.value, "done")

    def test_enum_member_count(self):
        """测试枚举成员数量"""
        self.assertEqual(len(ThinkingState), 6)


class TestThinkingStep(unittest.TestCase):
    """测试ThinkingStep数据类"""

    def test_creation(self):
        """测试创建ThinkingStep"""
        step = ThinkingStep(
            step_id="s1", name="think",
            state=ThinkingState.THINKING,
            detail="reasoning", start_time=1000.0,
            duration_ms=50.0, tool_name="", status="OK"
        )
        self.assertEqual(step.step_id, "s1")
        self.assertEqual(step.state, ThinkingState.THINKING)
        self.assertEqual(step.detail, "reasoning")

    def test_defaults(self):
        """测试默认值"""
        step = ThinkingStep(step_id="s1", name="test", state=ThinkingState.IDLE)
        self.assertEqual(step.detail, "")
        self.assertEqual(step.tool_name, "")
        self.assertEqual(step.status, "")
        self.assertEqual(step.duration_ms, 0.0)


class TestThinkingChainTracker(unittest.TestCase):
    """测试ThinkingChainTracker"""

    def setUp(self):
        self.tracker = ThinkingChainTracker()

    def test_init_defaults(self):
        """测试默认初始化"""
        tracker = ThinkingChainTracker()
        self.assertEqual(tracker._esp32_host, "")
        self.assertEqual(tracker._esp32_port, 19876)
        self.assertEqual(tracker._current_state, ThinkingState.IDLE)
        self.assertEqual(len(tracker._steps), 0)
        self.assertIsNone(tracker._sock)

    def test_init_with_params(self):
        """测试带参数初始化"""
        tracker = ThinkingChainTracker(esp32_host="192.168.1.1", esp32_port=12345)
        self.assertEqual(tracker._esp32_host, "192.168.1.1")
        self.assertEqual(tracker._esp32_port, 12345)

    def test_set_esp32(self):
        """测试设置ESP32参数"""
        self.tracker.set_esp32("10.0.0.1", 9999)
        self.assertEqual(self.tracker._esp32_host, "10.0.0.1")
        self.assertEqual(self.tracker._esp32_port, 9999)

    def test_get_current_status_empty(self):
        """测试空状态查询"""
        status = self.tracker.get_current_status()
        self.assertEqual(status["state"], "idle")
        self.assertEqual(status["trace_id"], "")
        self.assertEqual(status["step_count"], 0)
        self.assertEqual(status["last_step"], "")
        self.assertEqual(status["last_tool"], "")

    def test_get_current_status_with_steps(self):
        """测试有步骤时的状态查询"""
        span = MockSpan(name="tool_call", trace_id="t1", span_id="s1",
                        service_name="agent", attributes={"tool.name": "web_search"})
        self.tracker.on_span(span)
        status = self.tracker.get_current_status()
        self.assertEqual(status["state"], "tool_call")
        self.assertEqual(status["trace_id"], "t1")
        self.assertEqual(status["step_count"], 1)
        self.assertEqual(status["last_step"], "tool_call")
        self.assertEqual(status["last_tool"], "web_search")

    def test_is_agent_span(self):
        """测试agent span识别"""
        # 应该识别
        span1 = MockSpan(name="think_step", service_name="agent")
        self.assertTrue(self.tracker._is_agent_span(span1))

        span2 = MockSpan(name="tool_call", service_name="my_app")
        self.assertTrue(self.tracker._is_agent_span(span2))

        span3 = MockSpan(name="db_query", service_name="llm_service")
        self.assertTrue(self.tracker._is_agent_span(span3))

        # 不应该识别
        span4 = MockSpan(name="db_query", service_name="my_app")
        self.assertFalse(self.tracker._is_agent_span(span4))

    def test_classify_span_thinking(self):
        """测试分类think/thinking/plan→THINKING"""
        for name in ["think", "thinking", "reasoning", "plan"]:
            span = MockSpan(name=name)
            self.assertEqual(self.tracker._classify_span(span), ThinkingState.THINKING,
                             f"span name '{name}' should be THINKING")

    def test_classify_span_tool_call(self):
        """测试分类tool_call/function→TOOL_CALL"""
        for name in ["tool_call", "tool", "function_call"]:
            span = MockSpan(name=name)
            self.assertEqual(self.tracker._classify_span(span), ThinkingState.TOOL_CALL,
                             f"span name '{name}' should be TOOL_CALL")

    def test_classify_span_responding(self):
        """测试分类respond/response→RESPONDING"""
        for name in ["respond", "response", "generate"]:
            span = MockSpan(name=name)
            self.assertEqual(self.tracker._classify_span(span), ThinkingState.RESPONDING,
                             f"span name '{name}' should be RESPONDING")

    def test_classify_span_by_attribute(self):
        """测试通过属性分类"""
        span = MockSpan(name="unknown", attributes={"tool.name": "search"})
        self.assertEqual(self.tracker._classify_span(span), ThinkingState.TOOL_CALL)

    def test_classify_span_error(self):
        """测试错误状态分类"""
        span = MockSpan(name="unknown", status_code="ERROR")
        self.assertEqual(self.tracker._classify_span(span), ThinkingState.ERROR)

    def test_classify_span_default_thinking(self):
        """测试默认分类为THINKING"""
        span = MockSpan(name="unknown_span", status_code="OK")
        self.assertEqual(self.tracker._classify_span(span), ThinkingState.THINKING)

    def test_on_span_agent(self):
        """测试处理agent span"""
        span = MockSpan(name="tool_call", trace_id="t1", span_id="s1",
                        service_name="agent", attributes={"tool.name": "search"})
        self.tracker.on_span(span)
        self.assertEqual(len(self.tracker._steps), 1)
        self.assertEqual(self.tracker._trace_id, "t1")
        self.assertEqual(self.tracker._current_state, ThinkingState.TOOL_CALL)

    def test_on_span_non_agent(self):
        """测试忽略非agent span"""
        span = MockSpan(name="db_query", service_name="database")
        self.tracker.on_span(span)
        self.assertEqual(len(self.tracker._steps), 0)

    def test_on_span_new_trace_clears_steps(self):
        """测试新trace清除旧步骤"""
        span1 = MockSpan(name="think", trace_id="t1", span_id="s1", service_name="agent")
        span2 = MockSpan(name="tool_call", trace_id="t2", span_id="s2", service_name="agent")
        self.tracker.on_span(span1)
        self.assertEqual(len(self.tracker._steps), 1)
        self.tracker.on_span(span2)
        self.assertEqual(len(self.tracker._steps), 1)  # 旧步骤被清除
        self.assertEqual(self.tracker._trace_id, "t2")

    def test_reset(self):
        """测试重置"""
        span = MockSpan(name="think", trace_id="t1", span_id="s1", service_name="agent")
        self.tracker.on_span(span)
        self.tracker._sock = MagicMock()  # 模拟已有连接
        self.tracker.reset()
        self.assertEqual(self.tracker._current_state, ThinkingState.IDLE)
        self.assertEqual(len(self.tracker._steps), 0)
        self.assertEqual(self.tracker._trace_id, "")

    def test_extract_detail_from_attributes(self):
        """测试从属性提取详情"""
        span = MockSpan(attributes={"description": "searching web"})
        detail = self.tracker._extract_detail(span)
        self.assertEqual(detail, "searching web")

    def test_extract_detail_truncation(self):
        """测试详情截断到32字符"""
        span = MockSpan(attributes={"description": "a" * 50})
        detail = self.tracker._extract_detail(span)
        self.assertEqual(len(detail), 32)

    def test_extract_detail_from_events(self):
        """测试从事件提取详情"""
        span = MockSpan(events=[{"name": "event_info"}])
        detail = self.tracker._extract_detail(span)
        self.assertEqual(detail, "event_info")

    def test_extract_detail_fallback_to_name(self):
        """测试回退到span name"""
        span = MockSpan(name="some_span_name")
        detail = self.tracker._extract_detail(span)
        self.assertEqual(detail, "some_span_name")

    def test_close_with_socket(self):
        """测试关闭已有socket"""
        mock_sock = MagicMock()
        self.tracker._sock = mock_sock
        self.tracker.close()
        mock_sock.close.assert_called_once()
        self.assertIsNone(self.tracker._sock)

    def test_close_without_socket(self):
        """测试无socket时关闭"""
        self.tracker._sock = None
        self.tracker.close()  # 不应抛异常
        self.assertIsNone(self.tracker._sock)

    def test_close_socket_exception(self):
        """测试close时socket抛异常"""
        mock_sock = MagicMock()
        mock_sock.close.side_effect = OSError("broken")
        self.tracker._sock = mock_sock
        self.tracker.close()  # 不应传播异常
        self.assertIsNone(self.tracker._sock)

    @patch('modules.thinking_chain.socket.socket')
    def test_send_framed_creates_connection(self, mock_socket_class):
        """测试首次发送创建连接"""
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        self.tracker._esp32_host = "192.168.1.1"
        self.tracker._send_framed('{"test":1}')
        mock_socket_class.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_sock.connect.assert_called_once_with(("192.168.1.1", 19876))

    @patch('modules.thinking_chain.socket.socket')
    def test_send_framed_connection_refused(self, mock_socket_class):
        """测试连接失败时socket置None"""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError()
        mock_socket_class.return_value = mock_sock
        self.tracker._esp32_host = "192.168.1.1"
        self.tracker._send_framed('{"test":1}')
        self.assertIsNone(self.tracker._sock)

    @patch('modules.thinking_chain.socket.socket')
    def test_send_framed_sendall_failure_cleanup(self, mock_socket_class):
        """Opt18: sendall失败后socket置None(Opt18核心测试)"""
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = OSError("broken pipe")
        mock_socket_class.return_value = mock_sock
        self.tracker._esp32_host = "192.168.1.1"

        # 第一次发送建立连接
        self.tracker._send_framed('{"test":1}')
        # _sock应该被清理
        self.assertIsNone(self.tracker._sock)
        mock_sock.close.assert_called_once()

    def test_send_framed_no_host(self):
        """测试无host时不发送"""
        self.tracker._esp32_host = ""
        self.tracker._send_framed('{"test":1}')  # 不应抛异常

    def test_send_to_esp32_no_host(self):
        """测试无host时_send_to_esp32跳过"""
        self.tracker._esp32_host = ""
        step = ThinkingStep(step_id="s1", name="test", state=ThinkingState.IDLE)
        self.tracker._send_to_esp32(step)  # 不应抛异常

    @patch('modules.thinking_chain.socket.socket')
    def test_send_framed_payload_format(self, mock_socket_class):
        """测试发送帧格式 LEN:{size}\n{json}"""
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        self.tracker._esp32_host = "192.168.1.1"

        test_json = '{"state":"idle"}'
        self.tracker._send_framed(test_json)

        # 检查sendall调用参数
        call_args = mock_sock.sendall.call_args[0][0]
        payload = test_json.encode("utf-8")
        header = f"LEN:{len(payload)}\n".encode("utf-8")
        self.assertEqual(call_args, header + payload)

    def test_span_state_map_completeness(self):
        """测试状态映射表完整性"""
        expected_keys = {"think", "thinking", "reasoning", "plan",
                         "tool_call", "tool", "function_call",
                         "respond", "response", "generate"}
        self.assertEqual(set(ThinkingChainTracker._SPAN_STATE_MAP.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
