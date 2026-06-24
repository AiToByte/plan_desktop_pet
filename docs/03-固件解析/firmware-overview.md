# 固件工程总览

> 本文档基于 `esp32_firmware/` 源码，面向开发者梳理固件工程的完整结构、配置细节、内存布局与构建流程。
> 目标硬件: **微雪 ESP32-S3 1.54inch LCD** (ESP32-S3FN8, 2MB OPI PSRAM, 8MB Flash)

---

## 一、PlatformIO 工程结构

```
esp32_firmware/
├── platformio.ini              # PlatformIO 构建配置 (平台/板卡/库/标志)
├── sdkconfig.defaults          # ESP-IDF SDK 覆盖配置 (WDT/panic)
├── build.log                   # 构建日志 (可忽略)
│
├── include/                    # 全局头文件 (项目级)
│   ├── config.h                #   所有硬件引脚、超时、协议常量
│   ├── log.h                   #   统一日志分级宏 (LOG_E/W/I/D)
│   └── types.h                 #   共享数据结构 (AgentState, TokenStats 等)
│
├── src/                        # 源文件 (模块化, 每模块 .h + .cpp)
│   ├── main.cpp                #   入口: FreeRTOS 双核任务创建与调度
│   ├── display_manager.cpp/.h  #   屏幕渲染引擎 (LovyanGFX sprite)
│   ├── comm_manager.cpp/.h     #   TCP 通信与 JSON 协议解析
│   ├── wifi_manager.cpp/.h     #   WiFi 连接管理与重连
│   ├── web_config.cpp/.h       #   Web 配网 (AP 模式 + HTTP 表单)
│   ├── ble_config.cpp/.h       #   BLE 配网 (NimBLE)
│   ├── ble_provisioner.cpp/.h  #   BLE Provisioning 协议
│   ├── pixel_player.cpp/.h     #   .pxl 像素动画解码与播放
│   ├── sound_manager.cpp/.h    #   蜂鸣器音效管理
│   ├── touch_handler.cpp/.h    #   电容触摸与接近感应
│   ├── ambient_light.cpp/.h    #   BH1750 光照传感器驱动
│   ├── haptic_driver.cpp/.h    #   DRV2605L 触觉反馈驱动
│   ├── spring_animation.cpp/.h #   弹簧物理动画
│   └── sin_lut.h               #   正弦查找表 (动画优化)
│
├── data/                       # LittleFS 文件系统镜像
│   └── images/                 #   预置图片资源 (.pxl 等)
│       └── .gitkeep
│
├── lib/                        # 本地库 (当前为空, 依赖均通过 platformio.ini 拉取)
└── .pio/                       # PlatformIO 构建产物 (自动生成)
    └── build/esp32s3/          #   编译输出: firmware.bin, firmware.elf 等
```

**设计原则:**
- 每个外设/功能模块独立为 `.h + .cpp` 对, 避免单文件过大
- `include/` 存放跨模块共享的配置与类型定义
- `src/` 内模块通过头文件相互引用, `main.cpp` 负责组装与调度

---

## 二、platformio.ini 配置详解

完整配置文件内容:

```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino

lib_deps =
    lovyan03/LovyanGFX@^1.1.8
    bblanchon/ArduinoJson@^6.21.0
    ESPmDNS
    h2zero/NimBLE-Arduino@^1.4.0

monitor_speed = 115200
upload_speed = 921600
board_build.partitions = huge_app.csv
board_build.filesystem = littlefs
board_build.arduino.memory_type = qio_opi

build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -std=c++17
```

### 逐项解析

| 配置项 | 值 | 说明 |
|--------|------|------|
| `platform` | `espressif32` | Espressif 官方 PlatformIO 平台包, 包含 ESP-IDF 工具链 |
| `board` | `esp32-s3-devkitc-1` | 乐鑫 S3 开发板预设 (Flash/PSRAM/引脚映射) |
| `framework` | `arduino` | Arduino 框架封装, 提供 `setup()`/`loop()` 入口 |
| `monitor_speed` | `115200` | 串口监视器波特率 (bps) |
| `upload_speed` | `921600` | 烧录上传波特率, 约 900kbps |
| `board_build.partitions` | `huge_app.csv` | 分区表: 3MB app + 1.5MB LittleFS + 其余保留 |
| `board_build.filesystem` | `littlefs` | 文件系统类型, 用于 `data/` 目录烧录 |
| `board_build.arduino.memory_type` | `qio_opi` | PSRAM 模式: Quad I/O + Octal PSRAM (2MB) |

### 库依赖说明

| 库 | 版本 | 用途 |
|----|------|------|
| **LovyanGFX** | `^1.1.8` | 高性能 TFT 驱动, 支持 sprite 双缓冲, 硬件 SPI 加速 |
| **ArduinoJson** | `^6.21.0` | JSON 解析/生成, 用于 PC 通信协议 |
| **ESPmDNS** | (内置) | mDNS 局域网服务发现, 配网后自动广播设备地址 |
| **NimBLE-Arduino** | `^1.4.0` | 低功耗蓝牙栈, 替代原生 BLE 库, 节省约 100KB Flash |

### 构建标志 (build_flags) 解析

| 标志 | 作用 |
|------|------|
| `-DBOARD_HAS_PSRAM` | 启用 PSRAM 支持, 允许 `ps_malloc()` 分配大缓冲区 |
| `-DARDUINO_USB_MODE=1` | 使用 USB-OTG 模式 (S3 内置 USB 外设) |
| `-DARDUINO_USB_CDC_ON_BOOT=1` | 启动时启用 USB CDC 串口, 用于日志输出与调试 |
| `-std=c++17` | 启用 C++17 特性: `std::atomic`, 结构化绑定, `constexpr if` 等 |

### sdkconfig.defaults 覆盖

```ini
# Task WDT: 30秒超时 (vs ESP-IDF 默认5秒), 允许 WiFi/BLE 长任务
CONFIG_ESP_TASK_WDT_TIMEOUT_S=30
CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0=y
CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU1=y
CONFIG_ESP_TASK_WDT_PANIC=y

# panic handler 打印 reset reason
CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT=y

# RTC 硬件 WDT (软件 WDT 失败时的最终防线)
CONFIG_ESP_INT_WDT_TIMEOUT_MS=300
```

---

## 三、头文件说明

### 3.1 config.h -- 全局配置常量

所有硬件引脚、超时阈值、协议参数集中定义, 按功能分组:

**WiFi 与配网:**
```cpp
#define WIFI_TIMEOUT          10000     // WiFi连接超时 10秒
#define AP_SSID               "Pet-Setup"   // 配网AP名称
#define AP_PASSWORD           "pet"         // 默认密码(启动时根据MAC生成唯一密码)
#define CONFIG_PORT           80            // Web配网HTTP端口
#define CONFIG_TIMEOUT        120000        // 配网超时 2分钟
```

**TCP 通信:**
```cpp
#define SERVER_PORT           19876         // PC端服务器端口
#define RECONNECT_INTERVAL    5000          // 断线重连间隔 5秒
#define CLIENT_TCP_TIMEOUT    10            // WiFiClient::setTimeout 10秒
#define CLIENT_TCP_KEEPIDLE   5             // 空闲后发第一个keepalive探测
#define CLIENT_TCP_KEEPINTVL  5             // 探测间隔
#define CLIENT_TCP_KEEPCNT    3             // 探测失败次数后断开
#define CLIENT_READ_BUF_SIZE  512           // TCP批量读取缓冲区
```

**屏幕引脚 (ST7789V SPI):**
```cpp
#define LCD_CS    5       // 片选
#define LCD_RST   4       // 复位
#define LCD_DC    2       // 数据/命令
#define LCD_MOSI  11      // SPI数据出
#define LCD_SCLK  12      // SPI时钟
#define LCD_BL    48      // 背光PWM
#define LCD_MISO  13      // SPI数据入 (触摸读回)
#define LCD_TE_PIN     -1 // V-Sync TE引脚 (当前禁用, 软件帧率控制)
#define TE_ACTIVE_HIGH true
#define VSYNC_TIMEOUT_MS  20
```

**屏幕参数:**
```cpp
#define SCREEN_WIDTH  240
#define SCREEN_HEIGHT 240
#define SCREEN_ROTATION 0
#define LCD_BRIGHTNESS  200       // 背光亮度 0-255
#define UPDATE_INTERVAL 1000      // 显示更新 1秒
#define ANIMATION_INTERVAL 500    // 动画帧间隔 500ms
```

**FreeRTOS 双核:**
```cpp
#define COMM_TASK_CORE    0       // 通信任务 → Core 0
#define RENDER_TASK_CORE  1       // 渲染任务 → Core 1
#define COMM_TASK_STACK   8192    // 通信栈 8KB
#define RENDER_TASK_STACK 16384   // 渲染栈 16KB (含sprite操作)
```

**电源管理:**
```cpp
#define SCREEN_DIM_TIMEOUT   30000   // 30秒无数据 → 变暗
#define SCREEN_SLEEP_TIMEOUT 60000   // 60秒无数据 → 休眠(关背光)
#define OFFLINE_TIMEOUT_MS   45000   // 45秒无数据 → OFFLINE状态
```

**外设引脚:**
```cpp
#define BUZZER_PIN        18    // GPIO18 无源蜂鸣器
#define TOUCH_PIN         1     // GPIO1 电容触摸 (Touch1)
#define TOUCH_THRESHOLD   40    // 触摸阈值 (需校准)
#define TOUCH_LONG_PRESS_MS 1000  // 长按 1秒

// BH1750 光照传感器 (I2C)
#define BH1750_SDA_PIN       41
#define BH1750_SCL_PIN       42
#define BH1750_READ_INTERVAL 2000   // 2秒读取一次

// DRV2605L 触觉反馈 (与BH1750共享I2C总线)
#define HAPTIC_SDA_PIN       41
#define HAPTIC_SCL_PIN       42
```

**接近感应 (电容微量差分):**
```cpp
#define PROX_EMA_FAST_ALPHA    0.3f   // 快速EMA系数
#define PROX_EMA_SLOW_ALPHA    0.05f  // 慢速EMA系数 (基线跟踪)
#define PROX_RISING_THRESHOLD  8      // 上升差分阈值
#define PROX_FALLING_THRESHOLD 4      // 下降差分阈值
#define PROX_COOLDOWN_MS       2000   // 防抖冷却 2秒
#define PROX_WAKE_DURATION_MS  15000  // 接近唤醒亮屏 15秒
```

**WiFi 省电:**
```cpp
#define IDLE_POWER_MODE        2      // 空闲时进入 LIGHT_SLEEP
#define DTIM_ACTIVE            1      // 活跃态 DTIM 间隔
#define DTIM_IDLE              10     // 空闲态 DTIM 间隔
#define IDLE_TIMEOUT_MS        30000  // 30秒无活动 → 省电
#define WAKE_CHECK_INTERVAL_MS 500    // 唤醒检查间隔 500ms
#define BSS_MAX_IDLE_SEC       300    // BSS最大空闲 5分钟
```

### 3.2 types.h -- 数据结构定义

```cpp
// 思考链状态枚举 (OTLP可视化)
enum ThinkingState : uint8_t {
    THINK_IDLE = 0,       // 空闲
    THINK_THINKING,       // 思考中
    THINK_TOOL_CALL,      // 工具调用
    THINK_RESPONDING,     // 响应中
    THINK_ERROR,          // 错误
    THINK_DONE            // 完成
};

// Agent状态
struct AgentState {
    uint8_t status;                    // STATUS_IDLE/WORKING/AUTH/OFFLINE
    ThinkingState thinkingState;
    String processName;                // 当前进程名
    float cpuPercent;                  // CPU 使用率
    float memoryMB;                    // 内存占用 (MB)
    uint32_t uptimeSeconds;            // 运行时长
};

// Token 统计
struct TokenStats {
    uint32_t inputTokens;              // 输入 token 数
    uint32_t outputTokens;             // 输出 token 数
    uint32_t totalRequests;            // 总请求数
    uint32_t hourTokens;               // 小时 token 数
    float costUSD;                     // 累计费用 (美元)
};

// 天气信息
struct WeatherInfo {
    String city;
    float temperature;                 // 当前温度
    float feelsLike;                   // 体感温度
    uint8_t humidity;                  // 湿度 %
    String description;                // 天气描述
    String iconCode;                   // 图标代码
    float windSpeed;                   // 风速
};

// 显示数据 (双缓冲核心结构)
struct DisplayData {
    AgentState agent;
    TokenStats tokens;
    WeatherInfo weather;
    uint32_t lastUpdate;               // 最后更新时间戳
    bool connected;                    // TCP 连接状态

    // 思考链历史 (PSRAM 环形缓冲)
    ThinkingStepCache* thinkingHistory; // setup() 中分配到 PSRAM
    float scrollOffset;                // 滚动偏移 0.0~1.0
    bool needsScroll;                  // 是否需要滚动动画
    unsigned long scrollStartTime;     // 动画开始时间
};
```

### 3.3 log.h -- 日志分级宏

```cpp
// 日志级别: 0=ERROR, 1=WARN, 2=INFO(默认), 3=DEBUG
#define LOG_E(fmt, ...) do { if (LOG_LEVEL >= 0) Serial.printf("[E][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_W(fmt, ...) do { if (LOG_LEVEL >= 1) Serial.printf("[W][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_I(fmt, ...) do { if (LOG_LEVEL >= 2) Serial.printf("[I][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_D(fmt, ...) do { if (LOG_LEVEL >= 3) Serial.printf("[D][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
```

---

## 四、源文件组织

| 文件 | 行数 | 职责 | 关键依赖 |
|------|------|------|----------|
| `main.cpp` | 926 | 入口: 双核任务创建、数据调度、OTA、崩溃恢复 | 所有模块 |
| `display_manager.cpp` | 1370 | 屏幕渲染引擎: sprite 绘制、动画、休眠管理 | LovyanGFX |
| `web_config.cpp` | 638 | Web 配网: AP 模式、HTTP 表单、WiFi 凭据存储 | WiFi, WebServer |
| `pixel_player.cpp` | 372 | .pxl 像素动画解码、差分帧、RLE 解压、播放控制 | - |
| `sound_manager.cpp` | 373 | 蜂鸣器 PWM 音效: 频率/占空比/包络控制 | ESP32 LEDC |
| `comm_manager.cpp` | 293 | TCP 客户端: 连接/重连/心跳/JSON 接收 | WiFiClient |
| `haptic_driver.cpp` | 289 | DRV2605L 触觉反馈: 振动效果库驱动 | Wire (I2C) |
| `ble_provisioner.cpp` | 241 | BLE Provisioning 协议实现 | NimBLE |
| `wifi_manager.cpp` | 221 | WiFi STA 连接、重连策略、状态机 | WiFi |
| `ble_config.cpp` | 209 | BLE 配网服务: GATT 特征值、数据接收 | NimBLE |
| `ambient_light.cpp` | 149 | BH1750 光照传感器: I2C 读取、亮度映射 | Wire (I2C) |
| `touch_handler.cpp` | 156 | 电容触摸: 短按/长按/接近感应 EMA 算法 | ESP32 Touch |
| `spring_animation.cpp` | 40 | 弹簧物理动画: 阻尼振荡计算 | - |

**头文件 (include/):**

| 文件 | 行数 | 职责 |
|------|------|------|
| `config.h` | 123 | 全局配置常量 (引脚/超时/协议/省电) |
| `types.h` | 61 | 共享数据结构定义 |
| `log.h` | 25 | 日志分级宏 |

**总计: 5486 行** (src + include)

---

## 五、编译与烧录

### 基本命令

```bash
# 编译 (仅构建, 不烧录)
pio run

# 编译并烧录
pio run -t upload

# 打开串口监视器
pio device monitor

# 清理构建产物
pio run -t clean

# 烧录 LittleFS 文件系统 (data/ 目录)
pio run -t uploadfs
```

### 构建模式切换

**Debug 模式 (默认):**
```ini
; platformio.ini 中默认配置, 日志级别 INFO
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -std=c++17
```

**Release 模式 (减少日志):**
```ini
; 追加 -DLOG_LEVEL=0 仅输出 ERROR
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -std=c++17
    -DLOG_LEVEL=0
```

**Verbose 调试模式:**
```ini
; 追加 -DLOG_LEVEL=3 输出 DEBUG 级别
build_flags = ...
    -DLOG_LEVEL=3
```

### 烧录流程

1. USB 连接 ESP32-S3 开发板
2. 确认设备出现在设备管理器 (USB CDC)
3. `pio run -t upload` 自动检测端口并烧录
4. `pio run -t uploadfs` 烧录 LittleFS 文件系统
5. `pio device monitor` 查看启动日志

---

## 六、内存布局

ESP32-S3 内存分为以下区域:

### 内部 SRAM

| 区域 | 大小 | 用途 | 访问方式 |
|------|------|------|----------|
| **IRAM** | 32 KB | 中断处理函数、时间关键代码 | `IRAM_ATTR` 属性标记 |
| **DRAM** | 512 KB | 全局变量、栈、堆 | 默认 C/C++ 变量 |
| **RTC FAST** | 8 KB | RTC 快速内存 (Deep Sleep 保持) | `RTC_DATA_ATTR` |
| **RTC SLOW** | 8 KB | RTC 慢速内存 (冷启动保持) | `RTC_NOINIT_ATTR` |

### 外部 PSRAM

| 参数 | 值 |
|------|------|
| 容量 | **2 MB** |
| 模式 | **OPI (Octal PSRAM Interface)** |
| 频率 | 80 MHz |
| 用途 | 大缓冲区、sprite 帧缓冲、JSON 解析 |

**PSRAM 静态分配 (main.cpp):**
```cpp
// 像素缓冲池: 32x32x2x64 = 128KB, 避免运行时 malloc 碎片化
__attribute__((section(".psram"))) static uint8_t g_pxlPool[32 * 32 * 2 * 64];

// JSON 解析缓冲区: 4KB, 覆盖所有 JSON 消息
__attribute__((section(".psram"))) static char g_jsonParseBuf[4096];
```

### Flash 分区表 (huge_app.csv)

| 分区名 | 偏移 | 大小 | 用途 |
|--------|------|------|------|
| `nvs` | 0x9000 | 20 KB | NVS 键值存储 (WiFi 凭据等) |
| `otadata` | 0xE000 | 8 KB | OTA 双分区切换标记 |
| `app0` | 0x10000 | 3 MB | 主固件 (当前运行) |
| `app1` | 0x310000 | 3 MB | OTA 备份固件 |
| `spiffs` | 0x610000 | ~1.5 MB | LittleFS 文件系统 |

### RTC NOINIT 内存 (冷启动保持)

```cpp
// 崩溃计数: 使用 RTC_NOINIT_ATTR 确保重启不丢失
// 注意: 不能用 =0 初始化, 否则编译器将其放入 .rtc.data 段 (每次冷启动清零)
static constexpr uint32_t CRASH_MAGIC = 0xDEAD'BEEF;
RTC_NOINIT_ATTR uint32_t s_crashCount;
RTC_NOINIT_ATTR uint32_t s_crashMagic;
```

冷启动时通过 `CRASH_MAGIC` 标记判断是否为有效数据, 避免首次上电读到随机值。

### 双缓冲架构

```
Core 0 (通信)          Core 1 (渲染)
    │                      │
    │   g_displayBuf[0]    │
    ├──────────────────────►│  (atomic 指针交换, 无 mutex)
    │   g_displayBuf[1]    │
    ├──────────────────────►│
    │                      │
    │   g_frontIdx (atomic)│  0 或 1, 标识当前 front buffer
    └──────────────────────┘
```

---

## 七、日志系统

### 级别控制

| 级别 | 值 | 宏 | 输出格式 | 编译条件 |
|------|------|------|----------|----------|
| ERROR | 0 | `LOG_E()` | `[E][函数名] 消息` | 始终编译 |
| WARN | 1 | `LOG_W()` | `[W][函数名] 消息` | `LOG_LEVEL >= 1` |
| INFO | 2 | `LOG_I()` | `[I][函数名] 消息` | `LOG_LEVEL >= 2` (默认) |
| DEBUG | 3 | `LOG_D()` | `[D][函数名] 消息` | `LOG_LEVEL >= 3` |

### 编译期 vs 运行期

- **编译期控制:** 通过 `build_flags = -DLOG_LEVEL=N` 在编译时决定日志级别, 低于阈值的日志语句不会生成代码, 零运行时开销
- **默认级别:** 未定义 `LOG_LEVEL` 时默认为 `2` (INFO)
- **Release 优化:** 设置 `-DLOG_LEVEL=0` 可完全移除 WARN/INFO/DEBUG 日志, 减小固件体积

### 输出示例

```
[I][setup] Booting Desktop Pet v2 (FreeRTOS dual-core)
[I][commTask] Started on Core 0
[I][renderTask] Started on Core 1
[W][parseServerData] Unknown command: foo
[E][connectWiFi] Connection timeout after 10000ms
[D][commTask] Heartbeat sent, uptime=1234s
```

### 使用规范

```cpp
#include "log.h"

void setup() {
    LOG_I("Booting Desktop Pet v2 (FreeRTOS dual-core)");
    if (!display.begin()) {
        LOG_E("Failed to init display");
        return;
    }
    LOG_D("Display initialized: %dx%d", SCREEN_WIDTH, SCREEN_HEIGHT);
}
```

**注意事项:**
- `LOG_D()` 仅在开发调试时启用, Release 构建必须设 `LOG_LEVEL < 3`
- 格式化字符串使用 `printf` 语法 (`%s`, `%d`, `%f` 等)
- `__func__` 自动插入调用函数名, 无需手动填写
- 日志输出到 `Serial` (USB CDC), 波特率由 `monitor_speed = 115200` 决定

---

## 附录: 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 双核分工 | Core 0=通信, Core 1=渲染 | 避免 SPI 与 WiFi 争抢 CPU |
| 双缓冲+atomic | 无 mutex 指针交换 | 消除跨核阻塞, 保证帧率稳定 |
| PSRAM 静态池 | `__attribute__((section(".psram")))` | 避免运行时 malloc 碎片化 |
| NimBLE | 替代原生 ESP32 BLE | 节省约 100KB Flash |
| RTC NOINIT | 崩溃计数冷启动保持 | 实现自动恢复与无限重启保护 |
| Web 配网 | AP 模式 + HTTP 表单 | 用户友好, 无需硬编码 WiFi 凭据 |
| LIGHT_SLEEP | 空闲 30 秒后自动进入 | 降低功耗, DTIM 10 间隔保持连接 |
