"""
OTLP 接收模块
轻量级 OpenTelemetry Protocol (OTLP) HTTP 接收端
支持接收 OTLP/JSON 格式的 traces，提取 agent 状态信息
参考规范: https://opentelemetry.io/docs/specs/otlp/

端口: 4318 (OTLP/HTTP 标准端口)
端点: POST /v1/traces
"""

import json
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)



# OTLP Span Kind 映射
_SPAN_KIND_MAP = {0: "INTERNAL", 1: "SERVER", 2: "CLIENT", 3: "PRODUCER", 4: "CONSUMER"}
_NS_PER_SECOND = 1_000_000_000  # 纳秒 → 秒

@dataclass
class OTLPSpan:
    """从 OTLP trace 中提取的 span 信息"""
    trace_id: str
    span_id: str
    name: str
    service_name: str
    kind: str           # SPAN_KIND_INTERNAL, SPAN_KIND_CLIENT, etc.
    status_code: str    # OK, ERROR, UNSET
    status_message: str
    start_time: float   # Unix timestamp (seconds)
    end_time: float
    duration_ms: float
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: list = field(default_factory=list)


class OTLPReceiver:
    """
    OTLP HTTP 接收端
    
    用法:
        receiver = OTLPReceiver(port=4318)
        receiver.set_span_callback(my_callback)
        receiver.start()
        
        # 在 callback 中处理 span
        def my_callback(span: OTLPSpan):
            print(f"Service: {span.service_name}, Name: {span.name}")
    """
    
    def __init__(self, port: int = 4318, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._span_callback: Optional[Callable[[OTLPSpan], None]] = None
        self._health_callback: Optional[Callable[[], Dict]] = None
    
    def set_span_callback(self, callback: Callable[[OTLPSpan], None]):
        """设置 span 回调（每收到一个 span 触发一次）"""
        self._span_callback = callback
    
    def set_health_callback(self, callback: Callable[[], Dict]):
        """设置健康检查回调（返回当前 agent 状态摘要）"""
        self._health_callback = callback
    
    def start(self) -> bool:
        """启动 HTTP 接收端"""
        try:
            self._server = HTTPServer((self.host, self.port), 
                                       self._create_handler())
            self._running = True
            self._thread = threading.Thread(target=self._serve_loop, daemon=True)
            self._thread.start()
            logger.info(f"OTLP Receiver started on {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"OTLP Receiver start failed: {e}")
            return False
    
    def stop(self):
        """停止接收端"""
        self._running = False
        if self._server:
            self._server.shutdown()
            logger.info("OTLP Receiver stopped")
    
    def _serve_loop(self):
        """HTTP 服务循环"""
        while self._running:
            try:
                self._server.handle_request()
            except Exception as e:
                if self._running:
                    logger.error(f"OTLP request handling error: {e}")
    
    def _create_handler(self):
        """动态创建 HTTP Handler（闭包捕获 receiver 引用）"""
        receiver = self
        
        class OTLPHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                """处理 OTLP HTTP POST 请求"""
                if self.path == "/v1/traces":
                    self._handle_traces()
                elif self.path == "/v1/metrics":
                    self._handle_metrics()
                else:
                    self.send_error(404, "Unknown OTLP endpoint")
            
            def do_GET(self):
                """健康检查端点"""
                if self.path == "/health" or self.path == "/":
                    self._handle_health()
                else:
                    self.send_error(404)
            
            def _handle_traces(self):
                """解析 OTLP traces JSON 并提取 spans"""
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                    if content_length == 0:
                        self.send_error(400, "Empty body")
                        return
                    
                    body = self.rfile.read(content_length)
                    
                    # 支持 JSON 和 protobuf（先只处理 JSON）
                    content_type = self.headers.get("Content-Type", "")
                    if "json" in content_type or not content_type:
                        data = json.loads(body)
                    else:
                        # protobuf 格式暂不支持，返回 415
                        self.send_error(415, "Only JSON supported, use Content-Type: application/json")
                        return
                    
                    spans = self._parse_traces(data)
                    
                    for span in spans:
                        if receiver._span_callback:
                            try:
                                receiver._span_callback(span)
                            except Exception as e:
                                logger.error(f"Span callback error: {e}")
                    
                    # OTLP 标准成功响应
                    response = json.dumps({
                        "partialSuccess": {
                            "rejectedSpans": 0,
                            "errorMessage": ""
                        }
                    })
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(response.encode())
                    
                    logger.debug(f"Processed {len(spans)} spans")
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON: {e}")
                    self.send_error(400, f"Invalid JSON: {e}")
                except Exception as e:
                    logger.error(f"Traces processing error: {e}")
                    self.send_error(500, str(e))
            
            def _handle_metrics(self):
                """Metrics 端点（预留，暂不处理）"""
                response = json.dumps({"partialSuccess": {"rejectedMetrics": 0}})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.encode())
            
            def _handle_health(self):
                """健康检查响应"""
                status = {"status": "ok", "receiver": "otlp", "port": receiver.port}
                if receiver._health_callback:
                    try:
                        status.update(receiver._health_callback())
                    except Exception as e:
                        logger.debug(f"健康检查回调异常: {e}")
                response = json.dumps(status)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.encode())
            
            def log_message(self, format, *args):
                """覆盖默认日志，使用 logger"""
                logger.debug(f"OTLP HTTP: {format % args}")
        
        return OTLPHandler
    
    @staticmethod
    def _parse_traces(data: dict) -> list:
        """
        从 OTLP JSON 格式中解析 traces → spans
        
        OTLP JSON 格式:
        {
          "resourceSpans": [{
            "resource": {"attributes": [...]},
            "scopeSpans": [{
              "scope": {"name": "...", "version": "..."},
              "spans": [...]
            }]
          }]
        }
        """
        spans = []
        
        for resource_span in data.get("resourceSpans", []):
            # 提取 service.name
            resource = resource_span.get("resource", {})
            service_name = ""
            for attr in resource.get("attributes", []):
                if attr.get("key") == "service.name":
                    service_name = attr.get("value", {}).get("stringValue", "")
            
            for scope_span in resource_span.get("scopeSpans", []):
                for span_data in scope_span.get("spans", []):
                    span = OTLPReceiver._parse_single_span(span_data, service_name)
                    if span:
                        spans.append(span)
        
        return spans
    
    @staticmethod
    def _parse_single_span(data: dict, service_name: str) -> Optional[OTLPSpan]:
        """解析单个 span"""
        try:
            # OTLP 时间戳是纳秒字符串
            start_ns = int(data.get("startTimeUnixNano", "0"))
            end_ns = int(data.get("endTimeUnixNano", "0"))
            
            start_time = start_ns / _NS_PER_SECOND if start_ns else 0
            end_time = end_ns / _NS_PER_SECOND if end_ns else 0
            duration_ms = (end_time - start_time) * 1000 if start_ns and end_ns else 0
            
            # 状态
            status = data.get("status", {})
            status_code = status.get("code", "STATUS_CODE_UNSET")
            # 简化状态码
            if "OK" in status_code:
                status_code = "OK"
            elif "ERROR" in status_code:
                status_code = "ERROR"
            else:
                status_code = "UNSET"
            
            # 属性
            attributes = {}
            for attr in data.get("attributes", []):
                key = attr.get("key", "")
                value = attr.get("value", {})
                # 取第一个非空值
                for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                    if vtype in value:
                        attributes[key] = value[vtype]
                        break
            
            # 事件
            events = []
            for event_data in data.get("events", []):
                event = {
                    "name": event_data.get("name", ""),
                    "timestamp": int(event_data.get("timeUnixNano", "0")) / _NS_PER_SECOND,
                    "attributes": {}
                }
                for attr in event_data.get("attributes", []):
                    for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                        if vtype in attr.get("value", {}):
                            event["attributes"][attr["key"]] = attr["value"][vtype]
                            break
                events.append(event)
            
            # Span Kind
            kind = _SPAN_KIND_MAP.get(data.get("kind", 0), "INTERNAL")
            
            return OTLPSpan(
                trace_id=data.get("traceId", ""),
                span_id=data.get("spanId", ""),
                name=data.get("name", ""),
                service_name=service_name,
                kind=kind,
                status_code=status_code,
                status_message=status.get("message", ""),
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                attributes=attributes,
                events=events
            )
        except Exception as e:
            logger.warning(f"Failed to parse span: {e}")
            return None


# ============ 独立测试 ============

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    def on_span(span: OTLPSpan):
        print(f"[Span] service={span.service_name} name={span.name} "
              f"status={span.status_code} duration={span.duration_ms:.1f}ms")
        if span.attributes:
            print(f"  attrs: {span.attributes}")
    
    receiver = OTLPReceiver(port=4318)
    receiver.set_span_callback(on_span)
    receiver.start()
    
    print("OTLP Receiver running on :4318, POST /v1/traces to test")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        receiver.stop()
