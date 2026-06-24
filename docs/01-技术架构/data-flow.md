# 数据流转链路详解

> 本文档完整追踪桌面电子宠物系统中每一条数据流的生命周期，从PC端数据源采集，
> 经TCP帧协议传输，到ESP32双缓冲渲染的全链路。每条链路包含数据格式、关键代码引用和时序分析。

---

## 一、数据流总览

### 1.1 系统架构ASCII图

```
+=====================================================================+
|                        PC 端 (Python)                                |
|                                                                     |
|  +-------------------+  +----------------+  +-------------------+   |
|  | agent_monitor.py  |  | token_stats.py |  |   weather.py      |   |
|  | psutil进程扫描    |  | JSONL增量解析   |  | OpenWeatherMap API|   |
|  | CPU滑动窗口判断   |  | LogTailer追踪   |  | 自适应刷新率      |   |
|  +--------+----------+  +-------+--------+  +--------+----------+   |
|           |                     |                     |             |
|           v                     v                     v             |
|  +----------------------------------------------------------+      |
|  |              main.py: _periodic_update()                  |      |
|  |   send_agent_update (2s) | token (30s) | weather (自适应) |      |
|  +--------------------------+------------------+-------------+      |
|           |                     |                     |             |
|           v                     v                     v             |
|  +----------------------------------------------------------+      |
|  |           communication.py: send_message()                |      |
|  |   DeviceMessage → json.dumps → "LEN:<len>\n<payload>"     |      |
|  |   异步队列 (Queue[64]) → _send_queue_worker → TCP sendall |      |
|  +--------------------------+--------------------------------+      |
|           |                                                          |
+===========|==========================================================+
            |  WiFi TCP (端口 19876)
            |  帧协议: "LEN:<len>\n<json_payload>"
            v
+=====================================================================+
|                     ESP32-S3 (FreeRTOS 双核)                         |
|                                                                     |
|  Core 0: commTask                                                  |
|  +----------------------------------------------------------+      |
|  |  comm_manager.cpp: update()                               |      |
|  |  FRAME_IDLE → FRAME_READ_LEN → FRAME_READ_BODY            |      |
|  |  → processData() → _hasNewData=true                       |      |
|  +--------------------------+--------------------------------+      |
|           |                                                          |
|           v                                                          |
|  +----------------------------------------------------------+      |
|  |  main.cpp: parseServerData(json)                          |      |
|  |  type路由: status|token|weather|pixel_data|thinking_status |      |
|  |  → g_displayBuf[backIdx] 写入 → atomic swap               |      |
|  +--------------------------+--------------------------------+      |
|           |  双缓冲 (g_displayBuf[2] + atomic g_frontIdx)           |
|           v                                                          |
|  Core 1: renderTask                                                |
|  +----------------------------------------------------------+      |
|  |  display_manager.cpp: update(data)                        |      |
|  |  drawStatusBar → drawWeatherPanel → drawTokenPanel         |      |
|  |  → drawThinkingIndicator → drawFaceAnimation              |      |
|  |  → sprite.pushSprite → LCD DMA传输                        |      |
|  +----------------------------------------------------------+      |
|                                                                     |
|  传感器反馈环路:                                                     |
|  +----------------+  +----------------+  +----------------+        |
|  | BH1750 光照    |  | 触摸+接近感应   |  | DRV2605L 触觉  |        |
|  | → EMA → PWM    |  | → 手势识别      |  | → 振动反馈     |        |
|  +----------------+  +----------------+  +----------------+        |
+=====================================================================+
```

### 1.2 数据流编号索引

| 编号 | 链路名称 | 数据源 | 传输协议 | 更新频率 | 终点显示 |
|------|----------|--------|----------|----------|----------|
| 1 | Agent状态 → 屏幕 | psutil进程扫描 | TCP帧 | 2秒 | 状态栏+表情 |
| 2 | Token统计 → 屏幕 | JSONL日志文件 | TCP帧 | 30秒 | Token面板 |
| 3 | 天气数据 → 屏幕 | OpenWeatherMap API | TCP帧 | 10/30/60分钟 | 天气面板 |
| 4 | 思考链 → 屏幕 | OTLP HTTP 4318 | TCP帧 | 200ms防抖 | 思考指示器 |
| 5 | 像素动画 → 屏幕 | PNG/GIF文件 | TCP帧(base64) | 按需 | 全屏像素 |
| 6 | 传感器 → 系统 | BH1750/触摸/DRV2605L | GPIO/I2C | 实时 | 背光/振动/唤醒 |

---

## 二、链路1: Agent状态 → 屏幕显示

### 2.1 数据采集: agent_monitor.py

**入口函数**: `AgentMonitor.get_state()` (agent_monitor.py:246)

```
psutil.process_iter(['pid','name','cmdline'])
    │
    ├── 遍历系统进程列表，匹配 process_names (默认: ["claudecode","codex"])
    ├── 命中 → 缓存 PID (self._cached_proc)
    │         ↓
    │   proc.cpu_percent(interval=0)   ← 非阻塞调用
    │         ↓
    │   proc.oneshot():
    │     cpu_percent = proc.cpu_percent()
    │     memory_mb   = proc.memory_info().rss / 1024 / 1024
    │     uptime_sec  = time.time() - proc.create_time()
    │
    └── 未命中 → AgentStatus.OFFLINE
```

**PID缓存优化** (agent_monitor.py:253-262): 首次全量遍历后缓存进程对象，
后续仅验证PID存活 + 进程名一致性（微秒级），避免每2秒遍历全部进程。

### 2.2 CPU状态判断: _analyze_cpu_pattern()

**核心逻辑** (agent_monitor.py:122-157):

```
proc.cpu_percent(interval=0)  ← 非阻塞，返回自上次调用以来的CPU%
         ↓
self._cpu_history.append(cpu_percent)  ← deque(maxlen=5) 滑动窗口
         ↓
avg_cpu = sum(history) / len(history)  ← 5次采样平均值
         ↓
    ┌─────────────────────────────────────────────────┐
    │  avg_cpu > 30.0%  →  AgentStatus.WORKING        │
    │  avg_cpu > 3.0%   →  AgentStatus.AUTHORIZING     │
    │  avg_cpu <= 3.0%  →  _idle_streak++              │
    │    连续 >= 6次     →  AgentStatus.IDLE            │
    │    连续 < 6次      →  AgentStatus.AUTHORIZING     │
    └─────────────────────────────────────────────────┘
```

**阈值常量**:
- `CPU_THRESHOLD_WORKING = 30.0` — 高CPU表示Agent正在生成代码
- `CPU_THRESHOLD_AUTHORIZING = 3.0` — 低CPU表示等待用户授权/输入
- `IDLE_CONFIRM_COUNT = 6` — 连续6次低CPU确认空闲 (6 x 2s = 12秒)

### 2.3 JSONL授权检测: _check_auth_jsonl()

当CPU判定为 `AUTHORIZING` 时，进一步扫描Claude项目目录下的JSONL文件确认：

```
~/.claude/projects/*/*/*/*.jsonl  ← 最多3层深度搜索
         ↓
按修改时间排序，取最新文件
         ↓
f.seek(-8192, os.SEEK_END)  ← 只读末尾8KB，避免大文件全量扫描
         ↓
逐行解析JSONL:
  ├── msg.type == "permission_request"  → auth检测命中
  ├── content含 "permission" + "pending" → auth检测命中
  └── tool_use.name含 "AskUser"         → auth检测命中
```

### 2.4 消息组装: main.py _send_status_update()

**源码引用**: main.py:227-253

```python
state = self.agent_monitor.get_state()
msg = DeviceMessage(
    msg_type="status",
    data={
        "status": state.status.value,   # "idle"|"working"|"auth"|"offline"
        "process": state.process_name,   # 进程名字符串
        "cpu": round(state.cpu_percent, 1),
        "memory": round(state.memory_mb, 1),
        "uptime": int(state.uptime_seconds)
    },
    timestamp=time.time()
)
self.communication.send_message(msg)
```

### 2.5 TCP帧编码: communication.py

**帧格式定义** (communication.py:473):

```
原始JSON:
  {"type":"status","data":{"status":"working","process":"claudecode","cpu":45.2,...},"ts":1234567890.123}
         ↓
编码:
  "LEN:<json_bytes_length>\n<json_payload>"
         ↓
实际线上数据:
  LEN:128\n{"type":"status","data":{"status":"working","process":"claudecode","cpu":45.2,"memory":128.5,"uptime":3600},"ts":1234567890.123}
```

**发送机制** (communication.py:437-451):
1. `send_message()` 非阻塞入队: `self._send_queue.put_nowait(msg)` (Queue[maxsize=64])
2. 队列满时丢弃最旧消息腾出空间
3. `_send_queue_worker` 后台线程从队列取消息，调用 `_flush_send()` 同步发送
4. `_flush_send()` 内: `json.dumps` → 帧编码 → `socket.sendall(frame.encode('utf-8'))`

### 2.6 ESP32帧接收: comm_manager.cpp

**状态机** (comm_manager.cpp:116-228):

```
TCP数据到达 (_client.available() > 0)
         ↓
_client.read(_readBuf, ...)  ← 非阻塞批量读取到4KB缓冲区
         ↓
逐字节状态机:
┌─────────────────────────────────────────────────────────┐
│ FRAME_IDLE                                              │
│   'L' → _lenBuffer="L", → FRAME_READ_LEN              │
│   '{' → _frameBuffer="{", → FRAME_LEGACY_LINE (兼容)   │
├─────────────────────────────────────────────────────────┤
│ FRAME_READ_LEN                                          │
│   累积字符到 _lenBuffer，直到 '\n'                       │
│   解析 "LEN:NNNN" → _expectedLen                        │
│   校验: 0 < expectedLen <= 256*1024                     │
│   → FRAME_READ_BODY                                     │
├─────────────────────────────────────────────────────────┤
│ FRAME_READ_BODY (批量优化路径)                            │
│   直接从 _readBuf 拷贝 remaining 字节到 _frameBuffer    │
│   跳过逐字符状态机，减少循环开销                          │
│   _frameBuffer.length() >= _expectedLen:                │
│     → processData(_frameBuffer)                         │
│     → FRAME_IDLE                                        │
└─────────────────────────────────────────────────────────┘
```

**processData()** (comm_manager.cpp:238-250): `data.trim()` → 存入 `_lastData` → 设置 `_hasNewData = true`

### 2.7 JSON解析与双缓冲写入: main.cpp

**parseServerData()** (main.cpp:629-919):

```
comm.getData() → json字符串
         ↓
Phase 1: StaticJsonDocument<64> 快速提取 type 字段
         ↓
type == "status":
  Phase 2: StaticJsonDocument<256> + Filter 精确解析
  只提取: data.status, data.process, data.cpu, data.memory, data.uptime
         ↓
  双缓冲写入 (main.cpp:657-668):
    int front = g_frontIdx.load(memory_order_acquire);
    int backIdx = 1 - front;
    g_displayBuf[backIdx] = g_displayBuf[front];     // 复制front→back
    g_displayBuf[backIdx].agent.status = parseStatus(data["status"]);
    g_displayBuf[backIdx].agent.processName = data["process"];
    g_displayBuf[backIdx].agent.cpuPercent = data["cpu"];
    g_displayBuf[backIdx].agent.memoryMB = data["memory"];
    g_displayBuf[backIdx].agent.uptimeSeconds = data["uptime"];
    g_frontIdx.store(backIdx, memory_order_release);  // 原子交换
```

**parseStatus()** (main.cpp:921-926): 字符串→枚举映射:
- `"idle"` → `STATUS_IDLE`
- `"working"` → `STATUS_WORKING`
- `"auth"` → `STATUS_AUTH`
- 其他 → `STATUS_OFFLINE`

### 2.8 渲染: display_manager.cpp

**renderTask** (main.cpp:217-461) 在Core 1循环:

```
int frontIdx = g_frontIdx.load(memory_order_acquire);
localData = g_displayBuf[frontIdx];  // 读取front buffer到本地副本
         ↓
display.update(localData):
  ├── drawStatusBar(data.agent)        ← 状态灯(呼吸效果) + 进程名 + CPU/MEM
  ├── drawThinkingIndicator(data)      ← 思考链状态
  ├── drawWeatherPanel(data.weather)   ← 天气面板
  ├── drawTokenPanel(data.tokens)      ← Token面板
  └── drawFaceAnimation()              ← 32x32像素表情
         ↓
_sprite.pushSprite(&_lcd, 0, 0)  ← DMA传输到LCD
```

**drawStatusBar()** (display_manager.cpp:283-330):
- 状态圆点: `fillCircle(18, y+15, 8, dimColor)` — 使用 `fastSin()` 驱动呼吸灯效果
- CPU/MEM数值: 弹簧物理缓动 (`_springCpu.current()`, `_springMem.current()`) 消除数值跳变

**表情切换** (display_manager.cpp:131-136):
- `STATUS_IDLE` → `FACE_HAPPY` (黄色笑脸)
- `STATUS_WORKING` → `FACE_WORKING` (橙色专注脸，冒汗+思考泡泡)
- `STATUS_AUTH` → `FACE_AUTH` (粉红紧张脸，大眼睛+颤抖嘴)
- `STATUS_OFFLINE` → `FACE_OFFLINE` (灰色睡眠脸，Zzz动画)

### 2.9 时序分析

| 阶段 | 耗时 | 说明 |
|------|------|------|
| psutil进程扫描 | ~1-5ms | PID缓存命中时<0.1ms |
| CPU采样 | 0ms | 非阻塞调用(interval=0) |
| JSONL扫描 | ~2-10ms | 只读末尾8KB |
| json.dumps | <1ms | ~128字节payload |
| TCP sendall | ~0.5-2ms | 局域网RTT |
| ESP32帧解析 | ~1-3ms | ArduinoJson过滤解析 |
| 双缓冲swap | <0.1ms | atomic store |
| LCD渲染+DMA | ~5-10ms | 240x240 RGB565 |
| **端到端典型延迟** | **~10-30ms** | 从psutil到屏幕像素 |

---

## 三、链路2: Token统计 → 屏幕显示

### 3.1 数据采集: token_stats.py

**LogTailer增量读取** (token_stats.py:41-94):

```
LogTailer._file_states = {
    "path/to/file.jsonl": {"position": 12345, "inode": 67890}
}
         ↓
read_new_lines(file_path):
  ├── 首次读取: f.seek(max(0, size - 10*1024))  ← 从末尾10KB开始
  ├── 文件轮转: inode变化 → position=0
  ├── 文件截断: size < position → position=0
  └── 增量读取: f.seek(position) → 逐行读取 → 更新position
```

**JSONL解析** (_parse_log_line, token_stats.py:186-209):

```python
# 优先JSONL格式 (Claude CLI输出)
obj = json.loads(line)
usage = obj.get("message", {}).get("usage", {})
→ {"input_tokens": int, "output_tokens": int}

# fallback: 正则匹配纯文本 (预编译模式)
r'tokens?:\s*input[=:]\s*(\d+)\s*output[=:]\s*(\d+)'
r'prompt_tokens?[=:]\s*(\d+).*?completion_tokens?[=:]\s*(\d+)'
```

**费用估算** (token_stats.py:278-280):

```python
pricing = {"input": 3.0, "output": 15.0}  # USD per 1M tokens (Sonnet默认)
cost = (total_input * 3.0 + total_output * 15.0) / 1_000_000
```

### 3.2 定时发送: main.py _send_token_update()

**触发条件** (main.py:333-335): `now - self._last_token_update >= token_interval` (默认30秒)

```python
stats = self.token_tracker.get_stats()  # 内部有10秒缓存TTL
msg = DeviceMessage(
    msg_type="token",
    data={
        "input": stats.total_input_tokens,
        "output": stats.total_output_tokens,
        "requests": stats.total_requests,
        "hour": stats.tokens_last_hour,
        "cost": round(stats.estimated_cost_usd, 2)
    }
)
```

### 3.3 ESP32解析: main.cpp parseServerData()

**过滤解析** (main.cpp:678-705):

```cpp
// 使用Filter只提取需要的字段，减少内存占用
StaticJsonDocument<256> filter;
filter["data"]["input"] = true;
filter["data"]["output"] = true;
filter["data"]["requests"] = true;
filter["data"]["hour"] = true;
filter["data"]["cost"] = true;

// 双缓冲写入
g_displayBuf[backIdx].tokens.inputTokens = data["input"];
g_displayBuf[backIdx].tokens.outputTokens = data["output"];
g_displayBuf[backIdx].tokens.totalRequests = data["requests"];
g_displayBuf[backIdx].tokens.hourTokens = data["hour"];
g_displayBuf[backIdx].tokens.costUSD = data["cost"];
```

### 3.4 显示渲染: drawTokenPanel()

**源码引用**: display_manager.cpp:370-407

```
面板区域: y=142, 高度45px
┌────────────────────────────────┐
│ Tokens: [弹簧缓动数值]  $0.35  │  ← 第一行: 总Token数 + 费用
│ Req: 42               1h:2500 │  ← 第二行: 请求次数 + 1小时Token
└────────────────────────────────┘
```

- Token总数使用 `_springTokens.current()` 弹簧缓动，死区50（大数不抖动，避免频繁重绘）
- 费用使用橙色 (`FACE_ORANGE`) 高亮显示

### 3.5 时序分析

| 阶段 | 耗时 | 说明 |
|------|------|------|
| LogTailer增量读取 | ~5-20ms | 只读新增行 |
| JSONL解析 | ~1-5ms | 预编译正则 |
| json.dumps+TCP | ~1-3ms | ~80字节payload |
| ESP32解析+渲染 | ~5-10ms | 过滤解析+面板绘制 |
| **端到端典型延迟** | **~15-40ms** | 每30秒触发一次 |

---

## 四、链路3: 天气数据 → 屏幕显示

### 4.1 数据采集: weather.py

**自适应刷新率** (weather.py:105-111):

```python
def _get_effective_interval(self) -> int:
    if self._agent_status == "working":
        return 600    # 10分钟 (工作中频繁更新)
    elif self._agent_status in ("idle", "offline"):
        return 3600   # 1小时 (空闲时省API配额)
    return 1800        # 30分钟 (默认)
```

**API请求** (weather.py:159-178):

```python
params = {
    "q": self.city,          # 城市名
    "appid": self.api_key,   # OpenWeatherMap API Key
    "units": "metric",       # 摄氏度
    "lang": "zh_cn"          # 中文描述
}
response = self._session.get(
    "https://api.openweathermap.org/data/2.5/weather",
    params=params, timeout=10
)
```

**降级策略**: API失败 → 返回本地缓存 → 缓存也无 → 返回模拟数据 (22度, 晴)

### 4.2 图标映射

**ICON_MAP** (weather.py:62-81) — OpenWeatherMap图标代码到ESP32显示名称:

| API图标代码 | ESP32图标名 | 描述 |
|-------------|-------------|------|
| 01d | sun | 晴天 |
| 01n | moon | 晴夜 |
| 02d | cloud_sun | 少云 |
| 03d/03n | cloud | 多云 |
| 04d/04n | clouds | 阴天 |
| 09d/09n | rain_light | 小雨 |
| 10d/10n | rain | 雨 |
| 11d/11n | thunder | 雷暴 |
| 13d/13n | snow | 雪 |
| 50d/50n | fog | 雾 |

### 4.3 ESP32解析与渲染

**JSON解析** (main.cpp:706-737): Filter只提取 `city/temp/feels_like/humidity/desc/icon/wind`

**drawWeatherPanel()** (display_manager.cpp:332-368):

```
面板区域: y=72, 高度65px
┌────────────────────────────────┐
│ [天气图标]  22.5C              │  ← 图标+大号温度(弹簧缓动)
│             晴                 │  ← 天气描述
│             H:45%   W:3.5m/s  │  ← 湿度+风速
│            北京                │  ← 城市名(底部居中)
└────────────────────────────────┘
```

**天气图标绘制** — 11种像素风格图标 (20x20px):
- `drawIconSun()`: 中心圆 + 8方向旋转光线
- `drawIconRain()`: 暗色云 + 斜线雨滴(风效果)
- `drawIconThunder()`: 暗色云 + 闪烁黄色闪电
- `drawIconSnow()`: 白色云 + 十字雪花缓慢飘落
- 其他图标详见 display_manager.cpp:682-882

**温度弹簧缓动** (display_manager.cpp:124):
```cpp
_springTemp.setTarget(data.weather.temperature);
// 弹簧参数: stiffness=0.03, damping=0.85, deadzone=0.3°C
// 效果: 温度变化<0.3°C时不重绘，避免微小波动导致频繁刷新
```

### 4.4 时序分析

| 阶段 | 耗时 | 说明 |
|------|------|------|
| HTTP API请求 | ~200-2000ms | 取决于网络，有10s超时 |
| JSON解析 | <1ms | |
| 图标名映射 | <1ms | dict查找 |
| TCP传输 | ~1-3ms | ~150字节payload |
| ESP32解析+渲染 | ~5-15ms | 图标绘制最复杂 |
| **端到端典型延迟** | **~210-2020ms** | 主要瓶颈在API网络 |
| **触发周期** | 10/30/60分钟 | 自适应Agent状态 |

---

## 五、链路4: 思考链遥测 → 屏幕显示

### 5.1 数据源: Claude Code OTLP Spans

Claude Code Agent在运行时产生OpenTelemetry spans，通过HTTP OTLP协议发送到PC端。

**OTLP接收**: main.py `_otlp_receiver = OTLPReceiver(port=4318)` 监听HTTP 4318端口

**Span分类** (thinking_chain.py:55-66):

```python
_SPAN_STATE_MAP = {
    "think":        ThinkingState.THINKING,
    "thinking":     ThinkingState.THINKING,
    "reasoning":    ThinkingState.THINKING,
    "plan":         ThinkingState.THINKING,
    "tool_call":    ThinkingState.TOOL_CALL,
    "tool":         ThinkingState.TOOL_CALL,
    "respond":      ThinkingState.RESPONDING,
    "response":     ThinkingState.RESPONDING,
    "generate":     ThinkingState.RESPONDING,
}
```

### 5.2 防抖机制

**源码引用**: thinking_chain.py:75

```python
self._debounce_ms: float = 200.0  # 200ms防抖间隔
```

在 `on_span()` 中检查 `time.time() - self._last_update < self._debounce_ms/1000`，
避免快速连续的span事件导致ESP32收到过多消息。

### 5.3 消息格式

发送到ESP32的 `thinking_status` 消息:

```json
{
  "type": "thinking_status",
  "data": {
    "state": "thinking|tool_call|responding|error|done|idle",
    "name": "step名称",
    "tool": "工具名(仅tool_call状态)",
    "step_count": 5
  },
  "ts": 1234567890.123
}
```

### 5.4 ESP32解析: parseServerData()

**源码引用**: main.cpp:877-918

```cpp
// 思考状态枚举映射
String state = data["state"] | "idle";
ThinkingState ts = THINK_IDLE;
if (state == "thinking") ts = THINK_THINKING;
else if (state == "tool_call") ts = THINK_TOOL_CALL;
else if (state == "responding") ts = THINK_RESPONDING;
else if (state == "error") ts = THINK_ERROR;
else if (state == "done") ts = THINK_DONE;

// 写入双缓冲
g_displayBuf[backIdx].agent.thinkingState = ts;

// [OPT-1] 记录思考步骤到PSRAM环形缓冲
String stepText = data["name"] | data["tool"] | state;
g_displayBuf[backIdx].thinkingHistory->addStep(stepText.c_str());
```

### 5.5 ThinkingStepCache (PSRAM环形缓冲)

**源码引用**: display_manager.cpp:1171-1260

```
PSRAM链表结构 (ps_malloc分配):
  head → [Node1] → [Node2] → ... → [NodeN] ← tail
  count <= THINKING_HISTORY_MAX (默认30步)

addStep(text):
  1. ps_malloc(sizeof(ThinkingNode))
  2. strncpy(text, step.text, 27)  ← THINKING_STEP_TEXT_MAX=28
  3. 追加到tail
  4. count > MAX → _evictOldest() (从head淘汰)

getRecentSteps(outSteps, maxCount):
  1. 跳过 (count - maxCount) 个旧节点
  2. 收集到临时数组
  3. 反转: outSteps[0]=最新
```

### 5.6 渲染: drawThinkingIndicator()

**源码引用**: display_manager.cpp:1063-1169

**状态指示区** (右上角 58x10px):

```
┌──────────────────┐
│ ● think    5/30  │  ← 闪烁圆点 + 状态标签 + 步数
└──────────────────┘
```

状态颜色映射:
- `THINK_THINKING` → 绿色 (0x07E0)
- `THINK_TOOL_CALL` → 黄色 (0xFFE0)
- `THINK_RESPONDING` → 蓝色 (0x001F)
- `THINK_ERROR` → 红色 (0xF800)
- `THINK_DONE` → 绿色 (0x07E0)

**历史滚动展示** — CIE easing缓动:

```cpp
// CIE ease-in-out: 3t^2 - 2t^3 (smoothstep)
float t = (float)elapsed / SCROLL_DURATION_MS;
scrollFraction = t * t * (3.0f - 2.0f * t);

// 滚动偏移
int scrollPixels = (int)(scrollFraction * lineH);  // lineH=9px

// 最新步骤白色，旧步骤渐暗
i==0: textColor = 0xFFFF  (白色)
i==1: textColor = 0xC618  (浅灰)
i>=2: textColor = 0x8410  (深灰)
```

### 5.7 时序分析

| 阶段 | 耗时 | 说明 |
|------|------|------|
| OTLP HTTP接收 | ~1-5ms | 本地loopback |
| Span分类 | <1ms | dict查找 |
| 防抖等待 | 0-200ms | 200ms防抖窗口 |
| TCP传输 | ~1-2ms | ~100字节小消息 |
| ESP32解析 | ~1-2ms | |
| PSRAM链表操作 | <0.1ms | 单节点分配+追加 |
| 滚动渲染 | ~3-5ms | 最多4行文本 |
| **端到端典型延迟** | **~5-215ms** | 防抖是主要延迟源 |

---

## 六、链路5: 像素动画 → 屏幕显示

### 6.1 编码阶段: pxl_encoder.py

**PXL文件格式** (16字节头 + 帧数据):

```
字节偏移  内容
0x00-02  Magic: "PXL"
0x03     Version: 1
0x04-05  Flags: bit1=RLE, bit2=Delta帧编码
0x06-07  Width (uint16 LE)
0x08-09  Height (uint16 LE)
0x0A-0B  FrameCount (uint16 LE)
0x0C-0D  FrameInterval ms (uint16 LE)
0x0E-0F  Reserved
```

**RGB565编码** (pxl_encoder.py:30-41):

```python
# numpy向量化，比纯Python循环快10-50倍
rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
# 每像素2字节，32x32帧 = 2048字节
```

**RLE压缩** (pxl_encoder.py:44-80):

```
格式: [flag_byte][data]
  bit7=1 (run):  flag=0x80|count, 后接2字节重复像素(big-endian)
                 run长度 >= 3 时使用
  bit7=0 (literal): flag=count, 后接 count*2 字节原始像素
```

### 6.2 传输阶段: TCP分包base64

**发送格式** (两种协议):

```
格式A (pxl_sender):
{
  "type": "pixel_data",
  "data": {
    "packet_index": 0,
    "total_packets": 3,
    "chunk_base64": "UElM..."
  }
}

格式B (legacy):
{
  "type": "pixel_data",
  "data": "base64编码数据",
  "chunk": 0,
  "last": false
}
```

### 6.3 ESP32接收与解码: main.cpp parseServerData()

**PSRAM静态池** (main.cpp:36-37):

```cpp
// 32x32x2x64 = 128KB 预分配，避免运行时malloc碎片化
__attribute__((section(".psram")))
static uint8_t g_pxlPool[32 * 32 * 2 * 64];
```

**流式base64解码** (main.cpp:738-832):

```
chunkIndex == 0:
  g_pxlBuffer = g_pxlPool    ← 重置池指针
  g_pxlOffset = 0

每个chunk:
  mbedtls_base64_decode(g_pxlBuffer + g_pxlOffset, ...)  ← 直接解码到PSRAM池
  g_pxlOffset += written

isLastChunk:
  g_pendingPixelBufferPtr = g_pxlPool
  g_pendingPixelSize = g_pxlOffset
  g_pendingPixelBufferLoad.store(true)  ← 通知Core 1
```

### 6.4 Core 1加载与播放

**renderTask中的pending操作** (main.cpp:315-329):

```cpp
if (g_pendingPixelBufferLoad && g_pendingPixelBufferPtr) {
    uint8_t* buf = g_pendingPixelBufferPtr;
    size_t sz = g_pendingPixelSize;
    pixelPlayer.loadFromBuffer(buf, sz);   // 解码PXL帧数据
    g_pendingPixelPlay = true;              // 标记待播放
    g_pendingPixelBufferLoad = false;
}
```

**模式切换与淡入淡出** (display_manager.cpp:192-224):

```
setPixelMode(player):
  1. _transitionSprite.pushSprite(&_sprite, 0, 0)  ← 捕获当前帧作为旧帧
  2. _displayMode = MODE_PIXEL
  3. drawPixelFrame()  ← 绘制新像素帧到_sprite
  4. _fadeBlend()      ← 16帧alpha混合淡入淡出(~256ms)

_fadeBlend():
  逐像素混合: result = (old*invAlpha + new*alpha) >> 4
  // 16级alpha, 每帧16ms, 总计~256ms平滑过渡
```

### 6.5 像素帧渲染: drawPixelFrame()

**源码引用**: display_manager.cpp:226-266

```
_pixelPlayer->getCurrentFrame() → uint16_t* pixels (RGB565)
         ↓
整数倍缩放居中:
  scale = min(SCREEN_WIDTH/w, SCREEN_HEIGHT/h)
  scaledW = w * scale, scaledH = h * scale
  x = (240 - scaledW)/2 + scaledW/2
  y = (240 - scaledH)/2 + scaledH/2
         ↓
_sprite.pushImageRotateZoom(x, y, 0, 0, 0, scale, scale, w, h, pixels)
```

### 6.6 时序分析

| 阶段 | 耗时 | 说明 |
|------|------|------|
| PXL编码(Python) | ~10-50ms | numpy向量化RGB565 |
| RLE压缩 | ~5-20ms | 取决于帧复杂度 |
| base64编码 | ~1-5ms | |
| TCP分包传输 | ~5-50ms | 多个chunk，取决于文件大小 |
| base64解码(mbedtls) | ~2-10ms | 直接写入PSRAM池 |
| PXL帧解码 | ~5-20ms | RLE解压+帧解析 |
| 淡入淡出 | ~256ms | 16帧alpha混合 |
| 逐帧渲染 | ~5-15ms | pushImageRotateZoom |
| **单帧渲染** | **~5-15ms** | 稳态播放 |
| **首次加载** | **~300-500ms** | 含传输+淡入淡出 |

---

## 七、链路6: 传感器 → 系统响应

### 7.1 BH1750光照传感器 → 自动背光

**数据流**:

```
BH1750FVI (I2C 0x23)
  │  连续高分辨率模式, 分辨率 1 lx
  │  每次读取: Wire.requestFrom(0x23, 2) → 2字节原始值
  │  lux = raw / 1.2
  v
AmbientLightManager.readLux() (ambient_light.cpp:55)
  │
  v
EMA滤波 (ambient_light.h):
  _smoothLux = _smoothLux * 0.7 + rawLux * 0.3
  │  一阶低通滤波，消除瞬间波动(如手影掠过)
  v
autoAdjustBacklight(lux) → PWM值:
  ┌────────────────────────────────────────────┐
  │  0~10 lux:    PWM 20% (最低防全黑)         │
  │  10~100 lux:  线性映射 20%~50%             │
  │  100~1000 lux: 线性映射 50%~100%           │
  │  >1000 lux:   PWM 100%                     │
  └────────────────────────────────────────────┘
  │
  v
CIE1931感知线性化 → display.setBrightness(pwm)
  │  人眼感知亮度非线性，CIE曲线使亮度变化感觉均匀
  v
display.applySmoothBacklight() (每帧调用):
  _currentBrightness += (target - _currentBrightness) * BRIGHTNESS_SMOOTHING
  _lcd.setBrightness((uint8_t)(_currentBrightness + 0.5f))
  │  一阶EMA平滑，消除亮度跳变
  v
LCD背光PWM输出
```

**读取频率**: `BH1750_READ_INTERVAL` (renderTask中每帧检查)

### 7.2 触摸传感器 → 手势识别

**硬件**: 电容触摸GPIO + 接近感应

**TouchHandler** (touch_handler.h:39-62):

```
readValue() → 原始电容值
  │
  ├── 校准基线: _baseline (启动时采集)
  ├── 阈值: _threshold = _baseline + offset
  │
  ├── isTouched(): value > _threshold
  │
  ├── 手势状态机:
  │   单击: touch_start → release < 300ms → tap间隔 > 300ms
  │   双击: 两次tap间隔 < 300ms
  │   长按: touch持续 > 800ms
  │
  └── 回调触发:
      TOUCH_SINGLE_TAP  → sound.beep(4500, 15) + hapticDriver.click()
      TOUCH_DOUBLE_TAP  → sound.playNotification() + hapticDriver.buzz()
      TOUCH_LONG_PRESS  → sound.playAlert() + hapticDriver.strongHit()
```

### 7.3 接近感应 → 自动唤醒

**ProximitySensor** (touch_handler.h:18-37) — 双EMA差分检测:

```
readValue() → 原始电容值
  │
  ├── _fastEMA = _fastEMA * α_fast + raw * (1 - α_fast)  ← 快速响应
  ├── _slowEMA = _slowEMA * α_slow + raw * (1 - α_slow)  ← 慢速基线
  │
  ├── diff = _fastEMA - _slowEMA
  │   diff > threshold → isNear = true  (物体接近，电容值突增)
  │   diff < hysteresis → isNear = false (物体离开)
  │
  └── 接近事件 → renderTask:
      if (touch.proximity.isNear()):
        g_forceWake = true
        display.wakeup()          ← 恢复全亮
        g_screenSleeping = false
        g_lastDataReceived = now  ← 重置休眠计时
```

### 7.4 DRV2605L触觉反馈

**硬件**: DRV2605L LRA驱动器 (I2C 0x5A)

**预设效果** (haptic_driver.h:28-33):

| 效果ID | 名称 | 触发场景 |
|--------|------|----------|
| 1 | click | 触摸确认(单击) |
| 47 | buzz | 通知(双击) |
| 72 | strongHit | 警告(长按) |
| 3 | softTouch | 滑动反馈 |
| 12 | rampUp | 渐强提示 |

**调用链**: 触摸事件 → `TouchHandler._callback(event)` → `hapticDriver.click()` → I2C写入DRV2605L → LRA马达振动

### 7.5 休眠管理状态机

**renderTask中的休眠逻辑** (main.cpp:234-293):

```
正常运行 (240MHz, WiFi active, 50fps)
  │
  ├── 15秒无数据 → SCREEN_DIM_TIMEOUT
  │     display.dim() → 目标亮度30%
  │     g_screenDimmed = true
  │
  ├── 30秒无数据 → SCREEN_SLEEP_TIMEOUT
  │     setCpuFrequencyMhz(80)       ← CPU降频
  │     WiFi.setSleep(true)          ← WiFi省电
  │     display.sleep()              ← 背光关闭
  │     frameDelay = 500ms (2fps)
  │     g_screenSleeping = true
  │
  ├── 5分钟无数据 → Light Sleep
  │     esp_sleep_enable_touchpad_wakeup()
  │     gpio_hold_en(LCD_BL/BUZZER/LCD_CS)  ← 锁定引脚电平
  │     esp_light_sleep_start()               ← 超低功耗
  │     唤醒源: 触摸/RTC定时器
  │
  └── 数据到达 (g_forceWake=true):
        setCpuFrequencyMhz(240)     ← CPU恢复
        WiFi.setSleep(false)        ← WiFi恢复
        display.wakeup()            ← 背光恢复
        frameDelay = 20ms (50fps)
```

**VRR动态帧率** (main.cpp:409-426):

```
Agent WORKING:  frameDelay = 16ms  (60fps, 流畅思考动画)
Agent AUTH:     frameDelay = 33ms  (30fps)
Agent IDLE:     frameDelay = 20ms  (50fps, 默认)
数据静默>15s:   frameDelay = 200ms (5fps)
屏幕变暗:       frameDelay = 1000ms (1fps)
屏幕休眠:       frameDelay = 500ms (2fps)
```

---

## 八、时序分析与性能总结

### 8.1 各链路端到端延迟

```
链路1 Agent状态:    ~10-30ms   (每2秒)
链路2 Token统计:    ~15-40ms   (每30秒)
链路3 天气数据:     ~210-2020ms (每10/30/60分钟, 主要瓶颈=API网络)
链路4 思考链:       ~5-215ms   (200ms防抖是主要延迟)
链路5 像素动画:     ~300-500ms (首次), ~5-15ms/帧 (稳态)
链路6 传感器:       <1ms       (实时GPIO/I2C)
```

### 8.2 关键瓶颈分析

| 瓶颈 | 位置 | 影响 | 优化措施 |
|------|------|------|----------|
| OpenWeatherMap API | weather.py HTTP请求 | 天气更新延迟~2s | 本地缓存+降级模拟数据 |
| JSONL全量扫描 | token_stats.py | Token统计IO开销 | LogTailer增量读取+10s缓存TTL |
| psutil遍历 | agent_monitor.py | 每2秒遍历进程 | PID缓存+轻量存活检查 |
| ArduinoJson解析 | main.cpp parseServerData | 大JSON解析耗时 | Filter精确提取+分类型StaticJsonDocument |
| PSRAM访问延迟 | display_manager DMA | 像素帧渲染卡顿 | SRAM切片桥接+脏矩形局部刷新 |
| 思考链防抖 | thinking_chain.py | 显示延迟200ms | 可配置防抖间隔 |

### 8.3 内存使用概览

**ESP32-S3内存布局**:

| 区域 | 大小 | 用途 |
|------|------|------|
| PSRAM像素池 | 128KB | g_pxlPool (32x32x2x64) |
| PSRAM JSON缓冲 | 4KB | g_jsonParseBuf |
| PSRAM思考缓存 | ~3KB | ThinkingStepCache x 2 |
| SRAM显示缓冲 | ~230KB | Sprite双缓冲 (240x240x2) |
| SRAM帧混合缓冲 | ~115KB | s_fadeBlendBuf |
| SRAM切片缓冲 | 1KB | s_sramSliceBuf |
| TCP读取缓冲 | 4KB | _readBuf |
| 帧解析缓冲 | 动态 | _frameBuffer (最多256KB) |

### 8.4 双缓冲无锁设计

```
Core 0 (commTask)                    Core 1 (renderTask)
  │                                    │
  │ g_frontIdx.load(acquire)           │ g_frontIdx.load(acquire)
  │ backIdx = 1 - front                │ localData = g_displayBuf[frontIdx]
  │ g_displayBuf[backIdx] = ...写入    │
  │ g_frontIdx.store(backIdx, release) │
  │                                    │ 读取front buffer的本地副本
  │                                    │ 渲染到LCD
```

关键保证:
- **memory_order_acquire**: 读取时确保看到之前的写入
- **memory_order_release**: 写入时确保对后续读取可见
- **FIX-N1**: 只load一次frontIdx，防止两次load之间被另一个Core swap

### 8.5 断线重连与指数退避

**ESP32端** (comm_manager.cpp:87-114):

```
reconnect():
  连续失败次数 → 退避间隔:
    #1: 5s, #2: 10s, #3: 20s, #4: 40s, #5: 60s (上限)
  连续失败 >= 10次: WiFi.disconnect(true) → WiFi.begin() (硬重置)
```

**PC端** (communication.py:486-506):

```
Keep-Alive:
  每10秒发送ping
  30秒无pong → 断开连接
  断连后等待ESP32重连，不永久退出
```

---

> 本文档基于代码仓库 commit `ae498df` (2026-06-24) 分析生成。
> 源码文件引用路径均相对于项目根目录。
