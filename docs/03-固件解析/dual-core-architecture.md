# FreeRTOS 双核架构详解

> 本文档基于 `esp32_firmware/src/main.cpp`、`include/config.h`、`include/types.h`、
> `src/comm_manager.cpp`、`src/comm_manager.h`、`src/display_manager.h` 的实际代码编写。

---

## 一、ESP32-S3 双核 SMP 概述

ESP32-S3 搭载 Xtensa LX7 双核处理器，两个核心共享同一块 SRAM 和 PSRAM，运行
FreeRTOS SMP（对称多处理）调度器。与非对称架构不同，SMP 模式下任一核心可以运行任一
任务，调度器根据任务优先级和核心亲和性自动分配。

本项目采用 **核心亲和性绑定** 策略，将两个长期运行的任务分别固定到不同核心，避免
任务迁移带来的缓存抖动：

| 核心 | 任务 | 职责 |
|------|------|------|
| Core 0 | `commTask` | WiFi/TCP 通信、JSON 解析、心跳、离线检测 |
| Core 1 | `renderTask` | LCD 显示更新、动画渲染、休眠管理、温控 |

两个核心通过 **原子变量 + 双缓冲** 交换数据，无需互斥锁（Mutex），消除了锁竞争
导致的阻塞和优先级反转风险。

---

## 二、Core 0 通信任务

### 2.1 任务配置

```cpp
// config.h
#define COMM_TASK_CORE    0       // 绑定 Core 0
#define COMM_TASK_STACK   8192   // 栈大小 8KB

// main.cpp setup()
xTaskCreatePinnedToCore(
    commTask,           // 任务函数
    "CommTask",         // 任务名
    COMM_TASK_STACK,    // 8192 字节
    NULL,               // 无参数
    2,                  // 优先级 2（高于渲染任务）
    &g_commTaskHandle,  // 任务句柄（供 OTA 挂起使用）
    COMM_TASK_CORE      // Core 0
);
```

优先级设为 2，高于渲染任务的 1，确保网络数据及时处理，不会因渲染占用 CPU 而丢失
TCP 数据包。

### 2.2 主循环结构

通信任务的主循环每 10ms 执行一次（`vTaskDelay(pdMS_TO_TICKS(10))`），按以下
顺序处理：

```
while (true) {
    1. Web 配网检查  →  若正在配网则跳过其余逻辑
    2. comm.update() →  TCP 数据读取 + 帧协议解析
    3. 数据到达?     →  parseServerData() + 双缓冲写入
    4. 离线检测      →  45 秒无数据 → OFFLINE
    5. BOOT 键处理   →  停止像素播放 / 唤醒屏幕
    6. 断连重连      →  边沿触发清理 + 周期性 reconnect()
    7. 心跳          →  每 10 秒发送一次
    8. 崩溃遥测      →  首次连接后上报 crash_report
    9. vTaskDelay(10ms)
}
```

### 2.3 WiFi 状态机

WiFi 连接由 `WiFiManager` 模块管理，在 `setup()` 阶段完成初始化：

```cpp
wifi.begin();
if (wifi.connect()) {
    // 同步 NTP 时间（东八区）
    configTime(8 * 3600, 0, "ntp.aliyun.com", "ntp1.aliyun.com");
    // 设置通信服务器地址
    comm.setServer(serverHost, serverPort);
} else {
    display.showBootScreen("WiFi Failed!");
}
```

WiFi 断连后，通信任务通过 `comm.reconnect()` 进行指数退避重连。连续失败 10 次后
执行 WiFi 硬重置（`WiFi.disconnect(true)` → `WiFi.begin()`），解决 DHCP 或
关联状态异常：

```cpp
// comm_manager.cpp
void CommManager::reconnect() {
    unsigned long now = millis();
    if (now - _lastReconnect < _reconnectInterval) return;  // 退避限流
    _lastReconnect = now;
    _reconnectFailCount++;
    disconnect();  // 先断开旧连接，防止 socket 泄漏

    if (_reconnectFailCount >= 10) {
        WiFi.disconnect(true);   // 硬重置
        delay(200);
        WiFi.begin();
        _reconnectFailCount = 0;
        _reconnectInterval = RECONNECT_INTERVAL;
        return;
    }

    connect();
    _reconnectInterval = min(_reconnectInterval * 2, (unsigned long)60000);  // 指数退避上限 60s
}
```

### 2.4 TCP 帧协议状态机

通信层实现了双协议兼容的帧解析状态机，支持长度前缀帧协议（v2）和旧格式
`\n` 分隔的 JSON 行协议：

```cpp
// comm_manager.h
enum FrameState {
    FRAME_IDLE,         // 等待新帧（检测 'L' 或 '{' 开头）
    FRAME_READ_LEN,     // 读取长度前缀 "LEN:NNNN\n"
    FRAME_READ_BODY,    // 按长度读取 payload
    FRAME_LEGACY_LINE   // 兼容旧格式：\n 分隔
};
```

状态转换流程：

```
          ┌──────────────────────────────────────┐
          │           FRAME_IDLE                  │
          │  收到 'L' → FRAME_READ_LEN           │
          │  收到 '{' → FRAME_LEGACY_LINE         │
          └──────┬───────────────────┬────────────┘
                 │                   │
                 ▼                   ▼
    ┌────────────────────┐  ┌─────────────────────┐
    │  FRAME_READ_LEN    │  │  FRAME_LEGACY_LINE   │
    │  累积到 '\n'       │  │  累积到 '\n'         │
    │  解析 "LEN:NNNN"   │  │  整行即为 JSON       │
    └──────────┬─────────┘  └──────────┬───────────┘
               │                       │
               ▼                       ▼
    ┌────────────────────┐  processData()
    │  FRAME_READ_BODY   │
    │  按长度读取 payload │
    │  完成 → processData │
    └──────────┬─────────┘
               │
               ▼
           FRAME_IDLE
```

核心解析代码（含批量读取优化）：

```cpp
// comm_manager.cpp - update()
while (_client.connected() && _client.available()) {
    size_t bytesRead = _client.read((uint8_t*)_readBuf,
        min((int)CLIENT_READ_BUF_SIZE, _client.available()));
    for (size_t i = 0; i < bytesRead; i++) {
        char c = _readBuf[i];

        // FRAME_READ_BODY 批量写入优化：跳过逐字符追加
        if (_frameState == FRAME_READ_BODY && i < bytesRead) {
            int remaining = _expectedLen - (int)_frameBuffer.length();
            int available = (int)(bytesRead - i);
            int toCopy = (remaining < available) ? remaining : available;
            if (toCopy > 0) {
                _frameBuffer.concat(&_readBuf[i], toCopy);
                i += toCopy - 1;
                if ((int)_frameBuffer.length() >= _expectedLen) {
                    processData(_frameBuffer);
                    _frameBuffer = "";
                    _frameState = FRAME_IDLE;
                }
                continue;
            }
        }

        switch (_frameState) {
            case FRAME_IDLE:
                if (c == 'L') { _lenBuffer = "L"; _frameState = FRAME_READ_LEN; }
                else if (c == '{') { _frameBuffer = "{"; _frameState = FRAME_LEGACY_LINE; }
                break;
            case FRAME_READ_LEN:
                if (c == '\n') {
                    if (_lenBuffer.startsWith("LEN:")) {
                        _expectedLen = atoi(_lenBuffer.substring(4).c_str());
                        if (_expectedLen > 0 && _expectedLen <= 256 * 1024) {
                            _frameBuffer.reserve(_expectedLen);
                            _frameState = FRAME_READ_BODY;
                        }
                    }
                    _lenBuffer = "";
                } else {
                    _lenBuffer += c;
                    if (_lenBuffer.length() > 16) { _frameState = FRAME_IDLE; }  // 防溢出
                }
                break;
            // ... FRAME_READ_BODY / FRAME_LEGACY_LINE 略
        }
    }
}
```

发送方向统一使用长度前缀帧格式：

```cpp
void CommManager::sendFramed(const String& json) {
    char header[16];
    int len = snprintf(header, sizeof(header), "LEN:%d\n", (int)json.length());
    _client.write((const uint8_t*)header, len);
    _client.print(json);
}
```

### 2.5 JSON 解析

服务端下发的数据为 JSON 格式，使用 ArduinoJson 库解析。为避免运行时 `malloc`
导致堆碎片化，在 PSRAM 中预分配了 4KB 静态解析缓冲区：

```cpp
// main.cpp
__attribute__((section(".psram"))) static char g_jsonParseBuf[4096];
```

解析采用 **两阶段策略**：先用 64 字节的最小文档提取 `type` 字段，再按类型用
Filter 机制精确解析，减少内存占用：

```cpp
void parseServerData(String json) {
    // OOM 熔断：堆剩余不足 16KB 时跳过解析
    if (ESP.getFreeHeap() < 16384) return;

    // Phase 1: 快速提取 type 字段
    StaticJsonDocument<64> typeDoc;
    deserializeJson(typeDoc, json);
    String type = typeDoc["type"] | "unknown";

    // Phase 2: 按类型过滤解析（以 status 为例）
    if (type == "status") {
        StaticJsonDocument<256> filter;
        filter["data"]["status"] = true;
        filter["data"]["process"] = true;
        // ...
        StaticJsonDocument<256> doc;
        deserializeJson(doc, json, DeserializationOption::Filter(filter));
        // 写入双缓冲...
    }
}
```

支持的消息类型包括：`status`、`token`、`weather`、`pixel_data`、
`pixel_cmd`、`ping`、`thinking_status`。

### 2.6 心跳机制

每 10 秒向服务端发送一次心跳包，维持 TCP 连接活性：

```cpp
if (now - lastHeartbeat >= 10000) {
    lastHeartbeat = now;
    if (comm.isConnected()) {
        comm.sendHeartbeat();  // {"type":"heartbeat","ts":millis()}
    }
}
```

此外，TCP 层还启用了内核级 Keep-Alive，检测路由器 NAT 超时或服务端崩溃导致的
死连接：

```cpp
// comm_manager.cpp connect()
int fd = _client.fd();
int enable = 1;
setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &enable, sizeof(enable));
int idle = 60;     // 空闲 60 秒后开始探测
setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
int intvl = 10;    // 每 10 秒探测一次
setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
int cnt = 3;       // 连续 3 次无响应判定断开
setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof(cnt));
```

### 2.7 离线检测

45 秒未收到有效数据时，将设备状态切换为 OFFLINE：

```cpp
if (!isOffline && (now - g_lastDataReceived.load(std::memory_order_acquire)
                   > OFFLINE_TIMEOUT_MS)) {
    int front = g_frontIdx.load(std::memory_order_acquire);
    int backIdx = 1 - front;
    g_displayBuf[backIdx] = g_displayBuf[front];
    g_displayBuf[backIdx].connected = false;
    g_displayBuf[backIdx].agent.status = STATUS_OFFLINE;
    isOffline = true;
    g_frontIdx.store(backIdx, std::memory_order_release);
}
```

### 2.8 崩溃遥测

利用 ESP32-S3 的 RTC NOINIT 区域（重启不丢失的 SRAM）记录崩溃计数。该区域
在冷启动时内容随机，通过魔数 `0xDEADBEEF` 区分冷启动和异常重启：

```cpp
static constexpr uint32_t CRASH_MAGIC = 0xDEAD'BEEF;
RTC_NOINIT_ATTR uint32_t s_crashCount;   // 不能用 =0 初始化！
RTC_NOINIT_ATTR uint32_t s_crashMagic;

// setup() 中检测
if (s_crashMagic != CRASH_MAGIC) {
    s_crashCount = 0;           // 首次上电，初始化计数器
    s_crashMagic = CRASH_MAGIC;
}
esp_reset_reason_t resetReason = esp_reset_reason();
if (resetReason == ESP_RST_PANIC || resetReason == ESP_RST_TASK_WDT ||
    resetReason == ESP_RST_INT_WDT) {
    s_crashCount++;             // 异常重启，累加计数
}
```

首次建立 TCP 连接后，通信任务将崩溃信息上报服务端：

```cpp
if (!crashReported && s_crashCount > 0 && comm.isConnected()) {
    StaticJsonDocument<512> crashMsg;
    crashMsg["type"] = "crash_report";
    crashMsg["data"]["count"] = s_crashCount;
    crashMsg["data"]["reason"] = (int)esp_reset_reason();
    String crashJson;
    serializeJson(crashMsg, crashJson);
    comm.sendFramed(crashJson);
    crashReported = true;
}
```

### 2.9 BOOT 键处理

GPIO0（BOOT 按键）在通信任务中轮询检测，支持两种场景：

```cpp
if (digitalRead(0) == LOW) {
    delay(50);  // 消抖
    if (digitalRead(0) == LOW) {
        if (g_screenSleeping) {
            // 休眠状态下：唤醒屏幕显示 15 秒
            g_forceWake.store(true, std::memory_order_release);
        } else if (pixelPlayer.isLoaded()) {
            // 普通状态下：停止像素播放，切回普通模式
            pixelPlayer.stop();
            g_pendingNormalMode.store(true);
        }
        while (digitalRead(0) == LOW) vTaskDelay(pdMS_TO_TICKS(10));  // 等释放
    }
}
```

---

## 三、Core 1 渲染任务

### 3.1 任务配置

```cpp
// config.h
#define RENDER_TASK_CORE  1       // 绑定 Core 1
#define RENDER_TASK_STACK 16384   // 栈大小 16KB（含 sprite 操作）

// main.cpp setup()
xTaskCreatePinnedToCore(
    renderTask,
    "RenderTask",
    RENDER_TASK_STACK,   // 16384 字节
    NULL,
    1,                   // 优先级 1（低于通信任务）
    &g_renderTaskHandle,
    RENDER_TASK_CORE     // Core 1
);
```

渲染任务需要更大的栈空间（16KB），因为 LovyanGFX 的 sprite 操作涉及大量
像素缓冲区运算。

### 3.2 显示更新周期

基础显示更新间隔为 1 秒，动画更新间隔为 500ms：

```cpp
// config.h
#define UPDATE_INTERVAL     1000   // 显示刷新 1s
#define ANIMATION_INTERVAL  500    // 动画刷新 500ms
```

### 3.3 VRR 动态帧率

渲染任务采用 VRR（可变刷新率）策略，根据屏幕状态和 Agent 状态动态调整帧延迟：

```cpp
uint32_t frameDelay = 20;       // ACTIVE: 50fps（默认）
if (g_screenSleeping) {
    frameDelay = 500;            // SLEEP: 2fps
} else if (g_screenDimmed) {
    frameDelay = 1000;           // DIM: 1fps
} else if (millis() - g_lastDataReceived.load() > SCREEN_DIM_TIMEOUT / 2) {
    frameDelay = 200;            // IDLE: 5fps（数据静默 >15 秒）
} else {
    // OTLP 联动：根据 Agent 状态微调
    uint8_t agentStatus = g_displayBuf[backIdx].agent.status;
    if (agentStatus == STATUS_WORKING) {
        frameDelay = 16;         // Agent 工作中: 60fps（流畅思考动画）
    } else if (agentStatus == STATUS_AUTH) {
        frameDelay = 33;         // 认证/交互: 30fps
    }
}

vTaskDelay(pdMS_TO_TICKS(frameDelay));
```

帧率对照表：

| 状态 | frameDelay | 实际帧率 | 触发条件 |
|------|-----------|---------|---------|
| WORKING | 16ms | ~60fps | Agent 正在执行任务 |
| AUTH | 33ms | ~30fps | 需要用户授权 |
| ACTIVE | 20ms | ~50fps | 正常连接状态 |
| IDLE | 200ms | ~5fps | 15 秒无数据 |
| DIM | 1000ms | ~1fps | 30 秒无数据 |
| SLEEP | 500ms | ~2fps | 60 秒无数据 |

### 3.4 休眠状态机

屏幕休眠分为四个阶段，逐级降低功耗：

```
ACTIVE ──(30s)──▶ DIM ──(30s)──▶ SLEEP ──(5min)──▶ LIGHT_SLEEP
  240MHz           240MHz          80MHz              ESP32 硬件休眠
  WiFi active      WiFi active     WiFi sleep         Touch/WiFi 唤醒
  全亮              低亮度          关背光             关背光 + CPU 停止
```

状态转换代码：

```cpp
unsigned long timeSinceData = now - g_lastDataReceived.load();

if (needWake && (g_screenDimmed || g_screenSleeping)) {
    // 数据到达 → 唤醒
    setCpuFrequencyMhz(240);
    WiFi.setSleep(false);
    esp_wifi_set_ps(WIFI_PS_NONE);
    display.wakeup();
    g_screenDimmed = false;
    g_screenSleeping = false;

} else if (!g_screenSleeping && timeSinceData > SCREEN_SLEEP_TIMEOUT) {
    // 60 秒 → 休眠
    setCpuFrequencyMhz(80);
    WiFi.setSleep(true);
    esp_wifi_set_ps(WIFI_PS_MAX_MODEM);
    esp_wifi_set_listen_interval(3);  // 每 3 个 DTIM beacon 唤醒一次
    display.sleep();
    g_screenSleeping = true;

} else if (!g_screenDimmed && timeSinceData > SCREEN_DIM_TIMEOUT) {
    // 30 秒 → 变暗
    display.dim();
    g_screenDimmed = true;
}
```

Light Sleep 深度休眠（屏幕休眠 5 分钟后触发）：

```cpp
if (now - g_screenSleepStart >= LIGHT_SLEEP_TIMEOUT) {
    display.sleep();
    esp_sleep_enable_touchpad_wakeup();    // 触摸唤醒
    // RTC IO 状态保持：锁定关键引脚电平
    gpio_hold_en((gpio_num_t)LCD_BL);      // 背光保持低电平
    gpio_hold_en((gpio_num_t)BUZZER_PIN);  // 蜂鸣器保持低电平
    gpio_hold_en((gpio_num_t)LCD_CS);      // SPI 片选保持高电平
    esp_light_sleep_start();
    // === 唤醒 ===
    gpio_hold_dis((gpio_num_t)LCD_BL);
    gpio_hold_dis((gpio_num_t)BUZZER_PIN);
    gpio_hold_dis((gpio_num_t)LCD_CS);
    setCpuFrequencyMhz(240);
    WiFi.setSleep(false);
}
```

### 3.5 温控自适应

每 10 秒检测 CPU 温度，动态调整频率防止过热：

```cpp
float cpuTemp = temperatureRead();
if (cpuTemp > 65.0f) {
    setCpuFrequencyMhz(80);       // 严重过热：降频到 80MHz
} else if (cpuTemp > 55.0f) {
    setCpuFrequencyMhz(160);      // 温度过高：降频到 160MHz
} else if (cpuTemp < 50.0f && getCpuFrequencyMhz() < 240) {
    setCpuFrequencyMhz(240);      // 温度恢复：升频回 240MHz
}
```

| 温度阈值 | CPU 频率 | 动作 |
|---------|---------|------|
| < 50°C | 240MHz | 恢复全速 |
| > 55°C | 160MHz | 降频预警 |
| > 65°C | 80MHz | 紧急降频 + 降低亮度 |

### 3.6 触摸与接近感应

触摸和接近感应在渲染任务中更新，与显示循环同步：

```cpp
// 触摸检测
touch.update();

// 接近感应：自动唤醒屏幕
if (!g_screenSleeping) {
    touch.proximity.update();
}
if (touch.proximity.isNear() || touch.isProximityWakeActive()) {
    if (g_screenSleeping || g_screenDimmed) {
        g_forceWake = true;
        display.wakeup();
        g_screenSleeping = false;
        g_screenDimmed = false;
        g_screenSleepStart = 0;
    }
    g_lastDataReceived.store(now, std::memory_order_release);  // 重置休眠计时
}
```

### 3.7 光照自动背光

BH1750 光照传感器每 2 秒读取一次，根据环境光自动调节 LCD 背光亮度：

```cpp
static unsigned long lastLightRead = 0;
if (ambientLight.isAvailable() && !g_screenSleeping &&
    (now - lastLightRead >= BH1750_READ_INTERVAL)) {
    int16_t lux = ambientLight.readLux();
    uint8_t pwm = ambientLight.autoAdjustBacklight(lux);
    display.setBrightness(pwm);     // 一阶缓动，不会瞬间跳变
    lastLightRead = now;
}
```

背光采用一阶 EMA 缓动算法，每帧平滑过渡，消除亮度跳变闪烁：

```cpp
// display_manager.h
static constexpr float BRIGHTNESS_SMOOTHING = 0.15f;

void DisplayManager::applySmoothBacklight() {
    _currentBrightness += (_targetBrightness - _currentBrightness) * BRIGHTNESS_SMOOTHING;
    _lcd.setBrightness((uint8_t)_currentBrightness);
}
```

### 3.8 FPS 计数与堆栈监控

每秒输出实际渲染帧率，每 5 秒输出堆和栈水位：

```cpp
// FPS 计数器
static uint32_t fpsFrameCount = 0;
fpsFrameCount++;
if (now - lastFpsReport >= 1000) {
    float fps = fpsFrameCount * 1000.0f / (now - lastFpsReport);
    log_i("[FPS] %.1f fps", fps);
    fpsFrameCount = 0;
}

// 堆 + 栈监控
log_i("[Heap] Internal Free=%d B | PSRAM Free=%d B",
      ESP.getFreeHeap(), ESP.getFreePsram());
UBaseType_t renderStack = uxTaskGetStackHighWaterMark(NULL);
if (renderStack * sizeof(StackType_t) < 512) {
    LOG_E("WARNING: renderTask stack near overflow!");
}
```

---

## 四、双核共享数据

### 4.1 DisplayData 双缓冲

两个核心共享的核心数据结构是 `DisplayData`，包含 Agent 状态、Token 统计、
天气信息等显示所需的所有数据：

```cpp
// types.h
struct DisplayData {
    AgentState agent;          // Agent 状态（status, cpu, memory, processName）
    TokenStats tokens;         // Token 统计（input, output, requests, cost）
    WeatherInfo weather;       // 天气信息（city, temp, humidity, wind）
    uint32_t lastUpdate;       // 最后更新时间戳
    bool connected;            // 连接状态
    ThinkingStepCache* thinkingHistory;  // 思考链历史（PSRAM 环形缓冲）
    float scrollOffset;        // 滚动偏移
    bool needsScroll;          // 是否需要滚动动画
    unsigned long scrollStartTime;
};
```

双缓冲实例和原子索引：

```cpp
DisplayData g_displayBuf[2];           // 双缓冲：front=read, back=write
std::atomic<int> g_frontIdx{0};        // 原子索引：0 或 1
std::atomic<bool> g_forceWake{false};  // 原子标志：强制唤醒屏幕
```

### 4.2 原子索引交换机制

Core 0 写入 back buffer 后，通过原子 store 切换 `g_frontIdx`，Core 1 通过
原子 load 读取当前 front buffer。整个过程无需 Mutex：

```
Core 0 (写端):                          Core 1 (读端):
┌─────────────────────────┐             ┌─────────────────────────┐
│ 1. front = load(g_frontIdx)           │ 1. frontIdx = load(g_frontIdx)
│ 2. backIdx = 1 - front                │ 2. localData = g_displayBuf[frontIdx]
│ 3. g_displayBuf[backIdx] = ...        │ 3. (localData 是栈上副本)
│ 4. store(backIdx → g_frontIdx)        │    无需持锁，安全读取
└─────────────────────────┘             └─────────────────────────┘
```

### 4.3 待处理标志（Pending Flags）

Core 0 不能直接调用 Core 1 上的 LCD/SPI 驱动（SPI 总线非线程安全），因此通过
原子标志通知 Core 1 执行显示操作：

```cpp
std::atomic<bool> g_pendingNormalMode{false};        // 切回普通模式
std::atomic<bool> g_pendingPixelPlay{false};          // 播放像素动画
std::atomic<bool> g_pendingPixelStop{false};          // 停止像素动画
std::atomic<bool> g_pendingPixelBufferLoad{false};    // 加载像素缓冲区
std::atomic<uint8_t*> g_pendingPixelBufferPtr{nullptr};  // 像素数据指针
std::atomic<PixelPlayer*> g_pendingPixelPtr{nullptr};    // 播放器指针
std::atomic<size_t> g_pendingPixelSize{0};               // 像素数据大小
```

Core 1 在每帧循环开头检查并执行这些待处理操作：

```cpp
// 执行顺序：先停 → 再切模式 → 再播新像素（避免状态冲突）
if (g_pendingPixelStop) {
    pixelPlayer.stop();
    g_pendingPixelStop = false;
}
if (g_pendingNormalMode) {
    display.setNormalMode();
    g_pendingNormalMode = false;
}
if (g_pendingPixelPlay && g_pendingPixelPtr) {
    display.setPixelMode(g_pendingPixelPtr.load());
    g_pendingPixelPtr.load()->play();
    g_pendingPixelPlay = false;
    g_pendingPixelPtr = nullptr;
}
if (g_pendingPixelBufferLoad && g_pendingPixelBufferPtr) {
    uint8_t* buf = g_pendingPixelBufferPtr;
    size_t sz = g_pendingPixelSize;
    if (pixelPlayer.loadFromBuffer(buf, sz)) {
        g_pendingPixelPlay = true;
        g_pendingPixelPtr = &pixelPlayer;
    }
    g_pendingPixelBufferLoad = false;
}
```

### 4.4 为什么不需要 Mutex

传统双线程共享数据需要 Mutex 保护，但本项目通过架构设计完全避免了锁：

| 方面 | Mutex 方案 | 本项目方案 |
|------|-----------|-----------|
| 同步机制 | `xSemaphoreTake/Give` | `std::atomic` load/store |
| 写操作阻塞 | 可能阻塞等待锁 | 永不阻塞 |
| 优先级反转 | 高优先级任务可能被低优先级持锁阻塞 | 不存在 |
| 最坏延迟 | 取决于临界区长度 | 仅一次原子指令（~10ns） |
| 代码复杂度 | 需要管理锁的生命周期 | 仅需 `memory_order` 标注 |
| 死锁风险 | 多锁场景下存在 | 不存在 |

关键设计原则：**单写者 + 单读者 + 双缓冲**。Core 0 只写 back buffer，
Core 1 只读 front buffer，通过原子索引交换角色，物理上不存在同时读写同一
buffer 的情况。

---

## 五、跨核通信模式

### 5.1 双缓冲数据流

```
Core 0 (通信)                           Core 1 (渲染)
    │                                       │
    │  解析 JSON → 写入 back buffer         │
    │                                       │
    ├── front = load(g_frontIdx)            │
    ├── backIdx = 1 - front                 │
    ├── g_displayBuf[backIdx] = 更新数据     │
    ├── store(backIdx → g_frontIdx) ────────┤── frontIdx = load(g_frontIdx)
    │                                       ├── localData = g_displayBuf[frontIdx]
    │                                       │   （栈上副本，安全使用）
    │                                       │
    │                                       ├── 渲染 localData 到屏幕
    │                                       ├── 检查 pending flags
    │                                       └── vTaskDelay(frameDelay)
```

### 5.2 原子标志通信

跨核通信使用 `std::atomic` 变量，无需锁即可实现信号通知：

| 标志 | 写入方 | 读取方 | 用途 |
|------|--------|--------|------|
| `g_frontIdx` | Core 0 (store) | Core 1 (load) | 双缓冲索引交换 |
| `g_forceWake` | Core 0 (store true) | Core 1 (exchange false) | 强制唤醒屏幕 |
| `g_lastDataReceived` | Core 0 (store) | Core 1 (load) | 休眠计时基准 |
| `g_pendingNormalMode` | Core 0 (store true) | Core 1 (read + clear) | 切回普通模式 |
| `g_pendingPixelPlay` | Core 0 (store true) | Core 1 (read + clear) | 播放像素动画 |
| `g_pendingPixelStop` | Core 0 (store true) | Core 1 (read + clear) | 停止像素动画 |
| `g_pendingPixelBufferLoad` | Core 0 (store true) | Core 1 (read + clear) | 加载像素数据 |

### 5.3 vTaskDelay 让出 CPU

两个任务都在主循环末尾调用 `vTaskDelay()`，主动让出 CPU 时间片：

- Core 0: `vTaskDelay(pdMS_TO_TICKS(10))` — 10ms 周期
- Core 1: `vTaskDelay(pdMS_TO_TICKS(frameDelay))` — 16ms~1000ms 动态周期

这不仅避免了看门狗超时（WDT），还让 FreeRTOS 调度器有机会执行低优先级的
系统任务（如 WiFi 协议栈、lwIP TCP 处理等）。

---

## 六、任务间同步

### 6.1 内存序语义

所有原子操作都标注了明确的内存序（memory order），确保 SMP 架构下的数据
可见性：

```cpp
// Core 0 写入（release 语义：之前的写操作对后续 load 可见）
g_lastDataReceived.store(now, std::memory_order_release);
g_forceWake.store(true, std::memory_order_release);
g_frontIdx.store(backIdx, std::memory_order_release);

// Core 1 读取（acquire 语义：确保读到 release 之前的所有写入）
int frontIdx = g_frontIdx.load(std::memory_order_acquire);
unsigned long timeSinceData = now - g_lastDataReceived.load(std::memory_order_acquire);

// exchange（acquire+release：同时保证读和写的顺序）
needWake = g_forceWake.exchange(false, std::memory_order_acq_rel);
```

`memory_order_release` / `memory_order_acquire` 配对使用，形成
**happens-before** 关系：

```
Core 0:                          Core 1:
  写入 back buffer 数据            (不可能看到不完整的写入)
  store(g_frontIdx, release)  →   load(g_frontIdx, acquire)
                                   读取 front buffer 数据
                                   (保证看到 Core 0 写入的全部数据)
```

### 6.2 OTA 任务挂起/恢复

OTA 升级时需要独占 SPI 总线，通过 FreeRTOS 任务通知挂起渲染任务：

```cpp
// 渲染任务启动时保存句柄
g_renderTaskHandle = xTaskGetCurrentTaskHandle();

// OTA 升级时挂起渲染任务（释放 Core 1 的 SPI 总线 + CPU）
vTaskSuspend(g_renderTaskHandle);

// OTA 完成后恢复
vTaskResume(g_renderTaskHandle);
```

### 6.3 FIX-N1 防竞态技巧

代码中多处出现 `FIX-N1` 注释，修复了一个关键竞态：如果 Core 0 在两次
`g_frontIdx.load()` 之间被 Core 1 抢占并执行了 swap，会导致读到错误的
buffer 索引。修复方法是只 load 一次并缓存到局部变量：

```cpp
// 错误写法（两次 load 可能不一致）：
g_displayBuf[1 - g_frontIdx.load()] = g_displayBuf[g_frontIdx.load()];
//                                              ^^^^^^^^^^^^^^^^^^^^
//                                              可能已被 Core 1 swap！

// 正确写法（只 load 一次）：
int front = g_frontIdx.load(std::memory_order_acquire);
int backIdx = 1 - front;
g_displayBuf[backIdx] = g_displayBuf[front];
// ... 写入 backIdx ...
g_frontIdx.store(backIdx, std::memory_order_release);
```

---

## 附录：关键常量速查

| 常量 | 值 | 定义位置 | 说明 |
|------|-----|---------|------|
| `COMM_TASK_CORE` | 0 | config.h | 通信任务核心 |
| `RENDER_TASK_CORE` | 1 | config.h | 渲染任务核心 |
| `COMM_TASK_STACK` | 8192 | config.h | 通信任务栈 8KB |
| `RENDER_TASK_STACK` | 16384 | config.h | 渲染任务栈 16KB |
| `UPDATE_INTERVAL` | 1000ms | config.h | 显示刷新间隔 |
| `ANIMATION_INTERVAL` | 500ms | config.h | 动画刷新间隔 |
| `SCREEN_DIM_TIMEOUT` | 30000ms | config.h | 变暗超时 |
| `SCREEN_SLEEP_TIMEOUT` | 60000ms | config.h | 休眠超时 |
| `OFFLINE_TIMEOUT_MS` | 45000ms | config.h | 离线判定超时 |
| `LIGHT_SLEEP_TIMEOUT` | 300000ms | main.cpp | Light Sleep 超时 5min |
| `CLIENT_READ_BUF_SIZE` | 512 | config.h | TCP 读取缓冲区 |
| `JSON_PARSE_BUF_SIZE` | 4096 | main.cpp | JSON 解析缓冲区 |
| `PXL_POOL_SIZE` | 128KB | main.cpp | 像素数据 PSRAM 池 |
