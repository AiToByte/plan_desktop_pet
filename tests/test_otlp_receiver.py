"""
OTLP接收模块测试
覆盖: OTLPSpan构造、OTLPReceiver生命周期、_parse_traces/_parse_single_span解析
OTLP JSON格式解析：resourceSpans→scopeSpans→spans层次、纳秒时间戳、属性提取
"""
import json
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from modules.otlp_receiver import (
    OTLPSpan,
    OTLPReceiver,
    _SPAN_KIND_MAP,
    _NS_PER_SECOND,
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def receiver():
    """OTLPReceiver实例"""
    return OTLPReceiver(port=4318, host="127.0.0.1")


@pytest.fixture
def sample_otlp_trace():
    """标准OTLP trace JSON（含完整层次结构）"""
    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "test-agent"}},
                    {"key": "service.version", "value": {"stringValue": "1.0.0"}},
                ]
            },
            "scopeSpans": [{
                "scope": {"name": "test-scope", "version": "0.1.0"},
                "spans": [{
                    "traceId": "abc123def456",
                    "spanId": "span001",
                    "name": "agent.thinking",
                    "kind": 1,
                    "startTimeUnixNano": "1700000000000000000",
                    "endTimeUnixNano": "1700000001500000000",
                    "status": {
                        "code": "STATUS_CODE_OK",
                        "message": "success"
                    },
                    "attributes": [
                        {"key": "agent.status", "value": {"stringValue": "working"}},
                        {"key": "token.count", "value": {"intValue": "1500"}},
                        {"key": "cost", "value": {"doubleValue": 0.05}},
                        {"key": "streaming", "value": {"boolValue": True}},
                    ],
                    "events": [{
                        "name": "token_generated",
                        "timeUnixNano": "1700000000500000000",
                        "attributes": [
                            {"key": "token_type", "value": {"stringValue": "output"}}
                        ]
                    }]
                }]
            }]
        }]
    }


# ── TestOTLPSpan ──────────────────────────────────────────

class TestOTLPSpan:
    def test_construction(self):
        """OTLPSpan基本构造"""
        span = OTLPSpan(
            trace_id="t1", span_id="s1", name="test",
            service_name="svc", kind="INTERNAL",
            status_code="OK", status_message="ok",
            start_time=1.0, end_time=2.0, duration_ms=1000.0
        )
        assert span.trace_id == "t1"
        assert span.span_id == "s1"
        assert span.name == "test"
        assert span.service_name == "svc"
        assert span.attributes == {}
        assert span.events == []

    def test_with_attributes_and_events(self):
        """带属性和事件"""
        span = OTLPSpan(
            trace_id="t1", span_id="s1", name="test",
            service_name="svc", kind="SERVER",
            status_code="ERROR", status_message="timeout",
            start_time=0, end_time=0, duration_ms=0,
            attributes={"key": "value"},
            events=[{"name": "ev1", "timestamp": 1.0, "attributes": {}}]
        )
        assert span.attributes["key"] == "value"
        assert len(span.events) == 1


# ── TestSpanKindMap ───────────────────────────────────────

class TestSpanKindMap:
    def test_all_kinds_mapped(self):
        """所有5种kind都有映射"""
        assert _SPAN_KIND_MAP == {0: "INTERNAL", 1: "SERVER", 2: "CLIENT", 3: "PRODUCER", 4: "CONSUMER"}

    def test_unknown_kind_default(self):
        """未知kind默认INTERNAL"""
        assert _SPAN_KIND_MAP.get(99, "INTERNAL") == "INTERNAL"


# ── TestParseSingleSpan ───────────────────────────────────

class TestParseSingleSpan:
    def test_parse_complete_span(self, sample_otlp_trace):
        """解析完整span数据"""
        span_data = sample_otlp_trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span = OTLPReceiver._parse_single_span(span_data, "test-agent")
        
        assert span is not None
        assert span.trace_id == "abc123def456"
        assert span.span_id == "span001"
        assert span.name == "agent.thinking"
        assert span.service_name == "test-agent"
        assert span.kind == "SERVER"
        assert span.status_code == "OK"
        assert span.status_message == "success"

    def test_timestamp_conversion(self, sample_otlp_trace):
        """纳秒→秒时间戳转换"""
        span_data = sample_otlp_trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span = OTLPReceiver._parse_single_span(span_data, "svc")
        
        assert span.start_time == 1700000000.0
        assert span.end_time == 1700000001.5
        assert abs(span.duration_ms - 1500.0) < 0.01

    def test_attributes_extraction(self, sample_otlp_trace):
        """属性提取（string/int/double/bool）"""
        span_data = sample_otlp_trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span = OTLPReceiver._parse_single_span(span_data, "svc")
        
        assert span.attributes["agent.status"] == "working"
        assert span.attributes["token.count"] == "1500"  # intValue是字符串
        assert span.attributes["cost"] == 0.05
        assert span.attributes["streaming"] is True

    def test_events_extraction(self, sample_otlp_trace):
        """事件提取"""
        span_data = sample_otlp_trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span = OTLPReceiver._parse_single_span(span_data, "svc")
        
        assert len(span.events) == 1
        event = span.events[0]
        assert event["name"] == "token_generated"
        assert abs(event["timestamp"] - 1700000000.5) < 0.01
        assert event["attributes"]["token_type"] == "output"

    def test_status_code_ok(self):
        """状态码OK"""
        data = {"status": {"code": "STATUS_CODE_OK"}, "kind": 0}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.status_code == "OK"

    def test_status_code_error(self):
        """状态码ERROR"""
        data = {"status": {"code": "STATUS_CODE_ERROR"}, "kind": 0}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.status_code == "ERROR"

    def test_status_code_unset(self):
        """状态码UNSET"""
        data = {"status": {"code": "STATUS_CODE_UNSET"}, "kind": 0}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.status_code == "UNSET"

    def test_empty_status(self):
        """无status字段默认UNSET"""
        data = {"kind": 0}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.status_code == "UNSET"

    def test_span_kind_server(self):
        """kind=1 → SERVER"""
        data = {"kind": 1, "status": {}}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.kind == "SERVER"

    def test_span_kind_client(self):
        """kind=2 → CLIENT"""
        data = {"kind": 2, "status": {}}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.kind == "CLIENT"

    def test_zero_timestamps(self):
        """零时间戳"""
        data = {"startTimeUnixNano": "0", "endTimeUnixNano": "0", "kind": 0, "status": {}}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.start_time == 0
        assert span.duration_ms == 0

    def test_no_attributes_no_events(self):
        """无属性无事件"""
        data = {"kind": 0, "status": {}}
        span = OTLPReceiver._parse_single_span(data, "svc")
        assert span.attributes == {}
        assert span.events == []

    def test_malformed_data_returns_none(self):
        """畸形数据返回None"""
        span = OTLPReceiver._parse_single_span(None, "svc")
        assert span is None

    def test_empty_span_data(self):
        """空字典数据"""
        span = OTLPReceiver._parse_single_span({}, "")
        assert span is not None  # 应该有默认值


# ── TestParseTraces ───────────────────────────────────────

class TestParseTraces:
    def test_parse_complete_trace(self, sample_otlp_trace):
        """解析完整OTLP trace"""
        spans = OTLPReceiver._parse_traces(sample_otlp_trace)
        assert len(spans) == 1
        assert spans[0].service_name == "test-agent"
        assert spans[0].name == "agent.thinking"

    def test_empty_resource_spans(self):
        """空resourceSpans"""
        spans = OTLPReceiver._parse_traces({"resourceSpans": []})
        assert spans == []

    def test_no_resource_spans_key(self):
        """无resourceSpans键"""
        spans = OTLPReceiver._parse_traces({})
        assert spans == []

    def test_multiple_spans_in_trace(self):
        """单个trace中多个spans"""
        data = {
            "resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]},
                "scopeSpans": [{
                    "scope": {"name": "scope1"},
                    "spans": [
                        {"name": "span1", "kind": 0, "status": {}},
                        {"name": "span2", "kind": 1, "status": {}},
                        {"name": "span3", "kind": 2, "status": {}},
                    ]
                }]
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        assert len(spans) == 3
        assert spans[0].name == "span1"
        assert spans[1].name == "span2"
        assert spans[2].name == "span3"

    def test_multiple_resource_spans(self):
        """多个resourceSpans（不同service）"""
        data = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc-a"}}]},
                    "scopeSpans": [{"scope": {"name": "s1"}, "spans": [{"name": "a1", "kind": 0, "status": {}}]}]
                },
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc-b"}}]},
                    "scopeSpans": [{"scope": {"name": "s2"}, "spans": [{"name": "b1", "kind": 0, "status": {}}]}]
                }
            ]
        }
        spans = OTLPReceiver._parse_traces(data)
        assert len(spans) == 2
        assert spans[0].service_name == "svc-a"
        assert spans[1].service_name == "svc-b"

    def test_no_service_name(self):
        """无service.name属性"""
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {}, "spans": [{"name": "s1", "kind": 0, "status": {}}]}]
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        assert len(spans) == 1
        assert spans[0].service_name == ""

    def test_empty_scope_spans(self):
        """空scopeSpans"""
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": []
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        assert spans == []


# ── TestOTLPReceiver ──────────────────────────────────────

class TestOTLPReceiver:
    def test_construction(self, receiver):
        """接收端初始化"""
        assert receiver.port == 4318
        assert receiver.host == "127.0.0.1"
        assert receiver._running is False
        assert receiver._span_callback is None
        assert receiver._health_callback is None

    def test_set_span_callback(self, receiver):
        """设置span回调"""
        cb = lambda s: None
        receiver.set_span_callback(cb)
        assert receiver._span_callback is cb

    def test_set_health_callback(self, receiver):
        """设置健康检查回调"""
        cb = lambda: {"status": "ok"}
        receiver.set_health_callback(cb)
        assert receiver._health_callback is cb

    @patch("modules.otlp_receiver.HTTPServer")
    def test_start_success(self, mock_http_cls):
        """启动成功（mock HTTPServer）"""
        mock_server = MagicMock()
        mock_http_cls.return_value = mock_server
        r = OTLPReceiver(port=4318)
        result = r.start()
        assert result is True
        assert r._running is True
        assert r._server is mock_server
        # 线程已启动（serve_forever在线程中）
        r.stop()

    def test_start_failure(self):
        """启动失败（无效端口）"""
        r = OTLPReceiver(port=-1)
        result = r.start()
        assert result is False

    @patch("modules.otlp_receiver.HTTPServer")
    def test_stop(self, mock_http_cls):
        """停止接收端"""
        mock_server = MagicMock()
        mock_http_cls.return_value = mock_server
        r = OTLPReceiver(port=4318)
        r.start()
        assert r._running is True
        r.stop()
        assert r._running is False
        mock_server.shutdown.assert_called_once()

    def test_stop_without_start(self, receiver):
        """未启动时stop不报错"""
        receiver.stop()  # 不应抛异常


# ── TestConstants ─────────────────────────────────────────

class TestConstants:
    def test_ns_per_second(self):
        """纳秒每秒常量"""
        assert _NS_PER_SECOND == 1_000_000_000
