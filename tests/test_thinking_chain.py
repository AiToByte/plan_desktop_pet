"""
思考链可视化模块测试
覆盖: ThinkingState, ThinkingStep, ThinkingChainTracker
重点: span分类、状态映射、agent过滤、详情提取、防抖、帧协议发送、自动重连
"""
import json
import socket
import time
from unittest.mock import MagicMock, patch, call

import pytest

from modules.thinking_chain import (
    ThinkingState,
    ThinkingStep,
    ThinkingChainTracker,
)


# ── Helpers ──────────────────────────────────────────────

def make_span(name="agent.thinking", service_name="test-agent",
              span_id="span_001", trace_id="trace_001",
              start_time=1000.0, duration_ms=500.0,
              attributes=None, status_code="OK", events=None):
    """创建mock OTLPSpan"""
    span = MagicMock()
    span.name = name
    span.service_name = service_name
    span.span_id = span_id
    span.trace_id = trace_id
    span.start_time = start_time
    span.duration_ms = duration_ms
    span.attributes = attributes or {}
    span.status_code = status_code
    span.events = events or []
    return span


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def tracker():
    """无ESP32连接的追踪器"""
    return ThinkingChainTracker()


@pytest.fixture
def mock_socket():
    """mock socket对象"""
    sock = MagicMock(spec=socket.socket)
    return sock


# ── TestThinkingState ────────────────────────────────────

class TestThinkingState:
    """ThinkingState枚举测试"""

    def test_all_values(self):
        """枚举值完整性"""
        assert ThinkingState.IDLE.value == "idle"
        assert ThinkingState.THINKING.value == "thinking"
        assert ThinkingState.TOOL_CALL.value == "tool_call"
        assert ThinkingState.RESPONDING.value == "responding"
        assert ThinkingState.ERROR.value == "error"
        assert ThinkingState.DONE.value == "done"

    def test_enum_count(self):
        """枚举成员数量"""
        assert len(ThinkingState) == 6


# ── TestThinkingStep ─────────────────────────────────────

class TestThinkingStep:
    """ThinkingStep数据类测试"""

    def test_construction(self):
        """基本构造"""
        step = ThinkingStep(step_id="s1", name="test", state=ThinkingState.THINKING)
        assert step.step_id == "s1"
        assert step.name == "test"
        assert step.state == ThinkingState.THINKING
        assert step.detail == ""
        assert step.start_time == 0.0
        assert step.duration_ms == 0.0
        assert step.tool_name == ""
        assert step.status == ""

    def test_full_construction(self):
        """完整构造"""
        step = ThinkingStep(
            step_id="s2", name="tool_call",
            state=ThinkingState.TOOL_CALL,
            detail="searching", start_time=100.0,
            duration_ms=250.0, tool_name="web_search",
            status="OK"
        )
        assert step.tool_name == "web_search"
        assert step.duration_ms == 250.0


# ── TestSpanStateMap ─────────────────────────────────────

class TestSpanStateMap:
    """_SPAN_STATE_MAP映射测试"""

    def test_map_completeness(self):
        """关键关键字都有映射"""
        expected_keywords = ["think", "thinking", "tool_call", "tool",
                             "respond", "response", "generate"]
        for kw in expected_keywords:
            assert kw in ThinkingChainTracker._SPAN_STATE_MAP

    def test_thinking_keywords(self):
        """thinking类关键字→THINKING"""
        for kw in ("think", "thinking", "reasoning", "plan"):
            assert ThinkingChainTracker._SPAN_STATE_MAP[kw] == ThinkingState.THINKING

    def test_tool_keywords(self):
        """tool类关键字→TOOL_CALL"""
        for kw in ("tool_call", "tool", "function_call"):
            assert ThinkingChainTracker._SPAN_STATE_MAP[kw] == ThinkingState.TOOL_CALL


# ── TestConstruction ─────────────────────────────────────

class TestConstruction:
    """构造和set_esp32"""

    def test_default_construction(self, tracker):
        """默认构造"""
        assert tracker._current_state == ThinkingState.IDLE
        assert tracker._steps == []
        assert tracker._trace_id == ""
        assert tracker._esp32_host == ""
        assert tracker._esp32_port == 19876
        assert tracker._debounce_ms == 200.0
        assert tracker._sock is None

    def test_construction_with_host(self):
        """指定host构造"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100", esp32_port=12345)
        assert t._esp32_host == "192.168.1.100"
        assert t._esp32_port == 12345

    def test_set_esp32(self, tracker):
        """set_esp32更新参数"""
        tracker.set_esp32("10.0.0.1", 9999)
        assert tracker._esp32_host == "10.0.0.1"
        assert tracker._esp32_port == 9999

    def test_set_esp32_default_port(self, tracker):
        """set_esp32默认端口"""
        tracker.set_esp32("10.0.0.1")
        assert tracker._esp32_port == 19876


# ── TestIsAgentSpan ──────────────────────────────────────

class TestIsAgentSpan:
    """_is_agent_span过滤"""

    def test_agent_in_name(self, tracker):
        """name包含agent→True"""
        span = make_span(name="agent.thinking")
        assert tracker._is_agent_span(span) is True

    def test_think_in_name(self, tracker):
        """name包含think→True"""
        span = make_span(name="my_thinking_step")
        assert tracker._is_agent_span(span) is True

    def test_tool_in_service(self, tracker):
        """service_name包含tool→True"""
        span = make_span(name="step1", service_name="tool-service")
        assert tracker._is_agent_span(span) is True

    def test_non_agent_span(self, tracker):
        """无关span→False"""
        span = make_span(name="http.request", service_name="web-server")
        assert tracker._is_agent_span(span) is False

    def test_llm_in_name(self, tracker):
        """name包含llm→True"""
        span = make_span(name="llm.generate")
        assert tracker._is_agent_span(span) is True

    def test_case_insensitive(self, tracker):
        """大小写不敏感"""
        span = make_span(name="AGENT.Thinking", service_name="Test-Agent")
        assert tracker._is_agent_span(span) is True


# ── TestClassifySpan ─────────────────────────────────────

class TestClassifySpan:
    """_classify_span分类"""

    def test_thinking_classify(self, tracker):
        """thinking类name→THINKING"""
        for name in ("agent.thinking", "my.reasoning", "plan.strategy"):
            span = make_span(name=name)
            assert tracker._classify_span(span) == ThinkingState.THINKING

    def test_tool_call_classify(self, tracker):
        """tool类name→TOOL_CALL"""
        for name in ("tool_call.search", "my.tool.step", "function_call"):
            span = make_span(name=name)
            assert tracker._classify_span(span) == ThinkingState.TOOL_CALL

    def test_responding_classify(self, tracker):
        """response类name→RESPONDING"""
        for name in ("agent.respond", "response.stream", "generate.output"):
            span = make_span(name=name)
            assert tracker._classify_span(span) == ThinkingState.RESPONDING

    def test_tool_name_attribute(self, tracker):
        """有tool.name属性→TOOL_CALL"""
        span = make_span(name="unknown.step", attributes={"tool.name": "search"})
        assert tracker._classify_span(span) == ThinkingState.TOOL_CALL

    def test_error_status(self, tracker):
        """ERROR状态码→ERROR"""
        span = make_span(name="unknown.step", status_code="ERROR")
        assert tracker._classify_span(span) == ThinkingState.ERROR

    def test_default_to_thinking(self, tracker):
        """无法分类→默认THINKING"""
        span = make_span(name="mysterious.step")
        assert tracker._classify_span(span) == ThinkingState.THINKING


# ── TestExtractDetail ────────────────────────────────────

class TestExtractDetail:
    """_extract_detail提取详情"""

    def test_description_attribute(self, tracker):
        """优先取description属性"""
        span = make_span(name="test", attributes={"description": "doing search"})
        assert tracker._extract_detail(span) == "doing search"

    def test_message_attribute(self, tracker):
        """次选message属性"""
        span = make_span(name="test", attributes={"message": "processing data"})
        assert tracker._extract_detail(span) == "processing data"

    def test_truncate_to_32(self, tracker):
        """详情截断到32字符"""
        long_desc = "a" * 50
        span = make_span(name="test", attributes={"description": long_desc})
        assert len(tracker._extract_detail(span)) == 32

    def test_from_events(self, tracker):
        """从events提取"""
        span = make_span(name="test", events=[{"name": "event_msg"}])
        assert tracker._extract_detail(span) == "event_msg"

    def test_fallback_to_name(self, tracker):
        """无属性无事件→用name"""
        span = make_span(name="fallback_name")
        assert tracker._extract_detail(span) == "fallback_name"

    def test_fallback_truncate(self, tracker):
        """name超长也截断"""
        span = make_span(name="x" * 50)
        assert len(tracker._extract_detail(span)) == 32


# ── TestOnSpan ───────────────────────────────────────────

class TestOnSpan:
    """on_span完整流程"""

    def test_non_agent_span_ignored(self, tracker):
        """非agent span被忽略"""
        span = make_span(name="http.request", service_name="web-server")
        tracker.on_span(span)
        assert tracker._steps == []
        assert tracker._current_state == ThinkingState.IDLE

    def test_agent_span_processed(self, tracker):
        """agent span被处理"""
        span = make_span(name="agent.thinking", span_id="s1")
        tracker.on_span(span)
        assert len(tracker._steps) == 1
        assert tracker._steps[0].step_id == "s1"
        assert tracker._current_state == ThinkingState.THINKING

    def test_new_trace_clears_steps(self, tracker):
        """新trace_id清空旧steps"""
        span1 = make_span(name="agent.thinking", trace_id="trace_1")
        tracker.on_span(span1)
        assert len(tracker._steps) == 1

        span2 = make_span(name="agent.thinking", trace_id="trace_2")
        tracker.on_span(span2)
        assert len(tracker._steps) == 1  # 旧trace被清除
        assert tracker._trace_id == "trace_2"

    def test_same_trace_accumulates(self, tracker):
        """同trace_id累加steps"""
        span1 = make_span(name="agent.thinking", trace_id="t1", span_id="s1")
        span2 = make_span(name="tool_call.search", trace_id="t1", span_id="s2")
        tracker.on_span(span1)
        tracker.on_span(span2)
        assert len(tracker._steps) == 2

    def test_state_updates(self, tracker):
        """状态随span变化"""
        tracker.on_span(make_span(name="agent.thinking"))
        assert tracker._current_state == ThinkingState.THINKING
        tracker.on_span(make_span(name="tool_call.search", trace_id="trace_001"))
        assert tracker._current_state == ThinkingState.TOOL_CALL

    def test_tool_name_extracted(self, tracker):
        """tool.name从属性提取"""
        span = make_span(name="tool_call", attributes={"tool.name": "web_search"})
        tracker.on_span(span)
        assert tracker._steps[0].tool_name == "web_search"

    def test_status_extracted(self, tracker):
        """status_code写入step"""
        span = make_span(name="agent.thinking", status_code="ERROR")
        tracker.on_span(span)
        assert tracker._steps[0].status == "ERROR"


# ── TestGetCurrentStatus ─────────────────────────────────

class TestGetCurrentStatus:
    """get_current_status状态摘要"""

    def test_initial_status(self, tracker):
        """初始状态"""
        status = tracker.get_current_status()
        assert status["state"] == "idle"
        assert status["trace_id"] == ""
        assert status["step_count"] == 0
        assert status["last_step"] == ""
        assert status["last_tool"] == ""

    def test_after_span(self, tracker):
        """处理span后"""
        tracker.on_span(make_span(name="agent.thinking"))
        status = tracker.get_current_status()
        assert status["state"] == "thinking"
        assert status["step_count"] == 1
        assert status["last_step"] == "agent.thinking"

    def test_last_tool(self, tracker):
        """last_tool正确"""
        tracker.on_span(make_span(name="agent.thinking"))
        tracker.on_span(make_span(name="tool_call", attributes={"tool.name": "search"}))
        status = tracker.get_current_status()
        assert status["last_tool"] == "search"

    def test_last_tool_empty_when_no_tool(self, tracker):
        """无tool时last_tool为空"""
        tracker.on_span(make_span(name="agent.thinking"))
        status = tracker.get_current_status()
        assert status["last_tool"] == ""


# ── TestReset ────────────────────────────────────────────

class TestReset:
    """reset重置"""

    def test_reset_clears_state(self, tracker):
        """reset清除所有状态"""
        tracker.on_span(make_span(name="agent.thinking"))
        tracker.on_span(make_span(name="tool_call", trace_id="trace_001"))
        tracker.reset()
        assert tracker._current_state == ThinkingState.IDLE
        assert tracker._steps == []
        assert tracker._trace_id == ""

    def test_reset_sends_idle_to_esp32(self):
        """reset发送idle消息到ESP32"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        with patch.object(t, "_send_to_esp32") as mock_send:
            t.reset()
            mock_send.assert_called_once()
            sent_step = mock_send.call_args[0][0]
            assert sent_step.state == ThinkingState.IDLE


# ── TestSendToEsp32 ──────────────────────────────────────

class TestSendToEsp32:
    """_send_to_esp32发送逻辑"""

    def test_no_host_skips(self, tracker):
        """无host时不发送"""
        step = ThinkingStep(step_id="s1", name="test", state=ThinkingState.THINKING)
        with patch.object(tracker, "_send_framed") as mock_send:
            tracker._send_to_esp32(step)
            mock_send.assert_not_called()

    def test_sends_json_with_correct_fields(self):
        """发送JSON包含正确字段"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        t._steps = [ThinkingStep(step_id="s1", name="test", state=ThinkingState.THINKING)]
        step = ThinkingStep(step_id="s1", name="agent.thinking",
                           state=ThinkingState.THINKING, detail="reasoning",
                           tool_name="search", duration_ms=150.0)
        with patch.object(t, "_send_framed") as mock_send:
            t._send_to_esp32(step)
            mock_send.assert_called_once()
            msg = json.loads(mock_send.call_args[0][0])
            assert msg["type"] == "thinking_status"
            assert msg["state"] == "thinking"
            assert msg["tool"] == "search"
            assert msg["duration_ms"] == 150
            assert msg["step_count"] == 1

    def test_name_truncated_to_24(self):
        """name截断到24字符"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        t._steps = []
        step = ThinkingStep(step_id="s1", name="x" * 30, state=ThinkingState.THINKING)
        with patch.object(t, "_send_framed") as mock_send:
            t._send_to_esp32(step)
            msg = json.loads(mock_send.call_args[0][0])
            assert len(msg["name"]) == 24

    def test_failure_handled(self):
        """发送失败不抛异常"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        t._steps = []
        step = ThinkingStep(step_id="s1", name="test", state=ThinkingState.THINKING)
        with patch.object(t, "_send_framed", side_effect=OSError("network error")):
            t._send_to_esp32(step)  # 不应抛异常


# ── TestSendFramed ───────────────────────────────────────

class TestSendFramed:
    """_send_framed帧协议"""

    def test_creates_socket_on_first_send(self):
        """首次发送创建socket"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100", esp32_port=19876)
        with patch("modules.thinking_chain.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock
            t._send_framed('{"test": 1}')
            mock_sock.connect.assert_called_once_with(("192.168.1.100", 19876))

    def test_frame_format(self):
        """帧格式: LEN:<len>\n<payload>"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        mock_sock = MagicMock()
        t._sock = mock_sock
        payload = '{"state":"thinking"}'
        t._send_framed(payload)
        sent = mock_sock.sendall.call_args[0][0]
        expected_header = f"LEN:{len(payload.encode('utf-8'))}\n".encode("utf-8")
        assert sent == expected_header + payload.encode("utf-8")

    def test_reconnect_on_broken_pipe(self):
        """BrokenPipeError触发重连"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100", esp32_port=19876)
        old_sock = MagicMock()
        new_sock = MagicMock()
        t._sock = old_sock
        old_sock.sendall.side_effect = BrokenPipeError("pipe broken")
        with patch("modules.thinking_chain.socket.socket", return_value=new_sock):
            t._send_framed('{"test":1}')
            old_sock.close.assert_called_once()
            new_sock.connect.assert_called_with(("192.168.1.100", 19876))

    def test_reconnect_on_connection_reset(self):
        """ConnectionResetError触发重连"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        old_sock = MagicMock()
        new_sock = MagicMock()
        t._sock = old_sock
        old_sock.sendall.side_effect = ConnectionResetError("reset")
        with patch("modules.thinking_chain.socket.socket", return_value=new_sock):
            t._send_framed('{"test":1}')
            old_sock.close.assert_called_once()


# ── TestClose ────────────────────────────────────────────

class TestClose:
    """close关闭连接"""

    def test_close_with_socket(self):
        """有socket时关闭"""
        t = ThinkingChainTracker()
        mock_sock = MagicMock()
        t._sock = mock_sock
        t.close()
        mock_sock.close.assert_called_once()
        assert t._sock is None

    def test_close_without_socket(self):
        """无socket时不报错"""
        t = ThinkingChainTracker()
        t.close()  # 不应抛异常
        assert t._sock is None

    def test_close_handles_error(self):
        """close时socket.close()抛异常也不影响"""
        t = ThinkingChainTracker()
        mock_sock = MagicMock()
        mock_sock.close.side_effect = OSError("already closed")
        t._sock = mock_sock
        t.close()
        assert t._sock is None


# ── TestDebounce ─────────────────────────────────────────

class TestDebounce:
    """防抖逻辑"""

    def test_first_send_not_debounced(self):
        """首次发送不被防抖拦截"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        t._last_update = 0
        with patch.object(t, "_send_to_esp32") as mock_send:
            t.on_span(make_span(name="agent.thinking"))
            mock_send.assert_called()

    def test_rapid_second_send_debounced(self):
        """快速第二次发送被防抖"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        with patch.object(t, "_send_to_esp32") as mock_send:
            t.on_span(make_span(name="agent.thinking"))
            call_count_after_first = mock_send.call_count
            # 立即发送第二次（同一trace，防抖内）
            t.on_span(make_span(name="agent.thinking", span_id="s2"))
            # 由于防抖，第二次不应触发发送
            assert mock_send.call_count == call_count_after_first

    def test_after_debounce_sends(self):
        """防抖过期后可发送"""
        t = ThinkingChainTracker(esp32_host="192.168.1.100")
        with patch.object(t, "_send_to_esp32") as mock_send:
            t.on_span(make_span(name="agent.thinking"))
            # 模拟时间流逝
            t._last_update = time.time() * 1000 - 300  # 超过200ms防抖
            t.on_span(make_span(name="tool_call", span_id="s2"))
            assert mock_send.call_count == 2
