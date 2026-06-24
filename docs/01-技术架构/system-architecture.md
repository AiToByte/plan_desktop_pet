# 系统架构全景图

> 本文档描述桌面电子宠物（Desktop Pet）项目的整体系统架构，涵盖 PC 监控端、网络通信层、ESP32 固件端三大层次的设计细节、模块职责、数据流以及关键设计决策。

---

## 一、三层架构概述

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PC 监控端 (Python)                            │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ AgentMonitor  │  │ TokenTracker │  │WeatherService│              │
│  │  进程检测      │  │  JSONL解析    │  │  API调用      │              │
│  │  CPU/内存分析  │  │  价格计算     │  │  缓存策略     │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                        │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────┴───────┐              │
│  │OTLPReceiver  │  │ThinkingChain │  │  TrayApp     │              │
│  │  HTTP 4318   │  │  状态分类     │  │  系统托盘     │              │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘              │
│         │                 │                                         │
│         └────────┬────────┘                                         │
│                  ▼                                                   │
│         ┌───────────────┐                                           │
│         │ Communication │  WiFi (TCP/UDP) 或 Serial                  │
│         │  帧协议封装    │                                           │
│         └───────┬───────┘                                           │
└─────────────────┼───────────────────────────────────────────────────┘
                  │  TCP 19876 / Serial 115200
                  │  帧协议: LEN:NNNN\n{json}
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     网络传输层                                       │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  TCP 长连接 (帧协议)                                         │   │
│   │  - 长度前缀: LEN:NNNN\n{payload}                            │   │
│   │  - 心跳保活: 每10秒 ping/pong                               │   │
│   │  - 断线重连: 指数退避 + 随机抖动                              │   │
│   └─────────────────────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  UDP 广播 (设备发现)                                         │   │
│   │  - PC 端每5秒广播: {"type":"server_announce","port":19876}  │   │
│   │  - ESP32 端监听后自动连接                                    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  mDNS 服务发现                                               │   │
│   │  - 主机名: deskpet.local                                     │   │
│   │  - 备选发现机制（UDP 广播失败时）                              │   │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ESP32 固件端 (C++/Arduino)                        │
│                                                                     │
│   ┌────────────────────────────┐  ┌────────────────────────────┐   │
│   │     Core 0: 通信核          │  │     Core 1: 渲染核          │   │
│   │     (8KB 栈)                │  │     (16KB 栈)               │   │
│   │                            │  │                            │   │
│   │  ┌──────────────────────┐  │  │  ┌──────────────────────┐  │   │
│   │  │    CommManager       │  │  │  │   DisplayManager     │  │   │
│   │  │    TCP客户端         │  │  │  │   LovyanGFX渲染      │  │   │
│   │  │    帧协议状态机       │  │  │  │   Sprite双缓冲       │  │   │
│   │  └──────────────────────┘  │  │  └──────────────────────┘  │   │
│   │  ┌──────────────────────┐  │  │  ┌──────────────────────┐  │   │
│   │  │    WiFiManager       │  │  │  │   PixelPlayer        │  │   │
│   │  │    WiFi STA连接      │  │  │  │   PXL解码/播放       │  │   │
│   │  │    mDNS + UDP        │  │  │  └──────────────────────┘  │   │
│   │  └──────────────────────┘  │  │  ┌──────────────────────┐  │   │
│   │  ┌──────────────────────┐  │  │  │   AmbientLight       │  │   │
│   │  │    WebConfig         │  │  │  │   BH1750光照传感      │  │   │
│   │  │    AP配网 + OTA      │  │  │  └──────────────────────┘  │   │
│   │  └──────────────────────┘  │  │  ┌──────────────────────┐  │   │
│   │  ┌──────────────────────┐  │  │  │   TouchHandler       │  │   │
│   │  │    BLEConfig         │  │  │  │   电容触摸+接近感应   │  │   │
│   │  │    BLE配网           │  │  │  └──────────────────────┘  │   │
│   │  └──────────────────────┘  │  │  ┌──────────────────────┐  │   │
│   │                            │  │  │   HapticDriver       │  │   │
│   │                            │  │  │   DRV2605L振动反馈   │  │   │
│   │                            │  │  └──────────────────────┘  │   │
│   │                            │  │  ┌──────────────────────┐  │   │
│   │                            │  │  │   SoundManager       │  │   │
│   │                            │  │  │   蜂鸣器音效         │  │   │
│   │                            │  │  └──────────────────────┘  │   │
│   └────────────────────────────┘  └────────────────────────────┘   │
│              │           共享内存: DisplayData 双缓冲           │    │
│              └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 各层职责

| 层级 | 技术栈 | 核心职责 |
|------|--------|---------|
| **PC 监控端** | Python 3.10+, psutil, pyserial | 采集系统状态（Agent 进程、Token 用量、天气）、通过 OTLP 接收思考链数据、组装 JSON 消息推送至 ESP32 |
| **网络传输层** | TCP/UDP, WiFi, Serial | PC 与 ESP32 之间的双向通信；帧协议保证消息完整性；心跳/重连保证连接可靠性 |
| **ESP32 固件端** | ESP32-S3, Arduino, FreeRTOS | 接收 JSON 数据、驱动 240x240 LCD 显示状态信息、管理传感器输入、处理休眠/唤醒策略 |

### 1.2 数据流向

```
PC 采集数据                    ESP32 接收显示
──────────────                 ──────────────
AgentMonitor ─┐               ┌─ DisplayManager (LCD渲染)
TokenStats   ─┼─ JSON序列化 ──┼─ PixelPlayer   (像素动画)
WeatherService┼──────────────→│─ SoundManager  (蜂鸣器音效)
OTLPReceiver ─┤  TCP/Serial   └─ HapticDriver  (振动反馈)
ThinkingChain─┘
     ↑
     │ 反向消息 (heartbeat, crash_report)
     └──────── ESP32 → PC ←────────────────
```

---

## 二、PC 端模块架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    main.py                                       │
│                                                                 │
│  ┌───────────────────────┐   ┌────────────────────────────────┐ │
│  │   DesktopPetMonitor   │   │      ThreadHealthGuard         │ │
│  │   主控制器             │   │      线程健康守护器             │ │
│  │                       │   │                                │ │
│  │  - 加载配置            │   │  - 心跳监控 (30s周期)          │ │
│  │  - 初始化所有模块      │   │  - 超时检测 (60s阈值)          │ │
│  │  - 主循环调度          │   │  - 自动重启死亡/卡死线程       │ │
│  │  - 数据聚合推送        │   │  - 工厂模式重建线程            │ │
│  └───────────┬───────────┘   └────────────────────────────────┘ │
│              │                                                   │
└──────────────┼───────────────────────────────────────────────────┘
               │ 聚合所有模块数据
               ▼
┌──────────────────────────────────────────────────────────────────┐
│                        子模块依赖关系                              │
│                                                                  │
│  ┌──────────────────┐                                            │
│  │   agent_monitor   │  进程检测 (psutil)                        │
│  │   AgentMonitor    │  - 扫描 claude/codex 等 AI Agent 进程     │
│  │                   │  - 采集 CPU%、内存MB、运行时长             │
│  │   AgentStatus     │  - 判断状态: IDLE/WORKING/AUTH            │
│  └────────┬─────────┘                                            │
│           │ → status, cpuPercent, memoryMB                       │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │   token_stats     │  JSONL 日志解析                            │
│  │   TokenTracker    │  - 解析 ~/.claude/projects/ 下的 JSONL     │
│  │                   │  - 统计 input/output tokens               │
│  │                   │  - 按模型计算费用 (USD)                    │
│  │                   │  - 滑动窗口统计每小时用量                   │
│  └────────┬─────────┘                                            │
│           │ → inputTokens, outputTokens, costUSD                  │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │   weather         │  天气 API                                  │
│  │   WeatherService  │  - 调用 OpenWeatherMap / 和风天气 API      │
│  │                   │  - 缓存策略 (减少 API 调用频率)            │
│  │                   │  - 解析: 城市、温度、体感、湿度、风速       │
│  └────────┬─────────┘                                            │
│           │ → city, temperature, description, iconCode            │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │   otlp_receiver   │  OTLP HTTP 接收器                         │
│  │   OTLPReceiver    │  - 监听 HTTP 端口 4318                     │
│  │                   │  - 接收 OpenTelemetry Span 数据            │
│  │                   │  - 提取 Claude Agent 的思考链 trace        │
│  └────────┬─────────┘                                            │
│           │ → span_callback (思考链步骤)                          │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  thinking_chain   │  思考链状态分类器                          │
│  │  ThinkingChain    │  - 将 OTLP Span 转换为 ThinkingState       │
│  │  Tracker          │  - 状态: IDLE/THINKING/TOOL_CALL/         │
│  │                   │         RESPONDING/ERROR/DONE              │
│  │                   │  - 维护状态转换历史                        │
│  └────────┬─────────┘                                            │
│           │ → thinkingState, stepText                             │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  communication    │  通信模块                                  │
│  │  WiFiCommunication│  - TCP Server 监听 19876                   │
│  │  SerialCommunication - UDP 广播设备发现 (19877)                │
│  │  CommunicationBase│  - 帧协议: LEN:NNNN\n{json}               │
│  │                   │  - 心跳: 10s ping, 30s 超时断连            │
│  │                   │  - 指数退避重连 + 随机抖动                 │
│  │                   │  - 异步发送队列 (Queue, maxsize=64)        │
│  └────────┬─────────┘                                            │
│           │ → DeviceMessage (msg_type, data, timestamp)           │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │   tray_app        │  系统托盘                                  │
│  │   TrayApp         │  - pystray 托盘图标                        │
│  │                   │  - StatusPanel 状态面板                    │
│  │                   │  - 右键菜单: 设置/关于/退出                │
│  └──────────────────┘                                            │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 核心模块详解

#### 2.1.1 DesktopPetMonitor (main.py)

主控制器，负责整个 PC 端的生命周期管理：

- **初始化阶段**: 加载 `config/config.json`，实例化所有子模块，注册 `ThreadHealthGuard` 监控
- **主循环**: 周期性采集 Agent 状态、Token 统计、天气数据，聚合为 JSON 消息通过通信模块推送到 ESP32
- **OTLP 回调**: 接收 `OTLPReceiver` 的 Span 回调，经过 `ThinkingChainTracker` 分类后实时转发

```python
# 数据聚合流程 (简化)
status = self.agent_monitor.get_status()       # Agent 状态
tokens = self.token_tracker.get_stats()         # Token 统计
weather = self.weather_service.get_weather()    # 天气信息
message = DeviceMessage(
    msg_type="status",
    data={"agent": status, "tokens": tokens, "weather": weather}
)
self.communication.send_message(message)        # 推送到 ESP32
```

#### 2.1.2 ThreadHealthGuard (main.py)

线程健康守护器，防止后台线程意外死亡导致系统静默失败：

- **注册机制**: 每个受监控线程注册一个 `thread_factory`（重建函数）和初始线程实例
- **心跳协议**: 被监控线程定期调用 `heartbeat(name)` 更新时间戳
- **检测逻辑**: 每 30 秒检查一次，线程死亡或心跳超时 60 秒则触发重启
- **重建策略**: 等待旧线程 3 秒退出，然后通过工厂函数创建新线程（不使用 `PyThreadState_SetAsyncExc`，跨平台可靠）

#### 2.1.3 AgentMonitor (agent_monitor.py)

基于 `psutil` 的 AI Agent 进程监控器：

- 扫描系统进程列表，识别 `claude`、`codex` 等 AI Agent 进程
- 采集 CPU 使用率、内存占用（MB）、运行时长（秒）
- 根据 CPU 负载判断状态：空闲 (IDLE) / 工作中 (WORKING) / 认证中 (AUTH)

#### 2.1.4 TokenTracker (token_stats.py)

Claude API Token 用量统计器：

- 解析 `~/.claude/projects/` 目录下的 JSONL 日志文件
- 统计 `input_tokens` 和 `output_tokens`
- 按模型（Opus/Sonnet/Haiku）计算费用（USD）
- 滑动窗口统计每小时 Token 用量

#### 2.1.5 WeatherService (weather.py)

天气信息采集服务：

- 调用外部天气 API（OpenWeatherMap 或和风天气）
- 内置缓存策略，减少 API 调用频率
- 输出结构化数据：城市、温度、体感温度、湿度、天气描述、图标代码、风速

#### 2.1.6 OTLPReceiver (otlp_receiver.py)

OpenTelemetry Protocol (OTLP) HTTP 接收器：

- 监听 HTTP 端口 4318（OTLP HTTP 标准端口）
- 接收 Claude Agent 发出的 OpenTelemetry Span 数据
- 提取思考链（Thinking Chain）trace 信息
- 通过回调函数将 Span 数据传递给 `ThinkingChainTracker`

#### 2.1.7 ThinkingChainTracker (thinking_chain.py)

思考链状态分类器：

- 将 OTLP Span 数据映射为六种状态：
  - `THINK_IDLE` (0): 空闲
  - `THINK_THINKING` (1): 思考中
  - `THINK_TOOL_CALL` (2): 调用工具
  - `THINK_RESPONDING` (3): 生成回复
  - `THINK_ERROR` (4): 出错
  - `THINK_DONE` (5): 完成
- 维护状态转换历史，支持 ESP32 端的滚动展示

#### 2.1.8 Communication (communication.py)

双模式通信模块，支持 WiFi 和串口两种连接方式：

| 类 | 传输方式 | 端口/端口 | 说明 |
|----|---------|----------|------|
| `WiFiCommunication` | TCP Server | 19876 | PC 作为服务器，ESP32 主动连接 |
| `SerialCommunication` | USB 串口 | COM3 (可配置) | 直接串口通信，调试用 |
| `CommunicationBase` | 抽象基类 | - | 定义统一接口：connect/disconnect/send_message |

关键特性：
- **帧协议**: `LEN:NNNN\n{json_payload}`，保证消息完整性
- **心跳保活**: 每 10 秒发送 ping，30 秒无 pong 视为断连
- **指数退避重连**: 失败后等待时间指数增长 + 随机抖动，避免重连风暴
- **异步发送队列**: `Queue(maxsize=64)`，发送线程独立于采集线程
- **UDP 广播发现**: PC 端每 5 秒广播 `server_announce` 消息，ESP32 监听后自动连接

#### 2.1.9 TrayApp (tray_app.py)

系统托盘应用：

- 使用 `pystray` 创建系统托盘图标
- `StatusPanel` 显示实时状态面板
- 右键菜单：查看状态、设置、关于、退出

### 2.2 消息格式

PC 端推送到 ESP32 的 JSON 消息格式：

```json
{
  "type": "status",
  "data": {
    "agent": {
      "status": 1,
      "thinkingState": 2,
      "processName": "claude",
      "cpuPercent": 45.2,
      "memoryMB": 512.3,
      "uptimeSeconds": 3600
    },
    "tokens": {
      "inputTokens": 15000,
      "outputTokens": 8000,
      "totalRequests": 42,
      "hourTokens": 5000,
      "costUSD": 0.85
    },
    "weather": {
      "city": "Shanghai",
      "temperature": 28.5,
      "feelsLike": 31.2,
      "humidity": 75,
      "description": "多云",
      "iconCode": "04d",
      "windSpeed": 3.2
    }
  },
  "ts": 1719206400000
}
```

ESP32 端发送到 PC 的消息：

```json
{"type": "heartbeat", "ts": 1719206400000}
{"type": "crash_report", "data": {"count": 3, "reason": 1}, "ts": 1719206400000}
```

---

## 三、ESP32 固件端模块架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        main.cpp                                      │
│                  FreeRTOS 双核架构                                    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    全局共享数据                                │   │
│  │                                                             │   │
│  │   DisplayData g_displayBuf[2]     // 双缓冲 (front/back)    │   │
│  │   atomic<int> g_frontIdx          // 前端缓冲索引            │   │
│  │   atomic<bool> g_forceWake        // 强制唤醒标志            │   │
│  │   uint8_t g_pxlPool[128KB]        // PSRAM 像素池            │   │
│  │   char g_jsonParseBuf[4KB]        // PSRAM JSON 解析缓冲     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ╔═══════════════════════════════╗  ╔═══════════════════════════════╗│
│  ║     Core 0: 通信核            ║  ║     Core 1: 渲染核            ║│
│  ║     commTask (8KB 栈)         ║  ║     renderTask (16KB 栈)      ║│
│  ║                               ║  ║                               ║│
│  ║  ┌─────────────────────────┐  ║  ║  ┌─────────────────────────┐  ║│
│  ║  │    CommManager          │  ║  ║  │    DisplayManager       │  ║│
│  ║  │                         │  ║  ║  │                         │  ║│
│  ║  │  WiFiClient _client     │  ║  ║  │  LGFX (LovyanGFX)      │  ║│
│  ║  │  帧协议状态机:           │  ║  ║  │  Panel_ST7789           │  ║│
│  ║  │   FRAME_IDLE            │  ║  ║  │  Bus_SPI (80MHz/DMA)    │  ║│
│  ║  │   FRAME_READ_LEN        │  ║  ║  │                         │  ║│
│  ║  │   FRAME_READ_BODY       │  ║  ║  │  渲染模式:              │  ║│
│  ║  │   FRAME_LEGACY_LINE     │  ║  ║  │   NormalMode (状态显示) │  ║│
│  ║  │                         │  ║  ║  │   PixelMode  (像素动画) │  ║│
│  ║  │  批量读取: 512B 缓冲    │  ║  ║  │                         │  ║│
│  ║  │  指数退避重连            │  ║  ║  │  Sprite 双缓冲渲染      │  ║│
│  ║  └─────────────────────────┘  ║  ║  │  VSync 垂直同步         │  ║│
│  ║                               ║  ║  └─────────────────────────┘  ║│
│  ║  ┌─────────────────────────┐  ║  ║                               ║│
│  ║  │    WiFiManager          │  ║  ║  ┌─────────────────────────┐  ║│
│  ║  │                         │  ║  ║  │    PixelPlayer          │  ║│
│  ║  │  WiFi STA 模式连接      │  ║  ║  │                         │  ║│
│  ║  │  mDNS 注册/发现         │  ║  ║  │  PXL 格式解码           │  ║│
│  ║  │  UDP 广播监听            │  ║  ║  │  差分帧协议:            │  ║│
│  ║  │  WiFi 省电策略:          │  ║  ║  │   DELTA_FULL (完整帧)   │  ║│
│  ║  │   ACTIVE/MODEM/LIGHT    │  ║  ║  │   DELTA_DIFF (差分帧)   │  ║│
│  ║  │  DTIM beacon 管理       │  ║  ║  │  RLE 压缩解码           │  ║│
│  ║  └─────────────────────────┘  ║  ║  └─────────────────────────┘  ║│
│  ║                               ║  ║                               ║│
│  ║  ┌─────────────────────────┐  ║  ║  ┌─────────────────────────┐  ║│
│  ║  │    WebConfig            │  ║  ║  │    AmbientLightManager  │  ║│
│  ║  │                         │  ║  ║  │                         │  ║│
│  ║  │  AP 模式配网            │  ║  ║  │  BH1750 光照传感器      │  ║│
│  ║  │  热点: Pet-Setup        │  ║  ║  │  I2C: GPIO41/42         │  ║│
│  ║  │  Web 页面设置 WiFi      │  ║  ║  │  自动亮度调节           │  ║│
│  ║  │  OTA 固件升级            │  ║  ║  │  2秒采样周期            │  ║│
│  ║  └─────────────────────────┘  ║  ║  └─────────────────────────┘  ║│
│  ║                               ║  ║                               ║│
│  ║  ┌─────────────────────────┐  ║  ║  ┌─────────────────────────┐  ║│
│  ║  │    BLEConfig            │  ║  ║  │    TouchHandler         │  ║│
│  ║  │                         │  ║  ║  │                         │  ║│
│  ║  │  NimBLE 低功耗蓝牙配网  │  ║  ║  │  电容触摸: GPIO1        │  ║│
│  ║  │  BLE GATT 服务          │  ║  ║  │  接近感应: EMA差分检测  │  ║│
│  ║  │  手机 App 配置 WiFi     │  ║  ║  │  长按检测: 1000ms       │  ║│
│  ║  └─────────────────────────┘  ║  ║  │  触摸唤醒: RTC支持      │  ║│
│  ║                               ║  ║  └─────────────────────────┘  ║│
│  ║  ┌─────────────────────────┐  ║  ║                               ║│
│  ║  │    心跳 + 重连           │  ║  ║  ┌─────────────────────────┐  ║│
│  ║  │                         │  ║  ║  │    HapticDriver         │  ║│
│  ║  │  每10秒发送 heartbeat   │  ║  ║  │                         │  ║│
│  ║  │  45秒无数据 → OFFLINE   │  ║  ║  │  DRV2605L 触觉反馈      │  ║│
│  ║  │  边沿触发断连清理       │  ║  ║  │  I2C: 与BH1750共享总线  │  ║│
│  ║  │  崩溃遥测上报            │  ║  ║  │  振动模式反馈           │  ║│
│  ║  └─────────────────────────┘  ║  ║  └─────────────────────────┘  ║│
│  ║                               ║  ║                               ║│
│  ║                               ║  ║  ┌─────────────────────────┐  ║│
│  ║                               ║  ║  │    SoundManager         │  ║│
│  ║                               ║  ║  │                         │  ║│
│  ║                               ║  ║  │  无源蜂鸣器: GPIO18     │  ║│
│  ║                               ║  ║  │  PWM 音调播放           │  ║│
│  ║                               ║  ║  └─────────────────────────┘  ║│
│  ╚═══════════════════════════════╝  ╚═══════════════════════════════╝│
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    原子标志 (跨核通信)                        │   │
│  │                                                             │   │
│  │  atomic<bool> g_pendingNormalMode    // 切回普通模式         │   │
│  │  atomic<bool> g_pendingPixelPlay     // 播放像素动画         │   │
│  │  atomic<bool> g_pendingPixelStop     // 停止像素动画         │   │
│  │  atomic<bool> g_pendingPixelBufferLoad // 加载像素缓冲       │   │
│  │  atomic<uint8_t*> g_pendingPixelBufferPtr // 缓冲区指针      │   │
│  │  atomic<size_t> g_pendingPixelSize   // 缓冲区大小           │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 模块清单

| 模块 | 文件 | 运行核 | 职责 |
|------|------|--------|------|
| CommManager | comm_manager.h/cpp | Core 0 | TCP 客户端、帧协议解析、心跳发送、断线重连 |
| WiFiManager | wifi_manager.h/cpp | Core 0 | WiFi STA 连接、mDNS 注册、UDP 广播监听、省电策略 |
| WebConfig | web_config.h/cpp | Core 0 | AP 模式配网、Web 设置页面、OTA 固件升级 |
| BLEConfig | ble_config.h/cpp | Core 0 | NimBLE 蓝牙配网、GATT 服务 |
| DisplayManager | display_manager.h/cpp | Core 1 | LovyanGFX 渲染引擎、Sprite 管理、动画系统、亮度控制 |
| PixelPlayer | pixel_player.h/cpp | Core 1 | PXL 格式解码、差分帧处理、RLE 解压缩、播放控制 |
| AmbientLightManager | ambient_light.h/cpp | Core 1 | BH1750 光照采集、自动背光调节 |
| TouchHandler | touch_handler.h/cpp | Core 1 | 电容触摸检测、接近感应 (EMA 差分)、长按识别 |
| HapticDriver | haptic_driver.h/cpp | Core 1 | DRV2605L 触觉反馈驱动、振动模式 |
| SoundManager | sound_manager.h/cpp | Core 1 | 无源蜂鸣器 PWM 音调播放 |

---

## 四、双核分工详解

ESP32-S3 搭载 Xtensa LX7 双核处理器，本项目采用 **通信/渲染分离** 的双核架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                     ESP32-S3 双核架构                             │
│                                                                 │
│  ┌──────────────────────────┐  ┌──────────────────────────┐    │
│  │       Core 0             │  │       Core 1             │    │
│  │       通信核              │  │       渲染核              │    │
│  │       (8KB 栈)            │  │       (16KB 栈)           │    │
│  │                          │  │                          │    │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │    │
│  │  │ WiFi 协议栈        │  │  │  │ LCD SPI 驱动       │  │    │
│  │  │ (lwIP + WiFi驱动)  │  │  │  │ (80MHz + DMA)      │  │    │
│  │  └────────────────────┘  │  │  └────────────────────┘  │    │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │    │
│  │  │ TCP 收发           │  │  │  │ Sprite 渲染        │  │    │
│  │  │ (WiFiClient)       │  │  │  │ (LovyanGFX)        │  │    │
│  │  └────────────────────┘  │  │  └────────────────────┘  │    │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │    │
│  │  │ JSON 解析          │  │  │  │ 动画系统           │  │    │
│  │  │ (ArduinoJson)      │  │  │  │ (表情/天气图标)    │  │    │
│  │  └────────────────────┘  │  │  └────────────────────┘  │    │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │    │
│  │  │ 心跳/重连          │  │  │  │ 传感器读取         │  │    │
│  │  │ (10s/指数退避)     │  │  │  │ (BH1750/触摸)      │  │    │
│  │  └────────────────────┘  │  │  └────────────────────┘  │    │
│  │                          │  │  ┌────────────────────┐  │    │
│  │  CPU 密集度: 低          │  │  │ 休眠管理           │  │    │
│  │  I/O 密集度: 高          │  │  │ (Dim/Sleep/Light)  │  │    │
│  │  阻塞点: WiFi/TCP        │  │  └────────────────────┘  │    │
│  │                          │  │                          │    │
│  │                          │  │  CPU 密集度: 高          │    │
│  │                          │  │  I/O 密集度: 中 (SPI)    │    │
│  │                          │  │  阻塞点: SPI DMA 传输    │    │
│  └──────────────────────────┘  └──────────────────────────┘    │
│                                                                 │
│  通信方式: DisplayData 双缓冲 + atomic 指针交换 (无锁)          │
│  跨核操作: atomic<bool> pending 标志 (Core 0 设置, Core 1 执行) │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 为什么选择双核

| 问题 | 单核方案 | 双核方案 |
|------|---------|---------|
| WiFi 收数据时 LCD 刷新卡顿 | WiFi 协议栈中断渲染，画面撕裂 | 各核独立运行，互不阻塞 |
| TCP 阻塞读取导致动画掉帧 | 必须轮询检查，增加延迟 | Core 0 专心收发，Core 1 专心渲染 |
| JSON 解析占用 CPU 时间 | 解析期间显示冻结 | 解析在 Core 0，显示在 Core 1 并行 |
| 传感器读取与通信冲突 | I2C/SPI 总线竞争 | 传感器 I2C 在 Core 1，WiFi 在 Core 0 |

### 4.2 Core 0 通信核详解

```cpp
void commTask(void* pvParameters) {
    // 栈大小: 8KB (COMM_TASK_STACK = 8192)
    // 主循环周期: 10ms (vTaskDelay)

    while (true) {
        // 1. Web 配网模式处理
        if (wifi.isConfiguring()) {
            wifi.handleConfig();
            continue;
        }

        // 2. 通信更新 (TCP 收发)
        comm.update();

        // 3. 接收数据 → JSON 解析 → 双缓冲写入
        if (comm.hasNewData()) {
            String json = comm.getData();
            parseServerData(json);
            // 写入 back buffer → atomic swap
        }

        // 4. 离线检测 (45 秒无数据)
        if (timeout) markOffline();

        // 5. BOOT 键处理 (GPIO0)
        //    - 休眠中: 唤醒屏幕 15 秒
        //    - 普通模式: 停止像素播放

        // 6. 断连检测 + 重连 (边沿触发)
        if (disconnected) comm.reconnect();

        // 7. 心跳发送 (每 10 秒)
        if (heartbeatTimeout) comm.sendHeartbeat();

        // 8. 崩溃遥测 (首次连接后)
        if (crashCount > 0) sendCrashReport();

        vTaskDelay(10ms);  // 让出 CPU，避免看门狗超时
    }
}
```

### 4.3 Core 1 渲染核详解

```cpp
void renderTask(void* pvParameters) {
    // 栈大小: 16KB (RENDER_TASK_STACK = 16384)
    // 主循环周期: 动态 (休眠时 500ms, 正常时 ~16ms)

    DisplayData localData;  // 本地副本，减少原子操作

    while (true) {
        // 1. 读取 front buffer (原子指针交换)
        localData = g_displayBuf[g_frontIdx.load()];

        // 2. 屏幕休眠管理
        //    - 30秒无数据 → 变暗
        //    - 60秒无数据 → 休眠 (关背光)
        //    - 5分钟休眠 → ESP32 Light Sleep (超低功耗)
        //    - 数据到达 → 立即唤醒 (CPU 240MHz, WiFi active)

        // 3. 处理 Core 0 的待执行显示操作
        //    顺序: pixelStop → normalMode → pixelPlay
        //    (避免状态竞争)

        // 4. VSync 垂直同步 (防撕裂)
        display.waitForVSync();

        // 5. 显示更新 (每 1 秒)
        display.update(localData);

        // 6. 动画更新 (每 500ms)
        display.updateAnimation();

        // 7. 背光平滑过渡
        display.applySmoothBacklight();

        // 8. 温控自适应 (每 10 秒)
        //    > 65°C → CPU 80MHz
        //    > 55°C → CPU 160MHz
        //    < 50°C → CPU 240MHz

        // 9. 堆/栈监控 (每 5 秒)
        //    打印 PSRAM/Internal 堆水位 + 栈高水位
    }
}
```

---

## 五、共享数据机制

### 5.1 DisplayData 双缓冲

```
┌──────────────────────────────────────────────────────────────┐
│                    DisplayData 双缓冲                         │
│                                                              │
│   g_displayBuf[0]          g_displayBuf[1]                   │
│  ┌──────────────────┐    ┌──────────────────┐               │
│  │  DisplayData      │    │  DisplayData      │               │
│  │  ┌──────────────┐ │    │  ┌──────────────┐ │               │
│  │  │ AgentState   │ │    │  │ AgentState   │ │               │
│  │  │ TokenStats   │ │    │  │ TokenStats   │ │               │
│  │  │ WeatherInfo  │ │    │  │ WeatherInfo  │ │               │
│  │  │ lastUpdate   │ │    │  │ lastUpdate   │ │               │
│  │  │ connected    │ │    │  │ connected    │ │               │
│  │  │ thinking*    │ │    │  │ thinking*    │ │               │
│  │  └──────────────┘ │    │  └──────────────┘ │               │
│  └──────────────────┘    └──────────────────┘               │
│           ▲                        ▲                         │
│           │                        │                         │
│        front (读)               back (写)                    │
│        Core 1                   Core 0                       │
│                                                              │
│   g_frontIdx (atomic<int>)                                   │
│   ┌─────┐                                                    │
│ 0 │  0  │ → front = buf[0], back = buf[1]                    │
│   ├─────┤                                                    │
│ 1 │  1  │ → front = buf[1], back = buf[0]                    │
│   └─────┘                                                    │
└──────────────────────────────────────────────────────────────┘
```

**写入流程 (Core 0)**:

```cpp
// 1. 读取当前 front 索引 (acquire 语义)
int front = g_frontIdx.load(std::memory_order_acquire);
int backIdx = 1 - front;

// 2. 复制 front → back (继承历史数据)
g_displayBuf[backIdx] = g_displayBuf[front];

// 3. 修改 back buffer (写入新数据)
g_displayBuf[backIdx].connected = true;
g_displayBuf[backIdx].lastUpdate = now;

// 4. 原子交换 front 指针 (release 语义)
g_frontIdx.store(backIdx, std::memory_order_release);
```

**读取流程 (Core 1)**:

```cpp
// 1. 读取 front 索引 (acquire 语义)
int frontIdx = g_frontIdx.load(std::memory_order_acquire);

// 2. 拷贝到本地变量 (减少原子操作持有时间)
localData = g_displayBuf[frontIdx];

// 3. 使用 localData 渲染 (完全本地，无竞争)
display.update(localData);
```

### 5.2 原子标志 (跨核操作委托)

Core 0 不能直接调用 LCD/SPI 操作（SPI 总线由 Core 1 独占），因此通过原子标志委托 Core 1 执行：

```
Core 0 (通信核)                    Core 1 (渲染核)
─────────────────                  ─────────────────
收到 pixel_data                    每帧检查 pending 标志
    │                                   │
    ▼                                   ▼
g_pendingPixelBufferLoad = true    if (g_pendingPixelBufferLoad) {
g_pendingPixelBufferPtr = buf          pixelPlayer.loadFromBuffer(buf, size);
g_pendingPixelSize = size              g_pendingPixelPlay = true;
                                       }
```

### 5.3 为什么不用 Mutex

| 方案 | 优点 | 缺点 | 本项目选择 |
|------|------|------|-----------|
| **Mutex** | 简单直观 | 阻塞渲染核，LCD 刷新卡顿 | 不采用 |
| **双缓冲 + atomic** | 无锁、无阻塞、渲染零延迟 | 需要复制数据 | **采用** |
| **环形缓冲** | 多帧缓冲、高吞吐 | 实现复杂、内存占用大 | 不需要 |

**性能分析**:
- `DisplayData` 结构体约 200 字节，memcpy 复制耗时 < 1μs (240MHz CPU)
- Mutex lock/unlock 在 FreeRTOS SMP 下约 5-10μs，且可能导致优先级反转
- 双缓冲方案保证渲染核永远不会被通信核阻塞，帧率稳定

---

## 六、依赖关系

### 6.1 ESP32 固件依赖 (PlatformIO)

```ini
[env:esp32s3]
platform = espressif32          ; ESP32-S3 开发平台
board = esp32-s3-devkitc-1      ; 微雪 ESP32-S3 开发板
framework = arduino              ; Arduino 框架

lib_deps =
    lovyan03/LovyanGFX@^1.1.8   ; LCD 渲染引擎 (SPI/DMA)
    bblanchon/ArduinoJson@^6.21.0 ; JSON 解析库
    ESPmDNS                      ; mDNS 服务发现
    h2zero/NimBLE-Arduino@^1.4.0 ; BLE 低功耗蓝牙

; 内存配置
board_build.arduino.memory_type = qio_opi  ; PSRAM QIO OPI 模式
board_build.partitions = huge_app.csv       ; 大应用分区表
build_flags =
    -DBOARD_HAS_PSRAM           ; 启用 PSRAM 支持
    -std=c++17                  ; C++17 标准
```

### 6.2 PC 端依赖 (Python)

```
psutil>=5.9.0       # 系统进程监控 (AgentMonitor)
requests>=2.28.0    # HTTP 请求 (天气 API, OTLP 接收)
pyserial>=3.5       # 串口通信 (SerialCommunication)
```

隐式依赖（标准库或框架内置）:
- `socket` / `threading` / `queue`: WiFi 通信、异步队列
- `json` / `pathlib` / `logging`: 配置加载、日志记录
- `pystray`: 系统托盘（需额外安装）
- `dataclasses`: 数据类定义

### 6.3 硬件依赖

| 组件 | 型号 | 接口 | 用途 |
|------|------|------|------|
| 主控 | ESP32-S3 | - | 双核处理器 + WiFi + BLE |
| LCD | 微雪 1.54" 240x240 | SPI (80MHz) | ST7789V 显示驱动 |
| 光照传感器 | BH1750 | I2C (GPIO41/42) | 环境光检测 |
| 触觉反馈 | DRV2605L | I2C (共享) | 振动反馈 |
| 蜂鸣器 | 无源蜂鸣器 | PWM (GPIO18) | 音效播放 |
| 触摸 | 电容触摸 | GPIO1 | 触摸/接近感应 |
| PSRAM | 8MB OPI | 内部总线 | 像素池 + JSON 缓冲 |

---

## 七、关键设计决策

### 7.1 双缓冲 vs Mutex

**决策**: 采用 DisplayData 双缓冲 + `std::atomic<int>` 指针交换

**理由**:
1. **渲染核零阻塞**: Core 1 渲染 LCD 时不需要等待 Core 0 释放锁
2. **确定性延迟**: 原子操作耗时恒定 (~100ns)，Mutex 最坏情况可达数十 μs
3. **无优先级反转**: FreeRTOS Mutex 在 SMP 下可能出现优先级反转，原子操作无此问题
4. **实现简单**: 只需 2 个缓冲区 + 1 个原子索引，代码量少

**代价**: 每次写入需 memcpy 整个 DisplayData (~200 字节)，但 < 1μs 可忽略

### 7.2 PSRAM 静态池 vs malloc

**决策**: 像素缓冲区使用 PSRAM 静态预分配池 (`g_pxlPool[128KB]`)

```cpp
__attribute__((section(".psram")))
static uint8_t g_pxlPool[32 * 32 * 2 * 64];  // 128KB 静态池
```

**理由**:
1. **碎片化防护**: 长时间运行的嵌入式系统，频繁 malloc/free 会导致堆碎片化，最终 OOM
2. **确定性分配**: 静态池在编译时分配，运行时无分配失败风险
3. **PSRAM 优化**: ESP32-S3 的 PSRAM 带宽有限，静态分配避免了分配器元数据开销
4. **零内存泄漏**: 池化管理，无需 free，程序退出时统一回收

**同理**: JSON 解析缓冲区也使用 PSRAM 静态分配 (`g_jsonParseBuf[4KB]`)

### 7.3 TCP 帧协议 vs 原始 JSON

**决策**: 采用长度前缀帧协议 `LEN:NNNN\n{payload}`

```
┌─────────────────────────────────────────────────┐
│              TCP 帧协议格式                       │
│                                                 │
│  LEN:128\n{"type":"status","data":{...},"ts":0} │
│  ├──────┤ ├────────────────────────────────────┤ │
│  长度前缀  JSON payload (精确 128 字节)           │
│  (可变长)  (按长度读取，不依赖分隔符)              │
│                                                 │
│  状态机:                                        │
│  IDLE → READ_LEN → READ_BODY → (回调)           │
│         ↑                                      │
│         检测 "LEN:" 前缀                        │
│                                                 │
│  兼容模式:                                      │
│  FRAME_LEGACY_LINE: \n 分隔的旧格式             │
└─────────────────────────────────────────────────┘
```

**理由**:
1. **消息完整性**: 长度前缀保证读取完整的 JSON 消息，不会出现半包/粘包
2. **二进制兼容**: 像素数据可能包含任意字节，\n 分隔符会冲突
3. **向后兼容**: 状态机同时支持新帧协议和旧 \n 分隔格式
4. **性能**: 批量读取 (512B 缓冲) 减少系统调用次数

### 7.4 FreeRTOS vs 裸 Arduino

**决策**: 采用 FreeRTOS 双核任务架构

**理由**:
1. **任务隔离**: 通信和渲染运行在独立核心，互不干扰
2. **栈隔离**: 每个任务有独立栈空间 (8KB/16KB)，防止栈溢出互相影响
3. **优先级管理**: FreeRTOS 调度器自动管理任务优先级
4. **生态成熟**: ESP32 Arduino 框架底层就是 FreeRTOS，直接使用无额外开销
5. **调试便利**: FreeRTOS 提供任务状态查询、栈高水位监控等调试工具

### 7.5 WiFi 省电策略

```
┌──────────────────────────────────────────────────────────────┐
│                    WiFi 省电状态机                             │
│                                                              │
│  ┌──────────┐    30s无数据    ┌──────────┐                   │
│  │  ACTIVE  │ ─────────────→ │ MODEM    │                   │
│  │  240MHz  │                 │ SLEEP    │                   │
│  │  WiFi    │ ←───────────── │ 80MHz    │                   │
│  │  全速     │   数据到达      │ DTIM=3   │                   │
│  └──────────┘                 └────┬─────┘                   │
│                                    │                         │
│                           5min无交互                          │
│                                    ▼                         │
│                              ┌──────────┐                   │
│                              │  LIGHT   │                   │
│                              │  SLEEP   │                   │
│                              │  超低功耗 │                   │
│                              │  触摸唤醒 │                   │
│                              └──────────┘                   │
│                                                              │
│  唤醒触发:                                                   │
│  - g_forceWake (通信收到数据)                                │
│  - 触摸事件 (esp_sleep_enable_touchpad_wakeup)              │
│  - BOOT 键 (GPIO0)                                          │
└──────────────────────────────────────────────────────────────┘
```

### 7.6 跨核操作委托模式

**问题**: Core 0 (通信核) 收到像素数据后需要调用 `PixelPlayer.loadFromBuffer()`，但该操作涉及 SPI 总线，而 SPI 总线由 Core 1 (渲染核) 独占。

**解决方案**: 通过 `std::atomic` 标志位实现跨核操作委托：

```
Core 0 (生产者)                     Core 1 (消费者)
──────────────                      ──────────────
1. 解析像素数据到 PSRAM 池          每帧循环检查:
2. 设置原子标志:                       │
   g_pendingPixelBufferLoad = true     ├─ g_pendingPixelStop?
   g_pendingPixelBufferPtr = buf       ├─ g_pendingNormalMode?
   g_pendingPixelSize = size           ├─ g_pendingPixelPlay?
3. 立即返回 (不阻塞)                   └─ g_pendingPixelBufferLoad?
                                        │
                                        ▼
                                    在 Core 1 的时间片内执行:
                                    pixelPlayer.loadFromBuffer()
                                    (安全访问 SPI 总线)
```

**关键设计点**:
- 使用 `std::memory_order_release` (Core 0 写) 和 `std::memory_order_acquire` (Core 1 读) 保证内存可见性
- 执行顺序严格控制: `pixelStop → normalMode → pixelPlay`，避免状态竞争
- Core 0 只设置标志和指针，不执行任何 SPI 操作

### 7.7 崩溃恢复机制

```
┌──────────────────────────────────────────────────────────────┐
│                    崩溃恢复流程                                │
│                                                              │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │  崩溃     │ ──→ │ RTC_NOINIT│ ──→ │ 重启     │            │
│  │  发生     │     │ 计数器+1 │     │ 检测     │            │
│  └──────────┘     └──────────┘     └────┬─────┘            │
│                                         │                   │
│                                         ▼                   │
│                                  ┌──────────┐               │
│                                  │ 首次连接  │               │
│                                  │ 后上报    │               │
│                                  └────┬─────┘               │
│                                       │                     │
│                                       ▼                     │
│                              ┌──────────────────┐           │
│                              │ crash_report 消息 │           │
│                              │ {                 │           │
│                              │   count: 3,       │           │
│                              │   reason: 1       │           │
│                              │ }                 │           │
│                              └──────────────────┘           │
│                                                              │
│  RTC_NOINIT_ATTR: 重启不丢失的 RTC 内存变量                  │
│  CRASH_MAGIC (0xDEADBEEF): 区分冷启动和崩溃重启              │
└──────────────────────────────────────────────────────────────┘
```

---

## 附录：文件结构总览

```
plan_desktop_pet/
├── esp32_firmware/
│   ├── platformio.ini              # PlatformIO 构建配置
│   ├── include/
│   │   ├── config.h                # 全局配置 (引脚/超时/阈值)
│   │   └── types.h                 # 数据结构定义
│   └── src/
│       ├── main.cpp                # 主程序 (FreeRTOS 双核入口)
│       ├── display_manager.h/cpp   # 显示管理器 (LovyanGFX)
│       ├── comm_manager.h/cpp      # 通信管理器 (TCP 帧协议)
│       ├── wifi_manager.h/cpp      # WiFi 管理器 (STA/mDNS/UDP)
│       ├── web_config.h/cpp        # Web 配网 + OTA
│       ├── ble_config.h/cpp        # BLE 配网 (NimBLE)
│       ├── pixel_player.h/cpp      # PXL 像素播放器
│       ├── ambient_light.h/cpp     # BH1750 光照传感器
│       ├── touch_handler.h/cpp     # 触摸/接近感应
│       ├── haptic_driver.h/cpp     # DRV2605L 触觉反馈
│       ├── sound_manager.h/cpp     # 蜂鸣器音效
│       ├── spring_animation.h/cpp  # 弹簧动画系统
│       └── log.h                   # 统一日志宏
│
├── pc_monitor/
│   ├── main.py                     # 主程序 (DesktopPetMonitor)
│   ├── tray_app.py                 # 系统托盘 (TrayApp)
│   ├── requirements.txt            # Python 依赖
│   └── modules/
│       ├── agent_monitor.py        # Agent 进程监控
│       ├── token_stats.py          # Token 统计
│       ├── weather.py              # 天气服务
│       ├── communication.py        # 通信模块 (WiFi/Serial)
│       ├── otlp_receiver.py        # OTLP HTTP 接收器
│       └── thinking_chain.py       # 思考链状态分类
│
└── pixel_tool/
    ├── pixel_tool.py               # 像素编辑工具
    └── pxl_encoder.py              # PXL 格式编码器
```
