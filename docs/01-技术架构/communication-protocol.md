# 通信协议规范

> 本文档定义 PC 端 (pc_monitor) 与 ESP32 端 (esp32_firmware) 之间的完整通信协议，
> 涵盖帧格式、消息类型、连接生命周期、设备发现及错误恢复机制。

---

## 一、帧协议格式

PC 与 ESP32 之间通过 WiFi TCP 连接交换数据，采用 **长度前缀帧协议** (v2)，
同时兼容旧版换行分隔 JSON 格式 (v1 legacy fallback)。

### 1.1 长度前缀帧 (v2, 当前版本)

每帧由两部分组成：**长度头** + **JSON payload**。

```
LEN:<length>\n<payload>
```

| 组成部分 | 格式 | 说明 |
|----------|------|------|
| 长度头 | `LEN:<十进制数字>\n` | 以 `LEN:` 开头，后跟 payload 字节数，以 `\n` 结尾 |
| Payload | 原始 JSON 字符串 | 不含尾部换行符的 JSON 文本 |

**示例（原始字节）：**

```
LEN:48
{"type":"heartbeat","ts":1234567890}
```

**关键约束：**

| 参数 | PC 端值 | ESP32 端值 | 说明 |
|------|---------|------------|------|
| 最大帧长度 | 256 KB (`MAX_FRAME_LEN`) | 256 KB (`FRAME_MAX_LEN`) | 单帧 payload 的字节上限 |
| 长度头最大长度 | - | 16 字符 | 防止超长 header 攻击 |
| 旧格式最大长度 | - | 32 KB | legacy 单帧溢出保护 |
| 接收缓冲区上限 | 512 KB | - | PC 端 `_read_loop` 中畸形数据防护 |

### 1.2 旧格式 (v1 Legacy Fallback)

以 `\n` 分隔的纯 JSON 行，无长度前缀。用于兼容早期固件版本。

```
{"type":"heartbeat","ts":1234567890}\n
```

### 1.3 帧类型检测 (ESP32 端状态机)

ESP32 通过首字符自动识别帧类型：

```
FRAME_IDLE ──┬── 'L' ──→ FRAME_READ_LEN ──→ FRAME_READ_BODY ──→ processData()
             └── '{' ──→ FRAME_LEGACY_LINE ──(遇\n)──→ processData()
```

| 状态 | 说明 |
|------|------|
| `FRAME_IDLE` | 空闲，等待新帧首字符。`L` 进入长度头解析，`{` 进入旧格式解析 |
| `FRAME_READ_LEN` | 累积读取 `LEN:NNNN\n`，遇到 `\n` 后解析长度值 |
| `FRAME_READ_BODY` | 按 `_expectedLen` 逐字节/批量读取 payload。支持批量写入优化 |
| `FRAME_LEGACY_LINE` | 兼容旧格式：逐字符累积直到遇到 `\n` |

### 1.4 发送格式

两端发送时统一使用 v2 帧格式：

```cpp
// ESP32 端 (C++)
void CommManager::sendFramed(const String& json) {
    char header[16];
    int len = snprintf(header, sizeof(header), "LEN:%d\n", (int)json.length());
    _client.write((const uint8_t*)header, len);
    _client.print(json);
}
```

```python
# PC 端 (Python)
frame = f"LEN:{len(payload)}\n{payload}\n"
client_socket.sendall(frame.encode('utf-8'))
```

---

## 二、JSON 消息类型全表

所有消息均为单行 JSON 对象，核心字段为 `type`，部分消息包含 `data` 和 `ts`。

| 类型 (type) | 方向 | 触发条件 | 主要字段 | 发送频率 |
|-------------|------|----------|----------|----------|
| `handshake` | ESP32 -> PC | TCP 连接建立后首条消息 | `device`, `version` | 仅一次 |
| `status` | PC -> ESP32 | Agent 状态变化 | `status`, `process`, `cpu`, `memory`, `uptime` | 2 秒 |
| `token` | PC -> ESP32 | Token 统计更新 | `input`, `output`, `requests`, `hour`, `cost` | 30 秒 |
| `weather` | PC -> ESP32 | 天气信息更新 | `city`, `temp`, `feels_like`, `humidity`, `desc`, `icon`, `wind` | 30 分钟 |
| `heartbeat` | ESP32 -> PC | 定时发送 | `ts` | 10 秒 |
| `ping` | PC -> ESP32 | Keep-Alive 定时发送 | `ts` | 10 秒 |
| `pong` | ESP32 -> PC | 收到 ping 后自动回复 | `ts`, `ping_ts` | 收到 ping 时 |
| `pixel_data` | PC -> ESP32 | 发送自定义像素文件 | `data`/`chunk_base64`, `chunk`, `total`, `last` | 按需 |
| `pixel_cmd` | PC -> ESP32 | 控制像素播放 | `action` (play/stop/pause/resume) | 按需 |
| `thinking_status` | PC -> ESP32 | AI Agent 推理状态变化 | `state`, `name`, `tool`, `step_count` | 按需 |
| `crash_report` | ESP32 -> PC | ESP32 崩溃重启后首次连接 | `count`, `reason` | 仅一次 |

---

## 三、每种消息详细定义

### 3.1 handshake -- 握手消息

**方向：** ESP32 -> PC

**触发条件：** TCP 连接成功后立即发送，作为第一条消息。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"handshake"` |
| `device` | string | 是 | 设备标识，如 `"esp32s3"` |
| `version` | string | 是 | 协议版本号，当前 `"2.0.0"` (v2 帧协议) |

**JSON 示例：**

```json
{
  "type": "handshake",
  "device": "esp32s3",
  "version": "2.0.0"
}
```

---

### 3.2 status -- Agent 状态

**方向：** PC -> ESP32

**触发条件：** PC 端 Agent 监控模块定期检测到状态变化时发送。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"status"` |
| `data.status` | string | 是 | 状态枚举: `idle`, `working`, `auth`, `offline` |
| `data.process` | string | 否 | 当前运行的进程名称 |
| `data.cpu` | float | 否 | CPU 使用率 (0-100) |
| `data.memory` | float | 否 | 内存使用量 (MB) |
| `data.uptime` | int | 否 | 运行时长 (秒) |

**状态枚举说明：**

| 状态值 | ESP32 显示行为 |
|--------|----------------|
| `idle` | 空闲表情 |
| `working` | 工作中表情 (忙碌动画) |
| `auth` | 认证中表情 |
| `offline` | 离线表情 (45 秒无数据自动切换) |

**JSON 示例：**

```json
{
  "type": "status",
  "data": {
    "status": "working",
    "process": "claude-code",
    "cpu": 45.2,
    "memory": 128.5,
    "uptime": 3600
  }
}
```

---

### 3.3 token -- Token 统计

**方向：** PC -> ESP32

**触发条件：** PC 端 Token 统计模块定期更新时发送。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"token"` |
| `data.input` | int | 是 | 输入 Token 总数 |
| `data.output` | int | 是 | 输出 Token 总数 |
| `data.requests` | int | 是 | 总请求数 |
| `data.hour` | int | 否 | 最近 1 小时 Token 数 |
| `data.cost` | float | 否 | 预估费用 (USD) |

**JSON 示例：**

```json
{
  "type": "token",
  "data": {
    "input": 15000,
    "output": 8000,
    "requests": 42,
    "hour": 2500,
    "cost": 0.35
  }
}
```

---

### 3.4 weather -- 天气信息

**方向：** PC -> ESP32

**触发条件：** PC 端天气模块定期获取天气数据后发送。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"weather"` |
| `data.city` | string | 是 | 城市名 |
| `data.temp` | float | 是 | 当前温度 (摄氏度) |
| `data.feels_like` | float | 否 | 体感温度 (摄氏度) |
| `data.humidity` | int | 否 | 湿度百分比 (0-100) |
| `data.desc` | string | 否 | 天气描述文本 |
| `data.icon` | string | 否 | 天气图标代码: `sun`, `cloud`, `rain`, `snow`, `fog` |
| `data.wind` | float | 否 | 风速 (m/s) |

**JSON 示例：**

```json
{
  "type": "weather",
  "data": {
    "city": "北京",
    "temp": 22.5,
    "feels_like": 21.0,
    "humidity": 45,
    "desc": "晴",
    "icon": "sun",
    "wind": 3.5
  }
}
```

---

### 3.5 heartbeat -- 心跳

**方向：** ESP32 -> PC

**触发条件：** ESP32 端通信任务每 10 秒定时发送，用于维持连接活性。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"heartbeat"` |
| `ts` | int | 是 | ESP32 本地时间戳 (`millis()`) |

**JSON 示例：**

```json
{
  "type": "heartbeat",
  "ts": 1234567890
}
```

---

### 3.6 ping -- Keep-Alive 探测

**方向：** PC -> ESP32

**触发条件：** PC 端 Keep-Alive 线程每 10 秒发送一次，用于检测连接存活。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"ping"` |
| `ts` | float | 是 | PC 端发送时间戳 (`time.time()`) |

**JSON 示例：**

```json
{
  "type": "ping",
  "ts": 1687000000.123
}
```

---

### 3.7 pong -- Keep-Alive 响应

**方向：** ESP32 -> PC

**触发条件：** ESP32 收到 `ping` 消息后立即自动回复。PC 端收到 `pong` 后更新存活时间戳，
但不传递给上层回调。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"pong"` |
| `ts` | int | 是 | ESP32 回复时的 `millis()` |
| `ping_ts` | float | 否 | 原始 ping 的 `ts` 值，用于 RTT 计算 |

**JSON 示例：**

```json
{
  "type": "pong",
  "ts": 1234567900,
  "ping_ts": 1687000000.123
}
```

---

### 3.8 pixel_data -- 像素数据传输

**方向：** PC -> ESP32

**触发条件：** PC 端发送自定义 `.pxl` 像素文件时。支持单包和分包两种传输方式。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"pixel_data"` |
| `data` | string | 是* | Base64 编码的像素数据 (格式 B legacy) |
| `data.packet_index` | int | 是* | 当前分包索引 (格式 A) |
| `data.total_packets` | int | 是* | 总分包数 (格式 A) |
| `data.chunk_base64` | string | 是* | Base64 编码的像素数据 (格式 A) |
| `chunk` | int | 否 | 当前分包索引 (格式 B legacy) |
| `total` | int | 否 | 总分包数 (格式 B legacy) |
| `last` | bool | 否 | 是否最后一个分包 (格式 B legacy) |

> *标注"是*"的字段：格式 A 和格式 B 二选一。

**两种数据格式：**

**格式 A (pxl_sender 工具使用)：** `data` 为嵌套对象

```json
{
  "type": "pixel_data",
  "data": {
    "packet_index": 0,
    "total_packets": 3,
    "chunk_base64": "UElM...base64..."
  }
}
```

**格式 B (Legacy)：** `data` 直接为 Base64 字符串

```json
{
  "type": "pixel_data",
  "data": "UElM...base64...",
  "chunk": 0,
  "total": 3,
  "last": false
}
```

**传输流程：**

1. PC 端将 `.pxl` 文件 Base64 编码后分片发送
2. ESP32 端逐片解码到 PSRAM 预分配池 (128 KB)
3. 最后一片 (`last=true` 或 `packet_index >= total_packets - 1`) 到达后，
   将缓冲区指针传递给 Core 1 渲染任务加载并播放

---

### 3.9 pixel_cmd -- 像素控制命令

**方向：** PC -> ESP32

**触发条件：** PC 端控制自定义像素显示的播放状态。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"pixel_cmd"` |
| `data.action` | string | 是 | 控制动作枚举 |

**动作枚举：**

| action | 说明 |
|--------|------|
| `play` | 加载像素数据并切换到像素显示模式 |
| `stop` | 停止播放，返回正常表情显示模式 |
| `pause` | 暂停动画播放 |
| `resume` | 恢复动画播放 (内部调用 `play()`) |

**JSON 示例：**

```json
{
  "type": "pixel_cmd",
  "data": {
    "action": "play"
  }
}
```

---

### 3.10 thinking_status -- 思考链状态

**方向：** PC -> ESP32

**触发条件：** PC 端 OTLP 接收器检测到 AI Agent 推理状态变化时发送。
由 `ThinkingChainTracker` 模块驱动。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"thinking_status"` |
| `data.state` | string | 是 | 思考状态枚举 |
| `data.name` | string | 否 | 当前步骤名称 |
| `data.tool` | string | 否 | 工具调用名称 (仅 `tool_call` 状态) |
| `data.step_count` | int | 否 | 当前步骤序号 |

**状态枚举：**

| state | 含义 | ESP32 显示行为 |
|-------|------|----------------|
| `idle` | 空闲 | 无特殊显示 |
| `thinking` | 思考中 | 思考动画 |
| `tool_call` | 工具调用中 | 工具调用动画 |
| `responding` | 生成回复中 | 回复动画 |
| `error` | 错误 | 错误提示 |
| `done` | 完成 | 恢复正常 |

**JSON 示例：**

```json
{
  "type": "thinking_status",
  "data": {
    "state": "tool_call",
    "name": "Reading file",
    "tool": "Read",
    "step_count": 3
  }
}
```

---

### 3.11 crash_report -- 崩溃遥测

**方向：** ESP32 -> PC

**触发条件：** ESP32 崩溃重启后，首次成功连接 PC 时自动发送。
使用 RTC_NOINIT 段保存崩溃计数（重启不丢失）。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"crash_report"` |
| `data.count` | int | 是 | 累计崩溃次数 (冷启动保留) |
| `data.reason` | int | 是 | ESP32 重启原因代码 (`esp_reset_reason()`) |

**重启原因代码参考：**

| 代码 | 含义 |
|------|------|
| 1 | ESP_RST_POWERON -- 上电重启 |
| 3 | ESP_RST_SW -- 软件重启 |
| 4 | ESP_RST_PANIC -- 异常/看门狗 |
| 5 | ESP_RST_INT_WDT -- 中断看门狗 |
| 6 | ESP_RST_TASK_WDT -- 任务看门狗 |
| 9 | ESP_RST_BROWNOUT -- 掉电 |

**JSON 示例：**

```json
{
  "type": "crash_report",
  "data": {
    "count": 3,
    "reason": 4
  }
}
```

---

## 四、TCP 连接生命周期

```
  ESP32                              PC
   │                                  │
   │  ──── TCP SYN ──────────────→   │  Discovery 阶段完成
   │  ←─── TCP SYN+ACK ──────────   │  (见第五章)
   │  ──── TCP ACK ──────────────→   │
   │                                  │
   │  ──── handshake (v2) ────────→  │  握手阶段
   │                                  │
   │  ←─── status ──────────────────  │  正常数据交换
   │  ←─── token ───────────────────  │
   │  ←─── weather ─────────────────  │
   │  ──── heartbeat ──────────────→  │  每 10 秒
   │  ←─── ping ────────────────────  │  每 10 秒
   │  ──── pong ───────────────────→  │  收到 ping 时
   │                                  │
   │  ... (持续通信) ...              │
   │                                  │
   │  ──── [连接断开] ────────────→   │  断连检测
   │                                  │
   │  ──── 指数退避重连 ───────────→  │  重连阶段
   │  ──── handshake (v2) ────────→  │  重新握手
   │                                  │
```

### 4.1 连接角色

| 角色 | 端 | 说明 |
|------|------|------|
| TCP Server | PC (pc_monitor) | 监听 `0.0.0.0:19876`，等待 ESP32 连入 |
| TCP Client | ESP32 (esp32_firmware) | 主动连接 PC 的 IP 和端口 |

### 4.2 连接参数

| 参数 | PC 端值 | ESP32 端值 | 来源 |
|------|---------|------------|------|
| 默认端口 | `19876` | `19876` | `config.h` / Python 常量 |
| Accept 超时 | 1 秒 | - | `socket.settimeout()` |
| Client 超时 | 5 秒 | 10 秒 | `socket.settimeout()` / `WiFiClient::setTimeout()` |
| TCP Keep-Alive | 应用层 ping/pong | 内核 TCP keepalive | 见下文 |

### 4.3 心跳与保活机制

系统采用 **双层保活** 策略：

**应用层 (PC 端驱动)：**

- PC 端每 **10 秒** 发送 `ping` 消息
- ESP32 收到后立即回复 `pong`
- PC 端 **30 秒** 未收到 `pong` 判定断连
- `pong` 消息不传递给上层回调，仅更新内部时间戳

**TCP 层 (ESP32 端驱动)：**

- 连接成功后设置 `SO_KEEPALIVE`
- 空闲 **60 秒** 后开始探测 (`TCP_KEEPIDLE`)
- 每 **10 秒** 探测一次 (`TCP_KEEPINTVL`)
- 连续 **3 次** 无响应判定断开 (`TCP_KEEPCNT`)
- 目的：检测路由器 NAT 超时、服务端崩溃等死连接

### 4.4 断连与重连 (ESP32 端)

ESP32 检测到断连后进入 **指数退避重连** 流程：

```
断连检测 → disconnect() → reconnect() 循环
                              │
                              ├─ 间隔 = min(当前间隔 * 2, 60秒)
                              ├─ 初始间隔 = 5秒
                              └─ 连续失败 10 次 → WiFi 硬重置
```

| 参数 | 值 | 说明 |
|------|------|------|
| 初始重连间隔 | 5 秒 | `RECONNECT_INTERVAL` |
| 退避策略 | 每次翻倍 | `interval = min(interval * 2, 60000ms)` |
| 最大重连间隔 | 60 秒 | 上限 |
| WiFi 硬重置阈值 | 连续 10 次失败 | `WiFi.disconnect(true)` + `WiFi.begin()` |
| 重连成功后 | 重置计数和间隔 | `_reconnectFailCount = 0` |

### 4.5 断连与重连 (PC 端)

PC 端作为 Server，不主动重连，而是等待 ESP32 重新连入：

- `_accept_loop` 持续监听新连接
- 新连接到来时关闭旧 socket（单设备模式）
- 旧读取线程等待 2 秒退出后启动新线程
- 重启 Keep-Alive 线程

### 4.6 数据更新频率

| 数据类型 | 更新间隔 | 说明 |
|----------|----------|------|
| Agent 状态 | 2 秒 | `agent_monitor.py` |
| Token 统计 | 30 秒 | `token_stats.py` |
| 天气信息 | 30 分钟 | `weather.py` |
| 心跳 (ESP32->PC) | 10 秒 | `comm_manager.cpp` |
| Keep-Alive (PC->ESP32) | 10 秒 | `communication.py` |

### 4.7 离线检测

| 端 | 超时 | 行为 |
|------|------|------|
| ESP32 | 45 秒无数据 | 显示 OFFLINE 状态 (`OFFLINE_TIMEOUT_MS`) |
| ESP32 | 30 秒无数据 | 屏幕变暗 (`SCREEN_DIM_TIMEOUT`) |
| ESP32 | 60 秒无数据 | 屏幕休眠 (`SCREEN_SLEEP_TIMEOUT`) |
| PC | 30 秒无 pong | 断开连接 (`KEEPALIVE_TIMEOUT`) |

---

## 五、设备发现机制

ESP32 首次上电或丢失服务器配置时，按以下优先级尝试发现 PC 端服务器：

```
保存的配置 → mDNS → UDP 广播 → BLE 配网 → Web AP 配网
```

### 5.1 UDP 广播发现

PC 端定期向局域网广播服务器地址，ESP32 监听并自动解析。

| 参数 | 值 | 说明 |
|------|------|------|
| 广播端口 | `19877` | `DEFAULT_UDP_BROADCAST_PORT` |
| 广播间隔 | 5 秒 | `DEFAULT_UDP_BROADCAST_INTERVAL` |
| 广播格式 | `DESKTOP_PET_SERVER:<IP>:<PORT>` | 纯文本协议 |

**广播消息示例：**

```
DESKTOP_PET_SERVER:192.168.1.100:19876
```

**PC 端实现：**

```python
# PC 端广播循环
msg = f"DESKTOP_PET_SERVER:{local_ip}:{self.port}"
udp_sock.sendto(msg.encode('utf-8'), ('<broadcast>', self.udp_broadcast_port))
```

**ESP32 端实现：**

```cpp
// ESP32 监听 UDP 端口 19877
WiFiUDP udp;
udp.begin(19877);
// 解析 "DESKTOP_PET_SERVER:IP:PORT" 格式
// 成功后保存到 Flash (Preferences "pet_config")
```

**发现成功后：** ESP32 将服务器 IP 和端口保存到 Flash (`Preferences`)，
后续重启直接使用保存的配置。

### 5.2 mDNS 服务发现

| 参数 | 值 | 说明 |
|------|------|------|
| 服务类型 | `_deskpet._tcp.local.` | mDNS 服务名 |
| 主机名 | `deskpet.local` | mDNS 主机名 |
| 查询 | `MDNS.queryService("deskpet", "tcp")` | ESP32 端查询 |

**PC 端注册：** PC 端作为 Server 启动时注册 mDNS 服务（如有支持）。

**ESP32 端查询：**

```cpp
int n = MDNS.queryService("deskpet", "tcp");
if (n > 0) {
    String ip = MDNS.IP(0).toString();
    int port = MDNS.port(0);
    // 保存到 Flash
}
```

**ESP32 端注册：** 连接成功后，ESP32 也注册自身 mDNS 服务：

```cpp
MDNS.begin("deskpet");
MDNS.addService("deskpet", "tcp", server_port);
```

### 5.3 BLE 配网 (Provisioning)

当 mDNS 和 UDP 发现均失败时，ESP32 进入 BLE 配网模式。

| 参数 | 值 | 说明 |
|------|------|------|
| 服务 UUID | `0x1820` | 自定义配网服务 |
| SSID 特征 UUID | `0x2A69` | 写入 WiFi SSID |
| 密码特征 UUID | `0x2A6A` | 写入 WiFi 密码 |
| URL 特征 UUID | `0x2A6B` | 写入服务器地址 |
| 状态特征 UUID | `0x2A6C` | 读取配网状态 |
| 超时 | 120 秒 | 超时后降级到 AP 模式 |

**配网流程：**

1. ESP32 启动 BLE 广播
2. 手机 App 通过 BLE 写入 WiFi SSID、密码、服务器地址
3. ESP32 尝试连接 WiFi
4. 成功后保存配置到 Flash，关闭 BLE，进入正常通信

### 5.4 Web AP 配网 (Captive Portal)

BLE 配网超时或失败后的最终降级方案。

| 参数 | 值 | 说明 |
|------|------|------|
| AP SSID | `Pet-Setup` | 热点名称 |
| AP 密码 | `pet` + MAC 后缀 | 启动时根据 MAC 生成唯一密码 |
| 配网端口 | `80` | HTTP 服务端口 |
| 配网超时 | 120 秒 | 超时后重新进入 AP 模式 |

**配网流程：**

1. ESP32 启动 WiFi AP 模式
2. 用户连接 AP 后自动弹出配网页面 (Captive Portal)
3. 用户输入 WiFi SSID、密码、PC 服务器 IP 和端口
4. ESP32 保存配置到 Flash，尝试连接
5. 成功后进入正常通信

---

## 六、错误处理与恢复

### 6.1 帧溢出保护

| 错误场景 | 保护机制 | 位置 |
|----------|----------|------|
| 帧长度头超长 (>16 字符) | 丢弃，重置状态机 | ESP32 `FRAME_READ_LEN` |
| 帧长度值越界 (>256KB 或 <=0) | 丢弃，重置状态机 | ESP32 `FRAME_READ_LEN` |
| 帧体溢出 (>128KB) | 丢弃，重置状态机 | ESP32 `FRAME_READ_BODY` |
| 旧格式单帧溢出 (>32KB) | 丢弃，重置状态机 | ESP32 `FRAME_LEGACY_LINE` |
| PC 接收缓冲区溢出 (>512KB) | 清空缓冲区 | PC `_read_loop` |
| PC 帧长度越界 (>256KB 或 <=0) | 丢弃，重置 expected_len | PC `_read_loop` |
| 发送 payload 超大 (>128KB) | 拒绝发送，日志警告 | 两端发送函数 |

### 6.2 JSON 解析错误

| 场景 | 处理方式 |
|------|----------|
| PC 端收到无效 JSON | 日志警告 `收到无效JSON`，跳过当前消息 |
| ESP32 端 JSON 解析失败 | 日志错误，跳过当前消息 |
| ESP32 端 OOM 熔断 | 堆剩余 <16KB 时跳过所有 JSON 解析 |
| ESP32 端未知消息类型 | 忽略，不处理 |

### 6.3 心跳超时

**PC 端 (Keep-Alive 超时)：**

```
30 秒未收到 pong → 关闭 socket → 等待 ESP32 重新连入
```

- `_keepalive_loop` 线程检测 `_last_pong_time`
- 超时后关闭客户端 socket，标记 `_connected = False`
- 线程继续循环，等待 `_accept_loop` 接受新连接

**ESP32 端 (TCP Keep-Alive 超时)：**

```
60 秒空闲 → 每 10 秒探测 → 3 次无响应 → 判定断开
```

- 内核级 TCP keepalive 自动检测
- `_client.connected()` 返回 false 时触发重连

### 6.4 连接丢失恢复

**ESP32 端恢复流程：**

```
连接丢失
  ├─ 边沿触发：清理像素状态，切回正常模式
  ├─ 周期重连：每次 commTask 循环调用 reconnect()
  ├─ 指数退避：5s → 10s → 20s → 40s → 60s (上限)
  ├─ 10 次连续失败：WiFi 硬重置
  └─ 重连成功：重置退避计数，发送 handshake
```

**PC 端恢复流程：**

```
ESP32 断开
  ├─ _read_loop 检测到空数据
  ├─ 关闭旧 socket，标记 _connected = False
  ├─ _accept_loop 继续监听新连接
  └─ 新连接到来：接受连接，启动新读取线程，重启 Keep-Alive
```

### 6.5 发送队列溢出 (PC 端)

PC 端使用异步发送队列 (`Queue`, 最大 64 条) 防止发送阻塞：

```
队列满 → 丢弃最旧消息 → 放入新消息 → 日志警告
```

**实现：**

```python
try:
    self._send_queue.put_nowait(msg)  # 非阻塞入队
except Full:
    self._send_queue.get_nowait()     # 丢弃最旧
    self._send_queue.put_nowait(msg)  # 放入新消息
    logger.warning("发送队列已满，丢弃最旧消息")
```

### 6.6 像素传输错误

| 错误场景 | 处理方式 |
|----------|----------|
| Base64 解码失败 | 日志错误，丢弃当前 chunk |
| 解码后数据超过 PSRAM 池 (128KB) | 日志错误，丢弃当前 chunk |
| 分包索引不连续 | ESP32 以 `chunk_index == 0` 作为重置信号 |

---

## 附录

### A. 关键常量速查

| 常量 | 值 | 端 | 说明 |
|------|------|------|------|
| `SERVER_PORT` | 19876 | 两端 | TCP 通信端口 |
| `DEFAULT_UDP_BROADCAST_PORT` | 19877 | PC | UDP 广播端口 |
| `RECONNECT_INTERVAL` | 5000 ms | ESP32 | 初始重连间隔 |
| `OFFLINE_TIMEOUT_MS` | 45000 ms | ESP32 | 离线检测超时 |
| `SCREEN_DIM_TIMEOUT` | 30000 ms | ESP32 | 屏幕变暗超时 |
| `SCREEN_SLEEP_TIMEOUT` | 60000 ms | ESP32 | 屏幕休眠超时 |
| `KEEPALIVE_INTERVAL` | 10 s | PC | ping 发送间隔 |
| `KEEPALIVE_TIMEOUT` | 30 s | PC | pong 超时断连 |
| `SEND_QUEUE_MAXSIZE` | 64 | PC | 异步发送队列容量 |
| `MAX_FRAME_LEN` | 128 KB | PC | 发送帧大小上限 |
| `CLIENT_TCP_TIMEOUT` | 10 s | ESP32 | TCP 连接超时 |
| `CLIENT_READ_BUF_SIZE` | 512 B | ESP32 | TCP 读取缓冲区 |
| `JSON_PARSE_BUF_SIZE` | 4 KB | ESP32 | JSON 解析缓冲区 (PSRAM) |
| `PXL_POOL_SIZE` | 128 KB | ESP32 | 像素数据池 (PSRAM) |

### B. 协议版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 初始版本 | 换行分隔 JSON，无帧协议 |
| v2.0 | 当前版本 | 长度前缀帧协议，兼容 v1 fallback；新增 ping/pong、thinking_status、crash_report |
