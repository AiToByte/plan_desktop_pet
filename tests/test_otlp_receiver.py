"""
OTLPReceiver模块单元测试
测试OTLP JSON解析、Span提取、静态方法等功能
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_helpers  # noqa: F401 - mock psutil/serial/requests

sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

import unittest
from unittest.mock import patch, MagicMock
from modules.otlp_receiver import OTLPReceiver, OTLPSpan, _SPAN_KIND_MAP


class TestOTLPSpan(unittest.TestCase):
    """测试OTLPSpan数据类"""

    def test_create_span(self):
        """测试创建Span对象"""
        span = OTLPSpan(
            trace_id="abc123",
            span_id="def456",
            name="test_span",
            service_name="test_service",
            kind="INTERNAL",
            status_code="OK",
            status_message="",
            start_time=1000.0,
            end_time=1001.0,
            duration_ms=1000.0
        )
        self.assertEqual(span.trace_id, "abc123")
        self.assertEqual(span.name, "test_span")
        self.assertEqual(span.status_code, "OK")

    def test_default_attributes(self):
        """测试默认空属性"""
        span = OTLPSpan(
            trace_id="", span_id="", name="", service_name="",
            kind="INTERNAL", status_code="OK", status_message="",
            start_time=0, end_time=0, duration_ms=0
        )
        self.assertEqual(span.attributes, {})
        self.assertEqual(span.events, [])

    def test_span_with_attributes(self):
        """测试带属性的Span"""
        span = OTLPSpan(
            trace_id="", span_id="", name="", service_name="",
            kind="CLIENT", status_code="ERROR", status_message="timeout",
            start_time=0, end_time=0, duration_ms=0,
            attributes={"http.method": "GET", "http.status_code": 500}
        )
        self.assertEqual(span.attributes["http.method"], "GET")
        self.assertEqual(span.kind, "CLIENT")


class TestSpanKindMap(unittest.TestCase):
    """测试Span Kind映射"""

    def test_known_kinds(self):
        """测试已知Kind映射"""
        self.assertEqual(_SPAN_KIND_MAP[0], "INTERNAL")
        self.assertEqual(_SPAN_KIND_MAP[1], "SERVER")
        self.assertEqual(_SPAN_KIND_MAP[2], "CLIENT")
        self.assertEqual(_SPAN_KIND_MAP[3], "PRODUCER")
        self.assertEqual(_SPAN_KIND_MAP[4], "CONSUMER")


class TestParseTraces(unittest.TestCase):
    """测试OTLP traces解析"""

    def test_parse_empty_traces(self):
        """测试解析空traces"""
        result = OTLPReceiver._parse_traces({})
        self.assertEqual(result, [])

    def test_parse_no_resource_spans(self):
        """测试无resourceSpans字段"""
        result = OTLPReceiver._parse_traces({"resourceSpans": []})
        self.assertEqual(result, [])

    def test_parse_single_span(self):
        """测试解析单个span"""
        data = {
            "resourceSpans": [{
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "my_service"}}]
                },
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "trace001",
                        "spanId": "span001",
                        "name": "handle_request",
                        "kind": 1,
                        "startTimeUnixNano": "1000000000000000000",
                        "endTimeUnixNano": "1500000000000000000",
                        "status": {"code": "STATUS_CODE_OK"},
                        "attributes": [
                            {"key": "http.method", "value": {"stringValue": "GET"}}
                        ],
                        "events": []
                    }]
                }]
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].trace_id, "trace001")
        self.assertEqual(spans[0].name, "handle_request")
        self.assertEqual(spans[0].service_name, "my_service")
        self.assertEqual(spans[0].kind, "SERVER")
        self.assertEqual(spans[0].status_code, "OK")
        self.assertEqual(spans[0].duration_ms, 500000000000.0)
        self.assertEqual(spans[0].attributes["http.method"], "GET")

    def test_parse_multiple_spans(self):
        """测试解析多个spans"""
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [
                        {"traceId": "t1", "spanId": "s1", "name": "span1", "kind": 0},
                        {"traceId": "t2", "spanId": "s2", "name": "span2", "kind": 2}
                    ]
                }]
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].name, "span1")
        self.assertEqual(spans[1].kind, "CLIENT")

    def test_parse_with_events(self):
        """测试解析带events的span"""
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1", "spanId": "s1", "name": "test",
                        "kind": 0,
                        "events": [{
                            "name": "checkpoint",
                            "timeUnixNano": "1200000000000000000",
                            "attributes": [
                                {"key": "event.key", "value": {"stringValue": "event_val"}}
                            ]
                        }]
                    }]
                }]
            }]
        }
        spans = OTLPReceiver._parse_traces(data)
        self.assertEqual(len(spans[0].events), 1)
        self.assertEqual(spans[0].events[0]["name"], "checkpoint")


class TestParseSingleSpan(unittest.TestCase):
    """测试单span解析"""

    def test_valid_span(self):
        """测试有效span"""
        data = {
            "traceId": "abc", "spanId": "def", "name": "test",
            "kind": 1,
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000",
            "status": {"code": "STATUS_CODE_ERROR", "message": "timeout"}
        }
        span = OTLPReceiver._parse_single_span(data, "svc")
        self.assertIsNotNone(span)
        self.assertEqual(span.status_code, "ERROR")
        self.assertEqual(span.status_message, "timeout")
        self.assertEqual(span.duration_ms, 1000.0)

    def test_empty_data(self):
        """测试空span数据"""
        span = OTLPReceiver._parse_single_span({}, "svc")
        self.assertIsNotNone(span)
        self.assertEqual(span.status_code, "UNSET")

    def test_int_attribute(self):
        """测试整数属性"""
        data = {
            "traceId": "", "spanId": "", "name": "", "kind": 0,
            "attributes": [{"key": "count", "value": {"intValue": 42}}]
        }
        span = OTLPReceiver._parse_single_span(data, "")
        self.assertEqual(span.attributes["count"], 42)

    def test_bool_attribute(self):
        """测试布尔属性"""
        data = {
            "traceId": "", "spanId": "", "name": "", "kind": 0,
            "attributes": [{"key": "ok", "value": {"boolValue": True}}]
        }
        span = OTLPReceiver._parse_single_span(data, "")
        self.assertTrue(span.attributes["ok"])


class TestOTLPReceiverInit(unittest.TestCase):
    """测试OTLPReceiver初始化"""

    def test_default_config(self):
        """测试默认配置"""
        receiver = OTLPReceiver()
        self.assertEqual(receiver.port, 4318)
        self.assertEqual(receiver.host, "0.0.0.0")
        self.assertFalse(receiver._running)

    def test_custom_config(self):
        """测试自定义配置"""
        receiver = OTLPReceiver(port=8080, host="127.0.0.1")
        self.assertEqual(receiver.port, 8080)
        self.assertEqual(receiver.host, "127.0.0.1")

    def test_callbacks_none(self):
        """测试初始回调为None"""
        receiver = OTLPReceiver()
        self.assertIsNone(receiver._span_callback)
        self.assertIsNone(receiver._health_callback)

    def test_set_span_callback(self):
        """测试设置span回调"""
        receiver = OTLPReceiver()
        callback = MagicMock()
        receiver.set_span_callback(callback)
        self.assertEqual(receiver._span_callback, callback)

    def test_set_health_callback(self):
        """测试设置健康检查回调"""
        receiver = OTLPReceiver()
        callback = MagicMock(return_value={"agent": "running"})
        receiver.set_health_callback(callback)
        self.assertEqual(receiver._health_callback, callback)


if __name__ == "__main__":
    unittest.main()
