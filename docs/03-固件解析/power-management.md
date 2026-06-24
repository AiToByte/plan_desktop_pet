# 电源与功耗管理

本文档描述桌面电子宠物 ESP32-S3 固件的电源管理策略，涵盖功耗状态机、CPU 动态调频、WiFi 省电、背光缓动及 Light Sleep 深度休眠。

---

## 一、功耗状态机

系统定义了四个功耗状态，根据"最后一次收到有效数据"的时间戳自动流转：

```
                        收到数据/触摸/接近感应
                    ┌──────────────────────────────────┐
                    │                                  ▼
              ┌─────────┐   30s无数据   ┌─────────┐   30s无数据   ┌─────────┐   5min无数据   ┌─────────────┐
              │  ACTIVE  │─────────────▶│   DIM    │─────────────▶│  SLEEP   │──────────────▶│ LIGHT_SLEEP │
              │ 全速运行  │              │ 屏幕变暗  │              │ 背光关闭  │              │  芯片休眠    │
              └─────────┘              └─────────┘              └─────────┘              └─────────────┘
                 240MHz                  240MHz                   80MHz                    80MHz
              WiFi活跃/全亮           WiFi活跃/30%亮度         WiFi省电/背光灭           WiFi休眠/触摸唤醒
```

**状态定义与切换条件** (`esp32_firmware/include/config.h`):

| 状态 | 进入条件 | CPU 频率 | WiFi 模式 | LCD 背光 |
|------|---------|---------|----------|---------|
| ACTIVE | 收到数据 / 触摸 / 接近感应 | 240 MHz | `WIFI_PS_NONE` (活跃) | 100% (`LCD_BRIGHTNESS=200`) |
| DIM | 30 秒无数据 (`SCREEN_DIM_TIMEOUT`) | 240 MHz | 活跃 | 30% (目标亮度 60) |
| SLEEP | 60 秒无数据 (`SCREEN_SLEEP_TIMEOUT`) | 80 MHz | `WIFI_PS_MAX_MODEM` (省电) | 0% (背光关闭) |
| LIGHT_SLEEP | 进入 SLEEP 后 5 分钟无数据 | 芯片休眠 | 射频关闭 | 0% |

**状态转换核心逻辑** (`esp32_firmware/src/main.cpp` `renderTask` 函数):

```cpp
// 唤醒路径：收到数据时强制唤醒
if (needWake && (g_screenDimmed || g_screenSleeping)) {
    setCpuFrequencyMhz(240);
    WiFi.setSleep(false);
    esp_wifi_set_ps(WIFI_PS_NONE);
    display.wakeup();
    g_screenDimmed = false;
    g_screenSleeping = false;
}
// 休眠路径：60秒无数据
else if (!g_screenSleeping && timeSinceData > SCREEN_SLEEP_TIMEOUT) {
    setCpuFrequencyMhz(80);
    WiFi.setSleep(true);
    esp_wifi_set_ps(WIFI_PS_MAX_MODEM);
    esp_wifi_set_listen_interval(3);
    display.sleep();
    g_screenSleeping = true;
}
// 变暗路径：30秒无数据
else if (!g_screenDimmed && timeSinceData > SCREEN_DIM_TIMEOUT) {
    display.dim();
    g_screenDimmed = true;
}
```

**唤醒触发源**:

- **数据到达**: `commTask` 收到服务器数据后设置 `g_forceWake = true`，渲染任务检测到后执行完整唤醒流程
- **触摸事件**: `TouchHandler` 检测到触摸后重置 `g_lastDataReceived`
- **接近感应**: 电容微量差分检测（`proximity.isNear()`），唤醒后持续亮屏 15 秒（`PROX_WAKE_DURATION_MS`）
- **BOOT 键 (GPIO0)**: 休眠中按下唤醒屏幕 15 秒

---

## 二、CPU 频率动态调整

ESP32-S3 支持 80 / 160 / 240 MHz 三档 CPU 频率，固件根据运行状态和芯片温度自动切换。

### 2.1 运行态调频

| 场景 | 目标频率 | 代码位置 |
|------|---------|---------|
| 唤醒（数据到达 / 触摸 / 接近） | 240 MHz | `renderTask` 唤醒路径 |
| 屏幕休眠（60s 超时） | 80 MHz | `renderTask` 休眠路径 |
| Light Sleep 唤醒 | 240 MHz | `renderTask` Light Sleep 唤醒后 |

### 2.2 温控自适应

每 10 秒检测一次 CPU 温度（`temperatureRead()`），根据温度阈值动态降频：

```
温度阈值与动作:

  正常 (<50°C)     → 恢复 240 MHz（如之前降过频）
  警告 (>55°C)     → 降至 160 MHz
  严重 (>65°C)     → 降至 80 MHz + 唤醒显示
```

**实现代码** (`renderTask` 温控段):

```cpp
float cpuTemp = temperatureRead();
if (cpuTemp > 65.0f) {
    setCpuFrequencyMhz(80);
    display.wakeup();
} else if (cpuTemp > 55.0f) {
    setCpuFrequencyMhz(160);
} else if (cpuTemp < 50.0f && getCpuFrequencyMhz() < 240) {
    setCpuFrequencyMhz(240);
}
```

> **注意**: 温控降频与休眠降频独立运行。当系统处于 SLEEP 状态时 CPU 已经是 80 MHz，温控逻辑会被 `g_screenSleeping` 条件跳过（避免重复操作）。

### 2.3 VRR 动态帧率

帧率随功耗状态联动调整，进一步降低 SLEEP 状态的 CPU 负载：

| 状态 | 帧间隔 | 等效帧率 |
|------|--------|---------|
| ACTIVE (Agent 工作中) | 16 ms | 60 fps |
| ACTIVE (认证/交互) | 33 ms | 30 fps |
| ACTIVE (空闲/离线) | 20 ms | 50 fps |
| IDLE (数据静默 >15s) | 200 ms | 5 fps |
| DIM | 1000 ms | 1 fps |
| SLEEP | 500 ms | 2 fps |

---

## 三、WiFi 省电模式

WiFi 射频是 ESP32 的主要功耗来源之一。固件在不同功耗状态下采用不同的 WiFi 省电策略。

### 3.1 省电模式切换

| 功耗状态 | WiFi 睡眠模式 | API 调用 | 说明 |
|---------|-------------|---------|------|
| ACTIVE / DIM | `WIFI_PS_NONE` | `esp_wifi_set_ps(WIFI_PS_NONE)` | 射频常开，最低延迟 |
| SLEEP | `WIFI_PS_MAX_MODEM` | `esp_wifi_set_ps(WIFI_PS_MAX_MODEM)` | 射频仅在 DTIM beacon 时唤醒，约 50% 省电 |
| LIGHT_SLEEP | 芯片休眠 | `esp_light_sleep_start()` | 射频完全关闭，仅触摸唤醒 |

### 3.2 DTIM 监听间隔调优

进入 SLEEP 状态后，除了启用 `WIFI_PS_MAX_MODEM`，还设置了监听间隔为 3 个 beacon：

```cpp
esp_wifi_set_listen_interval(3);  // 每3个DTIM beacon唤醒一次
```

- **默认值**: 1（每个 beacon 都唤醒）
- **优化值**: 3（每 3 个 beacon 唤醒一次，进一步降低 WiFi 功耗约 60%）
- **代价**: 唤醒延迟略增（从约 100ms 增至约 300ms），对非实时场景可接受

### 3.3 Arduino WiFi 库封装

固件同时使用了 Arduino `WiFi.setSleep(true/false)` 封装，与底层 ESP-IDF API 配合：

```cpp
// 唤醒时
WiFi.setSleep(false);                    // Arduino层：禁用WiFi自动睡眠
esp_wifi_set_ps(WIFI_PS_NONE);           // IDF层：关闭省电模式

// 休眠时
WiFi.setSleep(true);                     // Arduino层：启用WiFi自动睡眠
esp_wifi_set_ps(WIFI_PS_MAX_MODEM);      // IDF层：最大省电模式
esp_wifi_set_listen_interval(3);         // IDF层：DTIM间隔=3
```

### 3.4 config.h 中的 WiFi 省电配置

```cpp
#define IDLE_POWER_MODE           2     // 空闲省电模式(0=ACTIVE,1=MODEM_SLEEP_AUTO,2=LIGHT_SLEEP)
#define DTIM_ACTIVE               1     // 活跃态DTIM间隔
#define DTIM_IDLE                 10    // 空闲态DTIM间隔
#define IDLE_TIMEOUT_MS           30000 // 进入省电模式的空闲超时(ms)
#define WAKE_CHECK_INTERVAL_MS    500   // 唤醒检查间隔(ms)
#define BSS_MAX_IDLE_SEC          300   // BSS最大空闲时间(秒)
```

> **注意**: `IDLE_POWER_MODE=2` 表示空闲时使用 Light Sleep 模式。实际的 Light Sleep 进入逻辑在 `renderTask` 中实现，而非 WiFi 驱动层自动触发。

---

## 四、屏幕背光缓动

背光亮度变化采用一阶 EMA（指数移动平均）低通滤波器实现平滑过渡，避免亮度瞬间跳变造成的视觉闪烁。

### 4.1 EMA 滤波器参数

```cpp
// esp32_firmware/src/display_manager.h
static constexpr float BRIGHTNESS_SMOOTHING = 0.15f;  // EMA系数
```

- **alpha = 0.15**: 每帧向目标亮度趋近 15%，兼顾响应速度与平滑度
- **收敛时间**: 约 20 帧（20 * 20ms = 400ms）达到目标亮度的 95%
- **截止阈值**: 差值 < 1.0 时直接对齐，避免无限趋近

### 4.2 核心算法

```cpp
void DisplayManager::applySmoothBacklight() {
    float target = (float)_targetBrightness;
    float diff = target - _currentBrightness;

    if (fabsf(diff) < 1.0f) {
        _currentBrightness = target;           // 差值极小，直接对齐
    } else {
        _currentBrightness += diff * BRIGHTNESS_SMOOTHING;  // EMA趋近
    }

    _lcd.setBrightness((uint8_t)(_currentBrightness + 0.5f));  // 四舍五入
}
```

**每帧调用时机**: `renderTask` 主循环末尾，在显示更新和动画更新之后：

```cpp
// 一阶缓动背光：每帧平滑过渡亮度，消除瞬间闪烁
display.applySmoothBacklight();
```

### 4.3 两种亮度设置接口

| 方法 | 用途 | 行为 |
|------|------|------|
| `setBrightnessImmediate(uint8_t)` | 启动初始化 | 立即设置硬件亮度 + 同步内部状态，无渐变 |
| `setBrightness(uint8_t)` | 运行时调节 | 仅设置目标亮度，由 `applySmoothBacklight` 每帧趋近 |

**启动时使用立即设置**（`begin()` 函数）：

```cpp
void DisplayManager::begin() {
    _lcd.init();
    _lcd.setRotation(SCREEN_ROTATION);
    _sprite.fillScreen(COLOR_BG);
    setBrightnessImmediate(LCD_BRIGHTNESS);  // 启动时立即设置，避免渐变
}
```

**运行时使用缓动设置**（光照传感器自动调节、状态切换等）：

```cpp
// 光照传感器自动调节
uint8_t pwm = ambientLight.autoAdjustBacklight(lux);
display.setBrightness(pwm);  // 平滑过渡

// 功耗状态切换
display.dim();     // 目标亮度 60 (30%)
display.sleep();   // 目标亮度 0 (关闭)
display.wakeup();  // 目标亮度 LCD_BRIGHTNESS (200, 100%)
```

### 4.4 各状态目标亮度

| 调用方法 | 目标亮度值 | 百分比 | 触发场景 |
|---------|----------|--------|---------|
| `setBrightnessImmediate(200)` | 200 | 100% | 启动初始化 |
| `wakeup()` | 200 | 100% | 收到数据 / 触摸 / 接近感应唤醒 |
| `dim()` | 60 | 30% | 30 秒无数据 |
| `sleep()` | 0 | 0% | 60 秒无数据 |
| `setBrightness(pwm)` | 0-255 | 自动 | 光照传感器 BH1750 实时调节 |

---

## 五、Light Sleep 模式

当屏幕进入 SLEEP 状态 5 分钟后仍无数据，系统进入 ESP32 Light Sleep 深度休眠，功耗降至约 5 mA。

### 5.1 进入 Light Sleep 的前置条件

```cpp
static constexpr uint32_t LIGHT_SLEEP_TIMEOUT = 300000;  // 5min

if (now - g_screenSleepStart >= LIGHT_SLEEP_TIMEOUT) {
    display.sleep();                            // 确保背光已关闭
    esp_sleep_enable_touchpad_wakeup();         // 使能触摸唤醒

    // RTC IO 状态保持：锁定关键引脚电平
    gpio_hold_en((gpio_num_t)LCD_BL);           // 背光保持低电平
    gpio_hold_en((gpio_num_t)BUZZER_PIN);       // 蜂鸣器保持低电平（静音）
    gpio_hold_en((gpio_num_t)LCD_CS);           // SPI片选保持高电平（未选中）

    esp_light_sleep_start();                    // 进入 Light Sleep
}
```

### 5.2 GPIO Hold 机制

Light Sleep 期间 CPU 停止运行，GPIO 引脚电平可能漂移。固件通过 `gpio_hold_en()` 锁定关键引脚：

| 引脚 | GPIO | 保持电平 | 原因 |
|------|------|---------|------|
| `LCD_BL` (背光) | 48 | LOW | 防止背光意外亮起 |
| `BUZZER_PIN` (蜂鸣器) | 18 | LOW | 防止意外发声 |
| `LCD_CS` (SPI片选) | 5 | HIGH | 防止 LCD 被意外选中 |

唤醒后立即释放 GPIO hold：

```cpp
// === 唤醒 ===
gpio_hold_dis((gpio_num_t)LCD_BL);
gpio_hold_dis((gpio_num_t)BUZZER_PIN);
gpio_hold_dis((gpio_num_t)LCD_CS);
```

### 5.3 唤醒源

- **触摸唤醒**: `esp_sleep_enable_touchpad_wakeup()` 使能电容触摸唤醒（GPIO1 / Touch1）
- **WiFi Beacon**: 代码中预留了 `esp_sleep_enable_wifi_beacon_wakeup()` 注释，当前 ESP-IDF 版本不支持此 API

### 5.4 RTC 内存保留

固件使用 `RTC_NOINIT_ATTR` 宏将崩溃计数器放入 RTC noinit 段，Light Sleep 期间数据不会丢失：

```cpp
RTC_NOINIT_ATTR uint32_t s_crashCount;
RTC_NOINIT_ATTR uint32_t s_crashMagic;
```

> **注意**: `RTC_NOINIT_ATTR` 不能用 `= 0` 初始化，否则编译器会将其放入 `.rtc.data` 段（每次冷启动清零）。必须保持未初始化状态，编译器才会将其放入 `.rtc.noinit` 段（冷启动保留）。

### 5.5 Light Sleep 唤醒后的恢复流程

```cpp
// 唤醒后恢复全速运行
setCpuFrequencyMhz(240);           // CPU 恢复 240 MHz
WiFi.setSleep(false);               // WiFi 禁用自动睡眠
esp_wifi_set_ps(WIFI_PS_NONE);      // WiFi 恢复活跃模式
g_screenSleeping = false;
g_screenDimmed = false;
g_forceWake.store(true);            // 触发渲染任务唤醒屏幕
```

---

## 六、各状态功耗估算

以下为基于硬件规格和实测的功耗估算（5V USB 供电）：

| 状态 | CPU 频率 | WiFi 模式 | LCD 背光 | 帧率 | 估算电流 | 说明 |
|------|---------|----------|---------|------|---------|------|
| **ACTIVE** | 240 MHz | 活跃 (PS_NONE) | 100% (200/255) | 30-60 fps | ~150 mA | 全速运行，WiFi + LCD + CPU 全开 |
| **DIM** | 240 MHz | 活跃 (PS_NONE) | 30% (60/255) | 1 fps | ~100 mA | 背光降低为主要省电点 |
| **SLEEP** | 80 MHz | 省电 (PS_MAX_MODEM) | 0% (关闭) | 2 fps | ~30 mA | CPU 降频 + WiFi 省电 + LCD 关闭 |
| **LIGHT_SLEEP** | 休眠 | 射频关闭 | 0% (关闭) | N/A | ~5 mA | 芯片休眠，仅 RTC + 触摸唤醒电路工作 |

### 6.1 功耗分解

**ACTIVE 状态 (~150 mA)**:

- CPU @ 240 MHz: ~50 mA
- WiFi 活跃收发: ~50 mA
- LCD 全亮 (240x240): ~40 mA
- 外设 (触摸/光照/蜂鸣器): ~10 mA

**SLEEP 状态 (~30 mA)**:

- CPU @ 80 MHz: ~15 mA
- WiFi 省电 (DTIM=3): ~10 mA
- LCD 关闭: ~0 mA
- 外设待机: ~5 mA

**LIGHT_SLEEP 状态 (~5 mA)**:

- RTC + 触摸唤醒电路: ~5 mA
- CPU / WiFi / LCD: 全部关闭

### 6.2 省电效果对比

```
全速运行 (ACTIVE):           150 mA × 24h = 3600 mAh  → 5000mAh电池约1.4天
启用全部省电策略 (LIGHT_SLEEP):    5 mA × 24h =  120 mAh  → 5000mAh电池约41天

省电比: 30倍
```

> **实际续航**: 取决于 ACTIVE/SLEEP 状态的时间占比。典型工作场景（每小时活跃 10 分钟）下，平均功耗约 30-40 mA，5000 mAh 电池可使用约 5-7 天。

---

## 七、配置参数速查

所有电源管理相关参数定义在 `esp32_firmware/include/config.h`：

| 参数 | 值 | 说明 |
|------|---|------|
| `SCREEN_DIM_TIMEOUT` | 30000 ms | 进入 DIM 状态的超时 |
| `SCREEN_SLEEP_TIMEOUT` | 60000 ms | 进入 SLEEP 状态的超时 |
| `LIGHT_SLEEP_TIMEOUT` | 300000 ms (硬编码) | 进入 Light Sleep 的超时 |
| `LCD_BRIGHTNESS` | 200 | 默认背光亮度 (0-255) |
| `BRIGHTNESS_SMOOTHING` | 0.15f | EMA 背光缓动系数 |
| `IDLE_POWER_MODE` | 2 | 空闲省电模式 (2=Light Sleep) |
| `DTIM_ACTIVE` | 1 | 活跃态 DTIM 间隔 |
| `DTIM_IDLE` | 10 | 空闲态 DTIM 间隔 |
| `IDLE_TIMEOUT_MS` | 30000 ms | 进入省电模式的空闲超时 |
| `PROX_WAKE_DURATION_MS` | 15000 ms | 接近感应唤醒后亮屏时长 |

---

## 八、架构流程图

```
┌─────────────────────────────────────────────────────────────┐
│                      commTask (Core 0)                      │
│  收到数据 → g_forceWake=true → g_lastDataReceived=now       │
│  触摸事件 → 重置 g_lastDataReceived                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ atomic 标志
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    renderTask (Core 1)                       │
│                                                             │
│  ┌─ 检查 g_forceWake ──────────────────────────────────┐   │
│  │  true + (dimmed || sleeping) → 唤醒流程              │   │
│  │    setCpuFrequencyMhz(240)                          │   │
│  │    WiFi.setSleep(false)                             │   │
│  │    esp_wifi_set_ps(WIFI_PS_NONE)                    │   │
│  │    display.wakeup() → 目标亮度 200                   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ 超时检测 ──────────────────────────────────────────┐   │
│  │  >30s: display.dim() → 目标亮度 60                   │   │
│  │  >60s: display.sleep() → 目标亮度 0                  │   │
│  │        setCpuFrequencyMhz(80)                       │   │
│  │        WiFi.setSleep(true)                          │   │
│  │        esp_wifi_set_ps(WIFI_PS_MAX_MODEM)           │   │
│  │  >5min: esp_light_sleep_start()                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ 温控 (每10s) ─────────────────────────────────────┐   │
│  │  >65°C → 80MHz    >55°C → 160MHz    <50°C → 240MHz │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ 背光缓动 (每帧) ──────────────────────────────────┐   │
│  │  applySmoothBacklight()                             │   │
│  │  _currentBrightness += (target - current) * 0.15   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```
