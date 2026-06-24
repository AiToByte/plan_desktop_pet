# OTLP 遥测集成

> 源文件: `pc_monitor/modules/otlp_receiver.py`

本文档描述桌面宠物项目中 OTLP（OpenTelemetry Protocol）遥测接收器的实现细节。该模块提供一个轻量级的 HTTP 服务端，接收 Claude Code 等 AI Agent 发出的 OTLP/JSON 格式 traces，提取 span 信息用于状态监控。

---

## 一、OTLP/HTTP 协议概述

### 1.1 什么是 OTLP

OTLP 是 OpenTelemetry 项目定义的标准遥测数据传输协议，用于传输 traces（链路追踪）、metrics（指标）和 logs（日志）三种信号。

### 1.2 协议特性

| 特性 | 说明 |
|------|------|
| 传输方式 | HTTP POST（本项目实现）或 gRPC |
| 数据格式 | JSON 或 Protobuf（本项目仅支持 JSON） |
| 标准端口 | **4318**（HTTP）、4317（gRPC） |
| Traces 端点 | `POST /v1/traces` |
| Metrics 端点 | `POST /v1/metrics` |
| 健康检查 | `GET /health` 或 `GET /` |

### 1.3 在本项目中的角色

Claude Code 支持通过 OTLP 导出其内部 span 数据（包括工具调用、模型推理等）。桌面宠物的 PC 端运行一个 OTLP 接收器，捕获这些 span 数据，从中提取 Agent 的工作状态、耗时等信息，最终展示在托盘面板上。

---

## 二、接收器实现

### 2.1 架构设计

`OTLPReceiver` 类基于 Python 标准库 `http.server.HTTPServer` 实现，运行在独立守护线程中，不阻塞主程序：

```
OTLPReceiver
    |
    +-- HTTPServer (host=0.0.0.0, port=4318)
    |       |
    |       +-- OTLPHandler (动态创建的内部类)
    |               |
    |               +-- do_POST() → /v1/traces, /v1/metrics
    |               +-- do_GET()  → /health
    |
    +-- threading.Thread (daemon=True)
    |       |
    |       +-- _serve_loop() → server.handle_request()
    |
    +-- _span_callback: Callable[[OTLPSpan], None]
    +-- _health_callback: Callable[[], Dict]
    +-- _auth_token: Optional[str]
```

### 2.2 生命周期管理

**启动流程**：

```python
def start(self) -> bool:
    self._server = HTTPServer((self.host, self.port), self._create_handler())
    self._running = True
    self._thread = threading.Thread(target=self._serve_loop, daemon=True)
    self._thread.start()
```

- `HTTPServer` 绑定到 `0.0.0.0:4318`，监听所有网络接口
- 服务循环在 daemon 线程中运行，主程序退出时自动终止
- 返回 `bool` 指示启动是否成功（端口被占用等情况会返回 False）

**停止流程**：

```python
def stop(self):
    self._running = False
    if self._server:
        self._server.shutdown()
```

设置 `_running = False` 并调用 `server.shutdown()` 优雅关闭 HTTP 服务。

### 2.3 动态 Handler 创建

由于 `BaseHTTPRequestHandler` 的设计限制（每个请求创建新实例，无法直接注入依赖），采用闭包模式创建 Handler 类：

```python
def _create_handler(self):
    receiver = self  # 闭包捕获 receiver 引用

    class OTLPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/v1/traces":
                self._handle_traces()
            # ...

    return OTLPHandler
```

通过闭包变量 `receiver`，Handler 内部可以访问 `OTLPReceiver` 的回调函数和配置。

### 2.4 回调机制

接收器通过两个回调函数与外部模块解耦：

| 回调 | 签名 | 触发时机 |
|------|------|---------|
| `set_span_callback` | `(OTLPSpan) -> None` | 每解析出一个 span 时调用 |
| `set_health_callback`() -> Dict` | 健康检查端点被访问时调用 |

这种设计使接收器不依赖具体的业务逻辑，调用方可以自由决定如何处理 span 数据。

---

## 三、Trace JSON 解析

### 3.1 OTLP JSON 结构

OTLP traces 的 JSON 格式采用三层嵌套结构：

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "claude-code"}}
        ]
      },
      "scopeSpans": [
        {
          "scope": {"name": "claude-code", "version": "1.0.0"},
          "spans": [
            {
              "traceId": "abc123...",
              "spanId": "def456...",
              "name": "tool_call",
              "kind": 1,
              "startTimeUnixNano": "1718956800000000000",
              "endTimeUnixNano": "1718956801500000000",
              "status": {"code": "STATUS_CODE_OK"},
              "attributes": [...],
              "events": [...]
            }
          ]
        }
      ]
    }
  ]
}
```

### 3.2 解析流程

`_parse_traces()` 静态方法负责逐层解析：

```
data (JSON root)
  → resourceSpans[]
      → 提取 resource.attributes 中的 service.name
      → scopeSpans[]
          → spans[]
              → _parse_single_span(span_data, service_name)
```

### 3.3 单个 Span 解析

`_parse_single_span()` 方法从原始 span 数据中提取结构化信息：

**时间戳转换**：OTLP 使用纳秒级 Unix 时间戳（字符串格式），需要转换为秒：

```python
start_ns = int(data.get("startTimeUnixNano", "0"))
start_time = start_ns / 1_000_000_000  # 纳秒 → 秒
duration_ms = (end_time - start_time) * 1000
```

**状态码简化**：OTLP 定义的状态码较长，解析时简化为三种：

| 原始值 | 简化值 |
|--------|--------|
| `STATUS_CODE_OK` | `OK` |
| `STATUS_CODE_ERROR` | `ERROR` |
| `STATUS_CODE_UNSET` / 其他 | `UNSET` |

**属性提取**：遍历 `attributes` 数组，提取 key-value 对。每个属性的值可能是多种类型之一：

```python
for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
    if vtype in value:
        attributes[key] = value[vtype]
        break
```

取第一个非空值类型。

**Span Kind 映射**：

| 数值 | 含义 |
|------|------|
| 0 | INTERNAL |
| 1 | SERVER |
| 2 | CLIENT |
| 3 | PRODUCER |
| 4 | CONSUMER |

### 3.4 OTLPSpan 数据结构

解析结果封装为 `OTLPSpan` 数据类：

```python
@dataclass
class OTLPSpan:
    trace_id: str          # 链路追踪 ID
    span_id: str           # Span ID
    name: str              # Span 名称（如 "tool_call", "llm_completion"）
    service_name: str      # 来源服务名（如 "claude-code"）
    kind: str              # INTERNAL / SERVER / CLIENT / PRODUCER / CONSUMER
    status_code: str       # OK / ERROR / UNSET
    status_message: str    # 状态附加信息
    start_time: float      # 开始时间（Unix 秒）
    end_time: float        # 结束时间（Unix 秒）
    duration_ms: float     # 持续时间（毫秒）
    attributes: Dict       # 自定义属性
    events: list           # 事件列表
```

---

## 四、ThinkingChainTracker 状态分类

虽然 `otlp_receiver.py` 本身不包含 `ThinkingChainTracker` 的实现，但它是 OTLP 数据的消费入口。下游模块（如 `agent_monitor.py`）通过 span 回调接收 `OTLPSpan`，并从中推断 Agent 的思考状态。

### 4.1 典型状态分类

根据 span 的 `name`、`attributes` 和 `duration_ms`，可以推断以下 Agent 状态：

| 状态 | 判断依据 |
|------|---------|
| Thinking | span name 包含 "think" 或 "reasoning"，持续时间较长 |
| Tool Calling | span name 包含 "tool"，attributes 中有工具名称 |
| Generating | span name 包含 "generate" 或 "completion" |
| Idle | 无活跃 span，或最后一个 span 已结束 |
| Error | status_code == "ERROR" |

### 4.2 状态转换

```
Idle ──(新span开始)──> Thinking / Tool Calling / Generating
    │                                    │
    └──(span结束)────────────────────────┘
                                │
                                v
                    Error (status_code == ERROR)
```

---

## 五、Claude Code OTLP 配置方法

要让 Claude Code 向本项目的接收器发送 OTLP 数据，需要配置以下环境变量：

### 5.1 环境变量配置

```bash
# 启用 OTLP 导出
export CLAUDE_CODE_ENABLE_OTLP=1

# 设置 OTLP HTTP 端点（默认端口 4318）
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

# 可选：设置服务名称
export OTEL_SERVICE_NAME=claude-code
```

### 5.2 Windows PowerShell 配置

```powershell
$env:CLAUDE_CODE_ENABLE_OTLP = "1"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
$env:OTEL_SERVICE_NAME = "claude-code"
```

### 5.3 验证连接

启动 OTLP 接收器后，可以通过 curl 发送测试请求：

```bash
curl -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans": []}'
```

返回 `{"partialSuccess": {"rejectedSpans": 0, "errorMessage": ""}}` 表示接收器工作正常。

---

## 六、认证机制

### 6.1 Bearer Token 认证

接收器支持可选的 Token 认证，防止未授权的客户端向端口发送数据：

```python
self._auth_token: Optional[str] = None
```

### 6.2 认证流程

当 `_auth_token` 不为 None 时，所有 `/v1/traces` 请求必须携带有效的 Authorization 头：

```python
if receiver._auth_token:
    auth_header = self.headers.get("Authorization", "")
    # 支持两种格式：
    #   "Bearer <token>"  ← 标准格式
    #   "<token>"         ← 兼容格式
    token = auth_header.replace("Bearer ", "").strip() if auth_header else ""
    if token != receiver._auth_token:
        logger.warning(f"OTLP auth failed from {self.client_address[0]}")
        self.send_error(401, "Unauthorized")
        return
```

### 6.3 安全注意事项

| 项目 | 说明 |
|------|------|
| 传输层 | 当前为 HTTP 明文，生产环境建议使用 HTTPS 或放在反向代理后面 |
| Token 存储 | Token 应从环境变量或配置文件读取，不应硬编码 |
| 端口暴露 | 默认绑定 `0.0.0.0`，仅在可信网络中使用 |
| 速率限制 | 当前未实现，高流量场景需考虑 |
| 健康检查 | `/health` 端点不受 Token 认证保护 |

### 6.4 响应格式

认证失败时返回标准 HTTP 401：

```http
HTTP/1.1 401 Unauthorized
```

认证成功时返回 OTLP 标准响应：

```json
{
  "partialSuccess": {
    "rejectedSpans": 0,
    "errorMessage": ""
  }
}
```

---

## 七、Metrics 端点（预留）

`/v1/metrics` 端点已预留实现框架，当前返回空的成功响应：

```python
def _handle_metrics(self):
    response = json.dumps({"partialSuccess": {"rejectedMetrics": 0}})
    # ... 200 OK
```

这是为了满足 OTLP 客户端的探测行为——某些 OpenTelemetry SDK 在初始化时会先发送 metrics 请求确认端点可用。

---

## 数据流总览

```
Claude Code (OTLP Exporter)
        |
        |  HTTP POST /v1/traces (JSON)
        v
  OTLPReceiver (port 4318)
        |
        +-- Token 认证检查
        |
        +-- JSON 解析
        |       |
        |       +-- resourceSpans → service.name
        |       +-- scopeSpans → spans[]
        |       +-- _parse_single_span() → OTLPSpan
        |
        +-- span_callback(span)  ──→  agent_monitor.py (状态推断)
        |
        +-- 200 OK (partialSuccess)
```
