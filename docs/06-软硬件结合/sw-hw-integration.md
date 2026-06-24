# 软硬件结合点详解

> 本文档详细解析桌面电子宠物项目中 ESP32-S3 固件与各硬件外设之间的结合点，涵盖 GPIO 映射、总线协议、驱动初始化、中断机制及电源管理策略。
> 所有代码路径基于 `esp32_firmware/` 目录，硬件平台为微雪 ESP32-S3 1.54inch LCD 开发板。

---

## 一、GPIO 与外设映射总表

下表列出固件中所有已使用的 GPIO 引脚及其对应外设、信号方向、驱动代码文件和配置常量。

| GPIO | 外设 | 方向 | 驱动代码 | 配置常量 |
|------|------|------|----------|----------|
| GPIO 0 | BOOT 按键 | 输入 | `main.cpp` | 直接 `digitalRead(0)` |
| GPIO 1 | 电容触摸 (Touch1) | 输入 | `touch_handler.cpp` | `TOUCH_PIN` |
| GPIO 2 | LCD D/C (数据/命令) | 输出 | `display_manager.cpp` | `LCD_DC` |
| GPIO 4 | LCD RST (复位) | 输出 | `display_manager.cpp` | `LCD_RST` |
| GPIO 5 | LCD CS (片选) | 输出 | `display_manager.cpp` | `LCD_CS` |
| GPIO 11 | SPI MOSI | 输出 | `display_manager.cpp` | `LCD_MOSI` |
| GPIO 12 | SPI SCLK (时钟) | 输出 | `display_manager.cpp` | `LCD_SCLK` |
| GPIO 13 | SPI MISO | 输入 | `display_manager.cpp` | `LCD_MISO` |
| GPIO 18 | 无源蜂鸣器 (PWM) | 输出 | `sound_manager.cpp` | `BUZZER_PIN` |
| GPIO 41 | I2C SDA (共享总线) | 双向 | `ambient_light.cpp` / `haptic_driver.cpp` | `BH1750_SDA_PIN` / `HAPTIC_SDA_PIN` |
| GPIO 42 | I2C SCL (共享总线) | 输出 | `ambient_light.cpp` / `haptic_driver.cpp` | `BH1750_SCL_PIN` / `HAPTIC_SCL_PIN` |
| GPIO 48 | LCD 背光 (PWM) | 输出 | `display_manager.cpp` | `LCD_BL` |

**I2C 总线设备地址：**

| 设备 | I2C 地址 | 配置常量 |
|------|----------|----------|
| BH1750 光照传感器 | 0x23 | `BH1750_ADDR` |
| DRV2605L 触觉驱动 | 0x5A | `DRV2605_ADDR` |

> **注意：** BH1750 和 DRV2605L 共享同一条 I2C 总线 (Wire / I2C0)，通过不同的设备地址进行区分。总线速率默认 100kHz (Standard Mode)。

---

## 二、SPI 总线：LCD 显示

### 2.1 硬件概述

LCD 屏幕采用 ST7789V2 驱动芯片，240x240 分辨率，16 位色深 (RGB565)。ESP32-S3 通过 SPI2_HOST 总线与 LCD 通信，最高时钟频率 80MHz，使用 DMA 传输以释放 CPU。

**SPI 引脚映射：**

```
ESP32-S3          ST7789V2
────────          ────────
GPIO 11 (MOSI) ──→ SDA (数据输入)
GPIO 12 (SCLK) ──→ SCL (时钟)
GPIO 13 (MISO) ←── (未使用，保留)
GPIO 5  (CS)   ──→ CS  (片选)
GPIO 2  (DC)   ──→ DC  (数据/命令选择)
GPIO 4  (RST)  ──→ RST (硬件复位)
GPIO 48 (PWM)  ──→ BLK (背光控制)
```

### 2.2 软件初始化流程

显示管理器在 `DisplayManager::begin()` 中完成初始化：

```cpp
// display_manager.cpp - begin()
void DisplayManager::begin() {
    _lcd.init();                          // 1. LovyanGFX 底层初始化 (SPI + DMA + ST7789V2 命令序列)
    _lcd.setRotation(SCREEN_ROTATION);    // 2. 设置屏幕旋转方向 (0=竖屏)
    _sprite.fillScreen(COLOR_BG);         // 3. 清屏
    setBrightnessImmediate(LCD_BRIGHTNESS); // 4. 设置初始亮度 (200/255)

    // 5. 创建双缓冲离屏画布
    _sprite.deleteSprite();
    _sprite.createSprite(SCREEN_WIDTH, SCREEN_HEIGHT);        // 主画布 240x240
    _transitionSprite.createSprite(SCREEN_WIDTH, SCREEN_HEIGHT); // 过渡画布 (淡入淡出)
}
```

**LovyanGFX LGFX 类配置要点：**
- SPI 主机：`SPI2_HOST` (ESP32-S3 的高速 SPI)
- 时钟频率：80 MHz
- DMA 通道：自动分配
- 帧缓冲：Sprite (离屏画布)，与屏幕同尺寸 240x240x2 = 115,200 字节

### 2.3 帧更新路径

帧数据从 Sprite 画布推送到 LCD 屏幕的完整路径：

```
绘制操作 (drawFace, drawWeatherPanel, ...)
    │
    ▼
_sprite (PSRAM 帧缓冲, 240x240xRGB565)
    │
    ▼
_sprite.pushSprite(&_lcd, 0, 0)   ← LovyanGFX 内部调用 SPI DMA
    │
    ▼
SPI DMA 传输 → ST7789V2 GRAM
    │
    ▼
LCD 面板显示
```

**DMA 等待机制：** 在每次 pushSprite 之前，必须调用 `_lcd.waitDMA()` 等待上一帧 DMA 传输完成，防止 CPU 覆盖正在传输的缓冲区：

```cpp
// display_manager.cpp - update()
_lcd.waitDMA();                    // 等待上一帧 DMA 完成
_sprite.pushSprite(&_lcd, 0, 0);  // 提交新帧
```

### 2.4 脏矩形局部刷新

动画更新时仅重绘变化区域，大幅减少 SPI 传输量：

```cpp
// display_manager.cpp - updateAnimation()
// 脏矩形：仅推送表情动画区域 (~240x40 vs 全屏 240x240，减少 ~80% SPI 传输)
_lcd.waitDMA();
_lcd.setClipRect(0, faceY - 4, SCREEN_WIDTH, FACE_SIZE + 8);
_sprite.pushSprite(&_lcd, 0, 0);
_lcd.clearClipRect();
```

### 2.5 V-Sync TE 中断 (Tearing Effect)

ST7789V2 的 TE 引脚在每帧扫描开始时产生边沿信号，可用于消除画面撕裂。

**硬件接线：** LCD_TE_PIN (当前配置为 -1，即禁用；接线后改为实际 GPIO)

**中断配置：**

```cpp
// display_manager.cpp - setupVSync()
void DisplayManager::setupVSync() {
    if (LCD_TE_PIN < 0) return;  // 禁用状态
    pinMode(LCD_TE_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(LCD_TE_PIN), _teIsrHandler, FALLING);
    s_teTriggered = false;
}
```

**ISR 处理函数 (IRAM)：**

```cpp
// display_manager.cpp
void IRAM_ATTR DisplayManager::_teIsrHandler() {
    s_teTriggered = true;  // 仅设置标志，不做任何耗时操作
}
```

**V-Sync 等待：**

```cpp
// display_manager.cpp - waitForVSync()
void DisplayManager::waitForVSync(uint32_t timeout_ms) {
    if (LCD_TE_PIN < 0 || !digitalPinIsValid(LCD_TE_PIN)) return;
    s_teTriggered = false;
    unsigned long start = millis();
    while (!s_teTriggered) {
        if (millis() - start > timeout_ms) break;
        vTaskDelay(pdMS_TO_TICKS(1));  // 1ms yield，释放 CPU 给其他 FreeRTOS 任务
    }
}
```

### 2.6 PWM 背光控制

背光通过 GPIO48 的 PWM 信号控制，亮度范围 0-255：

```cpp
// display_manager.cpp - applySmoothBacklight()
void DisplayManager::applySmoothBacklight() {
    float target = (float)_targetBrightness;
    float diff = target - _currentBrightness;
    if (fabsf(diff) < 1.0f) {
        _currentBrightness = target;
    } else {
        _currentBrightness += diff * BRIGHTNESS_SMOOTHING;  // 一阶 EMA 低通滤波
    }
    _lcd.setBrightness((uint8_t)(_currentBrightness + 0.5f));
}
```

背光状态机：
- **ACTIVE** → 全亮 (`LCD_BRIGHTNESS` = 200)
- **DIM** → 30% 亮度 (60)
- **SLEEP** → 关闭 (0)
- **唤醒** → 平滑渐变回全亮

---

## 三、I2C 总线：BH1750 光照传感器

### 3.1 硬件概述

BH1750FVI (GY-302 模块) 是一款数字光照度传感器，通过 I2C 接口输出 16 位原始数据，分辨率 1 lx，测量范围 1-65535 lx。

**接线：**

```
ESP32-S3            BH1750 (GY-302)
────────            ──────────────
GPIO 41 (SDA)  ←──→ SDA
GPIO 42 (SCL)  ───→ SCL
3.3V           ───→ VCC
GND            ───→ GND
```

**I2C 地址：** 0x23 (ADDR 引脚接地时)

### 3.2 初始化序列

```cpp
// ambient_light.cpp - begin()
bool AmbientLightManager::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);              // 1. 初始化 I2C0 总线

    // 2. 检测传感器是否响应
    _wire.beginTransmission(BH1750_ADDR);
    if (_wire.endTransmission() != 0) {
        _available = false;
        return false;  // 设备未找到
    }

    // 3. 上电命令
    _writeCommand(BH1750_POWER_ON);  // 0x01
    delay(10);

    // 4. 设置连续高分辨率模式
    _writeCommand(BH1750_CONT_HRES);  // 0x10
    delay(180);  // 首次测量需要 120~180ms 稳定时间

    _available = true;
    return true;
}
```

**命令字节说明：**

| 命令 | 字节值 | 说明 |
|------|--------|------|
| `BH1750_POWER_ON` | 0x01 | 上电 |
| `BH1750_CONT_HRES` | 0x10 | 连续高分辨率模式 (1 lx, 120ms) |
| Power Down | 0x00 | 关机 (低功耗) |

### 3.3 数据读取与 EMA 滤波

```cpp
// ambient_light.cpp - readLux()
int16_t AmbientLightManager::readLux() {
    if (!_available) return -1;

    // 1. 从 I2C 读取 2 字节原始数据
    _wire.requestFrom((uint8_t)BH1750_ADDR, (uint8_t)2);
    if (_wire.available() < 2) return -1;

    uint16_t raw = (_wire.read() << 8) | _wire.read();  // 高字节在前

    // 2. 转换为 lux 值 (高分辨率模式: raw / 1.2)
    int16_t rawLux = (int16_t)(raw / 1.2f);
    if (rawLux < 0) rawLux = 0;

    // 3. EMA 低通滤波 (alpha=0.15，消除光照抖动)
    //    new = alpha * raw + (1 - alpha) * old
    _emaLux = EMA_ALPHA * rawLux + (1.0f - EMA_ALPHA) * _emaLux;

    _lastLux = (int16_t)_emaLux;
    return _lastLux;
}
```

**EMA 滤波参数：** `EMA_ALPHA` = 0.15（约 7 个采样周期达到 63% 响应）

### 3.4 CIE 1931 感知亮度映射

人眼对亮度的感知是非线性的 (Weber-Fechner 定律)。固件使用 CIE 1931 标准曲线将物理照度映射为感知亮度：

```cpp
// ambient_light.cpp - cie1931_curve()
static float cie1931_curve(float Y) {
    if (Y <= 0.008856f) {
        return 903.3f * Y;                    // 低亮度区：线性
    } else {
        return 116.0f * powf(Y, 1.0f/3.0f) - 16.0f;  // 高亮度区：立方根
    }
}
```

**自动背光调节流程：**

```
BH1750 读取 lux (0~10000)
    │
    ▼
归一化到 0.0~1.0 (lux / 10000)
    │
    ▼
CIE 1931 曲线变换 (非线性 → 感知线性)
    │
    ▼
映射到 PWM 范围 (MIN_PWM=15 ~ MAX_PWM=255)
    │
    ▼
setBrightness(pwm) → LCD 背光
```

**最低亮度保护：** `MIN_PWM = 15` (约 6%)，确保完全黑暗环境下屏幕仍然可见。

### 3.5 与渲染任务的集成

光照读取在 `renderTask` 中周期性执行，每 2 秒读取一次：

```cpp
// main.cpp - renderTask()
static unsigned long lastLightRead = 0;
if (ambientLight.isAvailable() && !g_screenSleeping &&
    (now - lastLightRead >= BH1750_READ_INTERVAL)) {  // BH1750_READ_INTERVAL = 2000ms
    int16_t lux = ambientLight.readLux();
    uint8_t pwm = ambientLight.autoAdjustBacklight(lux);
    display.setBrightness(pwm);
    lastLightRead = now;
}
```

**数据流完整路径：**

```
BH1750 硬件 → I2C readLux() → EMA 滤波 → CIE 1931 映射 → PWM duty → LCD 背光
```

---

## 四、I2C 总线：DRV2605L 触觉驱动

### 4.1 硬件概述

DRV2605L 是 TI 的触觉反馈驱动芯片，内置 123 种波形效果 (Library 6 为 LRA 优化)，支持内部触发和波形序列播放。本项目使用 LRA (线性谐振致动器) 马达。

**接线：** 与 BH1750 共享同一条 I2C 总线 (GPIO41=SDA, GPIO42=SCL)

**I2C 地址：** 0x5A

### 4.2 关键寄存器

| 寄存器 | 地址 | 说明 |
|--------|------|------|
| Mode | 0x01 | 播放模式 (内部触发/外部触发/波形序列) |
| Library | 0x03 | 波形库选择 (0x06=LRA 优化) |
| WaveformSeq1~8 | 0x04~0x0B | 波形序列槽位 |
| Go | 0x0C | 触发播放 (写 1 启动，自动清零) |
| RatedVoltage | 0x16 | 额定电压 (校准参数) |
| ODClamp | 0x17 | 过驱动钳位电压 (校准参数) |
| Feedback | 0x1A | 反馈控制 (LRA/ERM 选择) |
| Control1~3 | 0x1B~0x1D | 控制寄存器 |

### 4.3 初始化序列

```cpp
// haptic_driver.cpp - begin()
bool HapticDriver::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);

    // 1. I2C 设备检测
    _wire.beginTransmission(DRV2605_ADDR);
    if (_wire.endTransmission() != 0) return false;

    // 2. 设置为内部触发模式
    _writeRegister(REG_MODE, 0x00);       // MODE_INTERNAL

    // 3. 选择 LRA 优化波形库 (Library 6，123 种效果)
    _writeRegister(REG_LIBRARY, 0x06);

    // 4. 反馈控制: LRA 模式 [7]=1, 带宽中等 [6:4]=5
    _writeRegister(REG_FEEDBACK, 0xA0);

    // 5. Control1: 采样时间 4x, 驱动时间 36us
    _writeRegister(REG_CONTROL1, 0x93);

    // 6. Control2: 双向制动 + 空闲时间 0
    _writeRegister(REG_CONTROL2, 0xF5);

    // 7. Control3: 电动制动 + 噪声门 + 软制动
    _writeRegister(REG_CONTROL3, 0xA0);

    // 8. 自动校准 LRA 参数
    calibrate();
}
```

### 4.4 自动校准流程

DRV2605L 的自动校准功能会测量 LRA 马达的谐振频率和阻抗特性，自动优化驱动参数：

```cpp
// haptic_driver.cpp - calibrate()
bool HapticDriver::calibrate() {
    // Step 1: 设置额定电压 (LRA 典型值 1.8V RMS)
    // RatedVoltage = V_rms * 255 / 5.36V ≈ 85 (0x55)
    _writeRegister(REG_RATEDVOL, 0x55);

    // Step 2: 设置过驱动钳位电压 (典型值 2.5V peak)
    // ODClamp = V_peak * 255 / 5.6V ≈ 114 (0x72)
    _writeRegister(REG_ODCLAMP, 0x72);

    // Step 3: 设置反馈寄存器 (LRA 模式 + back-EMF 使能)
    _writeRegister(REG_FEEDBACK, 0xA0);

    // Step 4: 进入自动校准模式 (Mode=0x07)
    _writeRegister(REG_MODE, 0x07);

    // Step 5: 触发校准 (GO=1)
    _writeRegister(REG_GO, 0x01);

    // Step 6: 等待校准完成 (GO 位自动清零，最多 1.5 秒)
    while (millis() - start < 1500) {
        uint8_t go;
        _readRegisterSafe(REG_GO, go);
        if ((go & 0x01) == 0) {
            // 校准完成，检查诊断结果
            uint8_t diag;
            _readRegisterSafe(REG_STATUS, diag);
            return (diag == 0x00);  // 0x00 = 校准成功
        }
        delay(50);
    }
}
```

### 4.5 效果播放

```cpp
// haptic_driver.cpp - playEffect()
void HapticDriver::playEffect(uint8_t effectId) {
    if (!_available) return;

    // 1. 设置为内部触发模式
    _writeRegister(REG_MODE, 0x00);  // MODE_INTERNAL

    // 2. 填充波形序列: 槽0=效果ID, 槽1=终止(0)
    _writeRegister(REG_WAVESEQ1, effectId);
    _writeRegister(REG_WAVESEQ2, 0x00);  // 终止标记

    // 3. 触发播放 (GO=1, 硬件自动清零)
    _writeRegister(REG_GO, 0x01);
}
```

**预定义效果常量：**

| 方法 | 效果 ID | 说明 |
|------|---------|------|
| `click()` | EFFECT_CLICK | 轻击反馈 |
| `buzz()` | EFFECT_BUZZ | 嗡嗡反馈 |
| `strongHit()` | EFFECT_STRONG | 强击反馈 |
| `softTouch()` | EFFECT_SOFT | 柔软触感 |

### 4.6 与触摸事件的集成

在 `main.cpp` 的 `setup()` 中，触摸事件回调绑定了触觉反馈：

```cpp
// main.cpp - setup()
touch.setCallback([](TouchEvent e) {
    if (e == TOUCH_SINGLE_TAP) {
        sound.playNotification();
        hapticDriver.click();        // 单击 → 轻击反馈
    } else if (e == TOUCH_DOUBLE_TAP) {
        sound.playNotification();
        hapticDriver.buzz();         // 双击 → 嗡嗡反馈
    } else if (e == TOUCH_LONG_PRESS) {
        sound.playAlert();
        hapticDriver.strongHit();    // 长按 → 强击反馈
    }
});
```

---

## 五、电容触摸：GPIO1

### 5.1 硬件概述

ESP32-S3 内置电容触摸外设，无需外部触摸芯片。GPIO1 对应 Touch1 通道，可检测手指接近和触摸。触摸检测基于电容变化：手指靠近时，引脚对地电容增大，touchRead 值下降。

### 5.2 基线校准

触摸检测依赖基线值的准确性。初始化时采样 20 次取平均作为基线：

```cpp
// touch_handler.cpp - calibrate()
void TouchHandler::calibrate() {
    uint32_t sum = 0;
    for (int i = 0; i < 20; i++) {
        sum += touchRead(TOUCH_PIN);  // 读取 Touch1 通道原始值
        delay(10);
    }
    _baseline = sum / 20;  // 20 次采样平均
}
```

**检测逻辑：** `touched = (touchRead < baseline - threshold)`

- `TOUCH_THRESHOLD` = 40 (可调整，值越小越不灵敏)
- 触摸时 touchRead 值下降，当下降幅度超过阈值时判定为触摸

### 5.3 手势状态机

触摸手势通过状态机实现，支持三种手势：

```
         按下              释放 (<400ms)
IDLE ─────────→ PRESSED ─────────────────→ 判断手势
         │                    │
         │                    ├─ 400ms 内再次按下 → DOUBLE_TAP
         │                    └─ 400ms 超时无操作 → SINGLE_TAP
         │
         └─ 持续按住 >1000ms → LONG_PRESS
```

**状态机实现：**

```cpp
// touch_handler.cpp - update()
void TouchHandler::update() {
    uint16_t val = touchRead(TOUCH_PIN);
    bool touched = (val < (_baseline - _threshold));
    unsigned long now = millis();

    if (touched && !_wasTouched) {
        // 按下瞬间
        _touchStart = now;
        _wasTouched = true;
    }
    else if (!touched && _wasTouched) {
        // 释放瞬间
        _wasTouched = false;
        unsigned long duration = now - _touchStart;

        if (duration >= TOUCH_LONG_PRESS_MS) {  // 1000ms
            _lastEvent = TOUCH_LONG_PRESS;
        } else {
            // 短按：判断单击/双击
            if (now - _lastTapTime < 400) {
                _tapCount++;      // 400ms 内再次按下 → 计数
            } else {
                _tapCount = 1;    // 超时重置
            }
            _lastTapTime = now;
        }
    }

    // 双击超时检测 (400ms 无第二次按下则触发)
    if (_tapCount > 0 && !_wasTouched && (now - _lastTapTime > 400)) {
        if (_tapCount >= 2) {
            _lastEvent = TOUCH_DOUBLE_TAP;
            if (_callback) _callback(TOUCH_DOUBLE_TAP);
        } else {
            _lastEvent = TOUCH_SINGLE_TAP;
            if (_callback) _callback(TOUCH_SINGLE_TAP);
        }
        _tapCount = 0;
    }
}
```

**参数配置：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `TOUCH_THRESHOLD` | 40 | 触摸判定阈值 (原始值差分) |
| `TOUCH_LONG_PRESS_MS` | 1000 | 长按判定时间 (ms) |
| 双击间隔 | 400ms | 两次短按的最大间隔 |

### 5.4 接近感应 (Proximity Detection)

接近感应基于双 EMA (指数移动平均) 差分检测，无需额外硬件：

**原理：** 维护两条 EMA 线 (快速和慢速)，当手指接近时 touchRead 值下降，快速线下降更快，两条线的差值反映接近程度。

```cpp
// touch_handler.cpp - ProximitySensor::update()
bool ProximitySensor::update() {
    uint16_t raw = touchRead(TOUCH_PIN);

    // 双 EMA 滤波
    _fastEMA = PROX_EMA_FAST_ALPHA * raw + (1.0f - PROX_EMA_FAST_ALPHA) * _fastEMA;  // alpha=0.3
    _slowEMA = PROX_EMA_SLOW_ALPHA * raw + (1.0f - PROX_EMA_SLOW_ALPHA) * _slowEMA;  // alpha=0.05

    // 差分：慢线(基准) - 快线(即时)
    // 手指接近时 raw 下降 → fastEMA 降更快 → diff 为正
    float diff = _slowEMA - _fastEMA;

    if (!_isNear) {
        // 等待上升沿 (diff > 阈值 → 检测到接近)
        if (diff > PROX_RISING_THRESHOLD) {  // 阈值=8
            _isNear = true;
            if (now - _lastEventTime > PROX_COOLDOWN_MS) {  // 冷却 2000ms 防抖
                _lastEventTime = now;
                return true;  // 触发接近事件
            }
        }
    } else {
        // 等待下降沿 (diff 回落 → 手指远离)
        if (diff < PROX_FALLING_THRESHOLD) {  // 阈值=4
            _isNear = false;
        }
    }
}
```

**接近感应参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `PROX_EMA_FAST_ALPHA` | 0.3 | 快速 EMA 系数 (响应快) |
| `PROX_EMA_SLOW_ALPHA` | 0.05 | 慢速 EMA 系数 (基线跟踪) |
| `PROX_RISING_THRESHOLD` | 8 | 上升差分阈值 (接近检测) |
| `PROX_FALLING_THRESHOLD` | 4 | 下降差分阈值 (远离检测) |
| `PROX_COOLDOWN_MS` | 2000 | 接近事件冷却时间 (防抖) |
| `PROX_WAKE_DURATION_MS` | 15000 | 接近唤醒后亮屏时长 |

### 5.5 接近唤醒屏幕

接近感应与屏幕休眠状态机集成：

```cpp
// main.cpp - renderTask()
if (touch.proximity.isNear() || touch.isProximityWakeActive()) {
    if (g_screenSleeping || g_screenDimmed) {
        display.wakeup();           // 唤醒屏幕
        g_screenSleeping = false;
        g_screenDimmed = false;
    }
    g_lastDataReceived.store(now);  // 重置休眠计时
}
```

---

## 六、蜂鸣器：GPIO18

### 6.1 硬件概述

项目使用无源蜂鸣器 (Passive Buzzer)，需要外部提供 PWM 信号才能发声。无源蜂鸣器的优势是可以产生不同频率的音调，实现丰富的声音效果。

**两种音频后端：**

| 后端 | 接口 | 特点 |
|------|------|------|
| PWM (LEDC) | ledcWrite / ledcWriteTone | 方波驱动，实现简单 |
| I2S-PDM | i2s_write | 正弦波驱动，音质更柔和 (苹果级听感) |

### 6.2 PWM 初始化

```cpp
// sound_manager.cpp - begin()
void SoundManager::begin() {
    // Arduino-ESP32 v3.x: 统一 API
    ledcAttach(BUZZER_PIN, 2000, 8);  // 引脚, 初始频率 2kHz, 8 位分辨率

    // Arduino-ESP32 v2.x: 分离 API
    // ledcSetup(0, 2000, 8);       // 通道 0, 2kHz, 8 位
    // ledcAttachPin(BUZZER_PIN, 0);
}
```

### 6.3 方波蜂鸣

最简单的发声方式，直接通过 LEDC 输出指定频率的方波：

```cpp
// sound_manager.cpp - beep()
void SoundManager::beep(uint16_t freq, uint16_t duration) {
    ledcWriteTone(BUZZER_PIN, freq);  // 设置频率
    delay(duration);                   // 持续指定时长
    ledcWrite(BUZZER_PIN, 0);         // 停止输出
}
```

### 6.4 正弦波柔和音调 (硬件定时器 ISR)

正弦波通过硬件定时器中断实现，定时器以 40kHz 频率触发 ISR，在 ISR 中查表输出正弦波 PWM 占空比：

```cpp
// sound_manager.cpp - sineTimerISR()
static void IRAM_ATTR sineTimerISR(void* arg) {
    uint16_t step = s_stepPerTick;
    if (step == 0) return;

    s_stepAcc += step;                      // 累加器 (定点数)
    if (s_stepAcc >= STEP_SCALE) {          // 1024
        s_stepAcc -= STEP_SCALE;
        s_sinIdx = (s_sinIdx + 1) & 63;    // 64 点正弦 LUT
    }
    s_pwmDuty = SIN_LUT[s_sinIdx];          // 查表获取占空比
    ledcWrite(BUZZER_PIN, s_pwmDuty);       // 输出 PWM
}
```

**频率计算：**

```
stepPerTick = freq * SIN_LUT_SIZE * STEP_SCALE / PWM_CARRIER_HZ
            = freq * 64 * 1024 / 40000
```

**定时器配置 (ESP32-S3)：**

```cpp
// sound_manager.cpp - _startSineTimer()
_sineTimer = timerBegin(PWM_CARRIER_HZ);     // 40kHz
timerAttachInterrupt(_sineTimer, &sineTimerISR);
timerStart(_sineTimer);
```

### 6.5 I2S-PDM 音频后端

I2S-PDM 模式提供更高保真度的音频输出，使用 DMA 传输正弦波采样数据，支持 ADSR 包络消除爆音：

```cpp
// sound_manager.cpp - _i2sTone()
void SoundManager::_i2sTone(uint16_t freq, uint16_t duration) {
    // 1. 生成正弦波基础缓冲区
    const int samplesPerCycle = 44100 / freq;
    uint8_t baseBuf[256];
    for (int i = 0; i < bufLen; i++) {
        float angle = 2.0f * 3.14159f * i / bufLen;
        baseBuf[i] = (uint8_t)(128 + 120 * sinf(angle));
    }

    // 2. ADSR 包络 (Attack=8ms, Release=15ms)
    // 短音保护: attack+release 不超过 duration 的 20%

    // 3. 逐块写入 I2S DMA
    while (millis() < endTime) {
        float gain = 计算当前包络增益;
        for (int i = 0; i < bufLen; i++) {
            envBuf[i] = (uint8_t)(128 + (baseBuf[i] - 128) * gain);
        }
        i2s_write(I2S_NUM_0, envBuf, bufLen, &bytesWritten, portMAX_DELAY);
    }
}
```

### 6.6 复合音效

| 音效 | 频率/时序 | 总阻塞时长 | 用途 |
|------|-----------|-----------|------|
| `playStartup()` | 1000→1500→2000 Hz, 各 80ms | ~440ms | 开机提示 |
| `playNotification()` | 2500 Hz x2, 各 60ms | ~160ms | 通知/触摸反馈 |
| `playAlert()` | 1500 Hz x3, 150ms on/100ms off | ~650ms | 警报 (长按) |
| `playOtaProgress()` | 1800 Hz, 30ms | ~30ms | OTA 进度提示 |
| `playOtaSuccess()` | 1000→1500→2000 Hz, 递增时长 | ~600ms | OTA 成功 |
| `playOtaFail()` | 800 Hz x3, 200ms on/100ms off | ~900ms | OTA 失败 |

> **注意：** 复合音效串行播放多段 tone，会阻塞当前 FreeRTOS 任务。但 `delay()` = `vTaskDelay()` 会释放 CPU 给同核其他任务，WiFi 栈不受影响。

---

## 七、电源管理结合

### 7.1 CPU 动态调频

ESP32-S3 支持 80/160/240 MHz 三档 CPU 频率，固件根据系统状态动态调整：

```cpp
// main.cpp - renderTask()
// 唤醒时：全速
setCpuFrequencyMhz(240);

// 屏幕休眠时：降频省电
setCpuFrequencyMhz(80);

// 温控降频
if (cpuTemp > 65.0f) {
    setCpuFrequencyMhz(80);      // 临界温度
} else if (cpuTemp > 55.0f) {
    setCpuFrequencyMhz(160);     // 警告温度
} else if (cpuTemp < 50.0f) {
    setCpuFrequencyMhz(240);     // 恢复全速
}
```

**温控检查周期：** 每 10 秒检测一次 CPU 温度

### 7.2 WiFi 省电模式

```cpp
// main.cpp - renderTask()
// 活跃态：关闭省电，最低延迟
WiFi.setSleep(false);
esp_wifi_set_ps(WIFI_PS_NONE);

// 休眠态：最大省电
WiFi.setSleep(true);
esp_wifi_set_ps(WIFI_PS_MAX_MODEM);       // WiFi 射频仅在 DTIM beacon 时唤醒
esp_wifi_set_listen_interval(3);          // 每 3 个 DTIM beacon 唤醒一次
```

**WiFi 省电配置参数 (config.h)：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `IDLE_POWER_MODE` | 2 | 空闲省电模式 (Light Sleep) |
| `DTIM_ACTIVE` | 1 | 活跃态 DTIM 间隔 |
| `DTIM_IDLE` | 10 | 空闲态 DTIM 间隔 |
| `IDLE_TIMEOUT_MS` | 30000 | 进入省电模式的空闲超时 |

### 7.3 屏幕休眠状态机

```
ACTIVE ──(30s无数据)──→ DIM ──(30s无数据)──→ SLEEP ──(5min)──→ LIGHT_SLEEP
  ↑                        ↑                      ↑                   │
  └────────────────────────┴──────────────────────┴───────────────────┘
                              数据到达 / 触摸 / 接近感应
```

**各状态行为：**

| 状态 | 背光 | CPU | WiFi | 帧率 |
|------|------|-----|------|------|
| ACTIVE | 100% | 240MHz | 活跃 | 50fps |
| DIM | 30% | 240MHz | 活跃 | 5fps |
| SLEEP | 0% | 80MHz | 省电 | 2fps |
| LIGHT_SLEEP | 0% | 睡眠 | DTIM | 唤醒 |

### 7.4 Light Sleep 深度休眠

屏幕休眠 5 分钟后进入 ESP32 Light Sleep，仅保留触摸唤醒和 WiFi beacon 唤醒：

```cpp
// main.cpp - renderTask()
if (now - g_screenSleepStart >= 300000) {  // 5 分钟
    display.sleep();

    // 配置触摸唤醒源
    esp_sleep_enable_touchpad_wakeup();

    // RTC IO 状态保持：锁定关键引脚电平，防止 Light Sleep 期间漂移
    gpio_hold_en((gpio_num_t)LCD_BL);       // 背光保持低电平
    gpio_hold_en((gpio_num_t)BUZZER_PIN);   // 蜂鸣器保持低电平 (静音)
    gpio_hold_en((gpio_num_t)LCD_CS);       // SPI 片选保持高电平 (未选中)

    esp_light_sleep_start();  // 进入 Light Sleep

    // === 唤醒 ===
    gpio_hold_dis((gpio_num_t)LCD_BL);
    gpio_hold_dis((gpio_num_t)BUZZER_PIN);
    gpio_hold_dis((gpio_num_t)LCD_CS);
    setCpuFrequencyMhz(240);
    WiFi.setSleep(false);
}
```

### 7.5 VRR 动态帧率

渲染帧率根据系统状态和 Agent 工作状态动态调整：

```cpp
// main.cpp - renderTask()
uint32_t frameDelay = 20;      // 默认 50fps

if (g_screenSleeping) {
    frameDelay = 500;           // SLEEP: 2fps
} else if (g_screenDimmed) {
    frameDelay = 1000;          // DIM: 1fps
} else if (数据静默 > 15秒) {
    frameDelay = 200;           // IDLE: 5fps
} else {
    // OTLP 联动：根据 Agent 状态微调
    if (agentStatus == STATUS_WORKING) {
        frameDelay = 16;        // Agent 工作中: 60fps (流畅思考动画)
    } else if (agentStatus == STATUS_AUTH) {
        frameDelay = 33;        // 认证/交互: 30fps
    }
}
```

---

## 八、中断与定时器

### 8.1 V-Sync TE 中断

**类型：** GPIO 外部中断 (FALLING 边沿)

**ISR：** `DisplayManager::_teIsrHandler()` (IRAM 属性)

**作用：** 与 LCD 面板帧扫描同步，消除画面撕裂

```
ST7789V2 TE 引脚 (FALLING)
    │
    ▼
GPIO ISR → s_teTriggered = true
    │
    ▼
renderTask 轮询 waitForVSync() → 检测到标志 → 允许 pushSprite()
```

### 8.2 蜂鸣器正弦波定时器中断

**类型：** 硬件定时器中断 (ESP32 Timer Group 0, Timer 0)

**频率：** 40kHz (每 25us 触发一次)

**ISR：** `sineTimerISR()` (IRAM 属性)

**作用：** 驱动正弦波 PWM 输出，实现柔和音调

```
Hardware Timer (40kHz)
    │
    ▼
sineTimerISR() → SIN_LUT[sinIdx] → ledcWrite(PWM duty)
    │
    ▼
无源蜂鸣器发声
```

### 8.3 FreeRTOS 任务调度

项目使用 FreeRTOS 双核架构，两个核心各有独立任务：

```
Core 0: commTask (优先级 2, 栈 8KB)
    ├── WiFi/TCP 通信
    ├── JSON 数据解析
    ├── 双缓冲写入
    └── BOOT 键检测

Core 1: renderTask (优先级 1, 栈 16KB)
    ├── LCD 显示更新
    ├── 动画渲染
    ├── 触摸检测
    ├── 光照传感器读取
    ├── 电源管理
    └── 温控自适应
```

**帧同步机制：** 使用 `vTaskDelay(pdMS_TO_TICKS(frameDelay))` 控制渲染帧率，非阻塞释放 CPU。

### 8.4 双核数据共享

Core 0 (通信) 和 Core 1 (渲染) 之间通过双缓冲 + 原子指针交换实现无锁数据共享：

```cpp
// main.cpp
DisplayData g_displayBuf[2];           // 双缓冲
std::atomic<int> g_frontIdx{0};        // 原子索引

// Core 0 写入:
int front = g_frontIdx.load(std::memory_order_acquire);
int backIdx = 1 - front;
g_displayBuf[backIdx] = g_displayBuf[front];  // 拷贝 front → back
g_displayBuf[backIdx].agent.status = newStatus; // 写入新数据
g_frontIdx.store(backIdx, std::memory_order_release);  // 原子交换

// Core 1 读取:
int idx = g_frontIdx.load(std::memory_order_acquire);
localData = g_displayBuf[idx];  // 直接读取，无需互斥锁
```

---

## 九、常见硬件问题排查

### 9.1 SPI 通信失败

**症状：** 屏幕无显示、花屏、白屏

**排查步骤：**

1. **检查接线：** 确认 MOSI、SCLK、CS、DC、RST 五根线正确连接
2. **降低 SPI 频率：** 将 80MHz 降至 40MHz 或 20MHz 测试
3. **检查 CS 片选：** 确认 CS 引脚在传输期间保持低电平
4. **检查 RST 复位：** 确认 RST 引脚在初始化前有一个低脉冲
5. **DMA 缓冲区对齐：** 确保帧缓冲区 4 字节对齐

**常见错误日志：**
```
SPI transfer failed
DMA timeout
```

### 9.2 I2C 地址冲突

**症状：** BH1750 或 DRV2605L 初始化失败

**排查步骤：**

1. **I2C 地址扫描：** 使用 I2C Scanner 扫描总线上所有设备
2. **检查上拉电阻：** SDA/SCL 线需要 4.7kΩ 上拉到 3.3V
3. **确认地址：** BH1750=0x23 (ADDR 接地), DRV2605L=0x5A (固定)
4. **总线冲突：** 确认两个设备地址不同，不会冲突
5. **检查供电：** 确认 3.3V 供电稳定

**I2C Scanner 代码片段：**
```cpp
for (uint8_t addr = 1; addr < 127; addr++) {
    _wire.beginTransmission(addr);
    if (_wire.endTransmission() == 0) {
        Serial.printf("Found device at 0x%02X\n", addr);
    }
}
```

### 9.3 触摸不灵敏

**症状：** 触摸无响应、误触发、需要用力按压

**排查步骤：**

1. **校准基线：** 确保初始化时环境稳定，基线值准确
2. **调整阈值：** 减小 `TOUCH_THRESHOLD` (如从 40 降到 20) 增加灵敏度
3. **检查接地：** 确保手指与 GND 有良好接触 (人体作为接地参考)
4. **环境干扰：** 远离强电磁场、金属物体
5. **引脚选择：** 确认 GPIO1 确实对应 Touch1 通道

**调试方法：**
```cpp
Serial.printf("Touch raw: %d, baseline: %d, delta: %d\n",
    touchRead(TOUCH_PIN), _baseline, _baseline - touchRead(TOUCH_PIN));
```

### 9.4 蜂鸣器无声

**症状：** 蜂鸣器不发声或声音异常

**排查步骤：**

1. **区分有源/无源：** 项目使用无源蜂鸣器，需要 PWM 信号驱动
2. **检查频率范围：** 无源蜂鸣器通常在 1-5kHz 范围内效果最佳
3. **检查 PWM 输出：** 用示波器或万用表测量 GPIO18 是否有 PWM 信号
4. **检查供电：** 确认蜂鸣器两端有足够的驱动电压
5. **检查定时器：** 确认硬件定时器正确初始化且 ISR 正常触发

**常见错误：**
- 使用有源蜂鸣器但发送 PWM 信号 (有源蜂鸣器只需高/低电平)
- 频率超出蜂鸣器响应范围 (>8kHz 或 <100Hz)

### 9.5 光照传感器读数异常

**症状：** 读数始终为 0 或 65535

**排查步骤：**

1. **检查 I2C 连接：** 确认 SDA/SCL 接线正确
2. **等待初始化延迟：** BH1750 首次测量需要 120-180ms
3. **检查传感器朝向：** 确认光敏窗口未被遮挡
4. **检查地址：** 确认 ADDR 引脚接地 (0x23)
5. **检查供电：** BH1750 工作电压 2.4-3.6V

### 9.6 触觉反馈无效果

**症状：** 触摸无振动反馈

**排查步骤：**

1. **检查 LRA 马达连接：** 确认马达正确连接到 DRV2605L 输出
2. **确认校准成功：** 检查 `calibrate()` 返回值和 Status 寄存器
3. **检查 I2C 写入：** 确认寄存器写入返回 0 (成功)
4. **测试简单效果：** 先尝试 `playEffect(1)` (Strong Click)
5. **检查马达类型：** 确认使用 LRA 马达且 Library 设置为 0x06

---

## 附录：启动初始化时序

```
setup()
    │
    ├─ Serial.begin(115200)
    ├─ 崩溃检测 (RTC_NOINIT_ATTR)
    │
    ├─ display.begin()              ← SPI + LCD 初始化
    ├─ display.setupVSync()         ← TE 中断配置
    ├─ display.showBootScreen()     ← 显示启动画面
    │
    ├─ sound.begin()                ← LEDC PWM 初始化
    ├─ sound.playStartup()          ← 开机三连音
    │
    ├─ touch.begin()                ← 触摸校准
    ├─ touch.proximity.begin()      ← 接近感应基线校准
    ├─ touch.setCallback()          ← 注册触摸事件回调
    │
    ├─ ambientLight.begin(41, 42)   ← BH1750 I2C 初始化
    ├─ hapticDriver.begin(41, 42)   ← DRV2605L I2C 初始化 + 校准
    │
    ├─ wifi.begin() + wifi.connect()← WiFi 连接
    ├─ configTime()                 ← NTP 时间同步
    ├─ comm.begin()                 ← TCP 通信初始化
    │
    ├─ xTaskCreatePinnedToCore(commTask, Core 0)   ← 通信任务
    └─ xTaskCreatePinnedToCore(renderTask, Core 1)  ← 渲染任务
```

---

> **文档版本：** v1.0
> **最后更新：** 2026-06-24
> **适用固件版本：** esp32_firmware v2 (FreeRTOS 双核架构)
