# 传感器系统详解

> 本文档涵盖桌面电子宠物 ESP32-S3 固件中的四类传感器/外设子系统：环境光传感器(BH1750)、
> 电容触摸+接近感应、触觉反馈驱动(DRV2605L)、蜂鸣器音频管理器，以及它们与 FreeRTOS
> 渲染任务的集成方式。

---

## 一、AmbientLightManager (BH1750 环境光传感器)

### 1.1 硬件概述

| 参数 | 值 |
|------|-----|
| 芯片 | BH1750FVI (GY-302 模块) |
| 协议 | I2C，地址 `0x23` (ADDR 接 GND) |
| 分辨率 | 1 lx (连续高分辨率模式) |
| 量程 | 1 ~ 65535 lx |
| 接线 | SDA=GPIO41, SCL=GPIO42, VCC=3.3V |

### 1.2 I2C 初始化流程

初始化在 `AmbientLightManager::begin()` 中完成，按以下步骤执行：

```cpp
bool AmbientLightManager::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);           // 1. 启动 I2C 总线

    // 2. 检测传感器是否存在
    _wire.beginTransmission(BH1750_ADDR);
    if (_wire.endTransmission() != 0) {
        _available = false;
        return false;                       // 设备无应答
    }

    // 3. 上电指令
    _writeCommand(BH1750_POWER_ON);         // 0x01
    delay(10);

    // 4. 设置连续高分辨率模式
    _writeCommand(BH1750_CONT_HRES);        // 0x10
    delay(180);                             // 首次测量需要 120~180ms

    _available = true;
    return true;
}
```

**BH1750 指令集：**

| 指令 | 字节 | 说明 |
|------|------|------|
| `BH1750_POWER_ON`  | `0x01` | 上电 |
| `BH1750_RESET`     | `0x07` | 重置（仅在连续模式下有效） |
| `BH1750_CONT_HRES` | `0x10` | 连续高分辨率模式 (1 lx, 120ms) |
| `BH1750_CONT_LRES` | `0x13` | 连续低分辨率模式 (4 lx, 16ms, 快速) |
| `BH1750_ONE_HRES`  | `0x20` | 单次高分辨率模式（测量后自动断电） |

### 1.3 数据读取与 lux 换算

BH1750 高分辨率模式下，原始值需除以 1.2 才得到 lux：

```cpp
int16_t AmbientLightManager::readLux() {
    if (!_available) return -1;

    _wire.requestFrom((uint8_t)BH1750_ADDR, (uint8_t)2);
    if (_wire.available() < 2) return -1;

    uint16_t raw = (_wire.read() << 8) | _wire.read();   // 高字节在前

    int16_t rawLux = (int16_t)(raw / 1.2f);               // BH1750 datasheet 公式
    if (rawLux < 0) rawLux = 0;

    // EMA 滤波
    _emaLux = EMA_ALPHA * rawLux + (1.0f - EMA_ALPHA) * _emaLux;
    _lastLux = (int16_t)_emaLux;
    return _lastLux;
}
```

### 1.4 EMA 滤波 (指数移动平均)

为消除环境光快速波动（如云层遮挡、灯光闪烁），采用一阶 EMA 低通滤波：

```
filtered = alpha * raw + (1 - alpha) * filtered_old
```

| 参数 | 值 | 含义 |
|------|-----|------|
| `EMA_ALPHA` | `0.15` | 平滑系数。越小滤波越强，响应越慢 |

- `alpha=0.15` 意味着新样本只占 15% 权重，历史值占 85%
- 适合背光调节场景：避免屏幕亮度随光线频繁跳变

### 1.5 CIE 1931 感知亮度曲线映射

人眼对亮度的感知是非线性的（Weber-Fechner 定律）。直接用 lux 线性映射 PWM 会导致
低光照下背光过暗、高光照下变化不明显。因此采用 CIE 1931 感知亮度公式：

```cpp
static float cie1931_curve(float Y) {
    if (Y <= 0.008856f) {
        return 903.3f * Y;                              // 线性区
    } else {
        return 116.0f * powf(Y, 1.0f/3.0f) - 16.0f;    // 立方根区
    }
}
```

**背光映射流程：**

```
lux (0~10000) --> 归一化 (0.0~1.0) --> CIE 1931 曲线 --> PWM (15~255)
```

```cpp
uint8_t AmbientLightManager::autoAdjustBacklight(int16_t lux) {
    if (lux < 0) return 128;    // 读取失败时给中等亮度

    const int16_t MAX_LUX = 10000;
    if (lux > MAX_LUX) lux = MAX_LUX;

    float normalized = (float)lux / (float)MAX_LUX;    // 0.0 ~ 1.0
    float perceived = cie1931_curve(normalized) / 100.0f;

    const uint8_t MIN_PWM = 15;   // 约 6% 亮度，确保屏幕在黑暗中仍可见
    const uint8_t MAX_PWM = 255;

    return MIN_PWM + (uint8_t)(perceived * (MAX_PWM - MIN_PWM));
}
```

**关键设计决策：**
- `MIN_PWM = 15`：防止完全黑暗时屏幕关闭，用户始终能看到内容
- `MAX_LUX = 10000`：超过此值的光照视为"极亮"，背光全开
- 读取失败时返回 128（中等亮度），避免黑屏

### 1.6 功耗管理

支持 Power Down 指令以降低待机功耗（BH1750 典型待机功耗约 0.01mA）：

```cpp
void AmbientLightManager::powerDown() {
    _writeCommand(0x00);    // Power Down 指令
}

void AmbientLightManager::powerUp() {
    _writeCommand(BH1750_POWER_ON);     // 重新上电
    delay(10);
    _writeCommand(BH1750_CONT_HRES);    // 恢复连续高分辨率模式
    delay(180);                         // 等待首次测量完成
}
```

---

## 二、TouchHandler (电容触摸 + 接近感应)

### 2.1 硬件概述

| 参数 | 值 |
|------|-----|
| 引脚 | GPIO1 (Touch1)，ESP32-S3 内置电容触摸 |
| 校准方式 | 20 次采样取平均基线 |
| 默认阈值 | 40 (相对基线的差值) |
| 长按阈值 | 1000 ms |

### 2.2 基线校准

上电时进行 20 次采样取平均值作为"无人触摸"的基线：

```cpp
void TouchHandler::calibrate() {
    uint32_t sum = 0;
    for (int i = 0; i < 20; i++) {
        sum += touchRead(TOUCH_PIN);
        delay(10);      // 每次间隔 10ms
    }
    _baseline = sum / 20;
}
```

触摸检测逻辑：`touchRead(TOUCH_PIN) < (baseline - threshold)` 时判定为"按下"。
ESP32-S3 的电容触摸值在手指接近时会**下降**（与 ESP32 经典款相反），因此使用基线减法。

### 2.3 手势状态机

手势识别基于 IDLE -> PRESSED -> RELEASED 三状态有限状态机：

```
         touchRead < threshold
    IDLE ─────────────────────────> PRESSED
     ^                                  │
     │  touchRead >= threshold          │
     └──────────────────────────────────┘
                                         │
              touchRead >= threshold     │
              (手指释放)                  │
         IDLE <─────────────────── RELEASED
              (判定手势类型)
```

**判定规则：**

| 手势 | 条件 | 回调事件 |
|------|------|----------|
| 单击 | 按下时长 < 400ms，400ms 内无第二次按下 | `TOUCH_SINGLE_TAP` |
| 双击 | 400ms 内完成两次短按 | `TOUCH_DOUBLE_TAP` |
| 长按 | 按下时长 >= 1000ms | `TOUCH_LONG_PRESS` |

**核心状态机代码：**

```cpp
void TouchHandler::update() {
    if (!_initialized) return;

    // 接近感应独立检测
    if (proximity.update()) {
        if (_callback) _callback(TOUCH_PROXIMITY);
    }

    uint16_t val = touchRead(TOUCH_PIN);
    bool touched = (val < (_baseline - _threshold));
    unsigned long now = millis();

    if (touched && !_wasTouched) {
        // ---- 按下边缘 ----
        _touchStart = now;
        _wasTouched = true;
    }
    else if (!touched && _wasTouched) {
        // ---- 释放边缘 ----
        _wasTouched = false;
        unsigned long duration = now - _touchStart;

        if (duration >= TOUCH_LONG_PRESS_MS) {
            // 长按：立即触发，重置计数
            _lastEvent = TOUCH_LONG_PRESS;
            _tapCount = 0;
            if (_callback) _callback(TOUCH_LONG_PRESS);
        } else {
            // 短按：累加点击计数
            if (now - _lastTapTime < 400) {
                _tapCount++;        // 400ms 内连击
            } else {
                _tapCount = 1;      // 超时，重新计数
            }
            _lastTapTime = now;
        }
    }

    // 双击超时检测：400ms 无新点击则判定
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

### 2.4 接近感应 (ProximitySensor)

接近感应复用同一个触摸引脚，通过双 EMA（快慢线）差分算法检测手指接近但未接触的状态。

**算法原理：**

```
快速 EMA (alpha=0.3) --> 跟踪即时值，响应快
慢速 EMA (alpha=0.05) --> 跟踪基线，响应慢
差值 diff = slowEMA - fastEMA

手指接近时 touchRead 值下降 --> fastEMA 下降更快 --> diff 增大
当 diff > RISING_THRESHOLD --> 判定为"接近"
```

**参数配置（config.h）：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `PROX_EMA_FAST_ALPHA` | `0.3` | 快速 EMA 系数，响应迅速 |
| `PROX_EMA_SLOW_ALPHA` | `0.05` | 慢速 EMA 系数，跟踪基线 |
| `PROX_RISING_THRESHOLD` | `8` | 上升差分阈值（接近检测） |
| `PROX_FALLING_THRESHOLD` | `4` | 下降差分阈值（远离检测） |
| `PROX_COOLDOWN_MS` | `2000` | 接近事件冷却时间 (ms) |
| `PROX_WAKE_DURATION_MS` | `15000` | 接近唤醒后亮屏持续时长 (ms) |

**接近检测核心逻辑：**

```cpp
bool ProximitySensor::update() {
    if (!_initialized) return false;

    uint16_t raw = touchRead(TOUCH_PIN);

    // 双 EMA 更新
    _fastEMA = 0.3f * raw + 0.7f * _fastEMA;
    _slowEMA = 0.05f * raw + 0.95f * _slowEMA;

    float diff = _slowEMA - _fastEMA;
    unsigned long now = millis();

    if (!_isNear) {
        // 等待上升沿（手指接近）
        if (diff > PROX_RISING_THRESHOLD) {   // threshold = 8
            _isNear = true;
            _lastNearTime = now;
            if (now - _lastEventTime > PROX_COOLDOWN_MS) {  // cooldown = 2s
                _lastEventTime = now;
                return true;    // 触发接近事件
            }
        }
    } else {
        // 等待下降沿（手指远离）
        if (diff < PROX_FALLING_THRESHOLD) {  // threshold = 4
            _isNear = false;
        }
        _lastNearTime = now;   // 持续接近时不断刷新时间戳
    }
    return false;
}
```

**唤醒保持逻辑：**

```cpp
bool TouchHandler::isProximityWakeActive() const {
    return proximity.isNear() ||
           (millis() - proximity.getLastNearTime() < PROX_WAKE_DURATION_MS);
}
```

即使手指已远离，只要最后接近时间在 15 秒内，仍认为"唤醒有效"。

---

## 三、HapticDriver (DRV2605L 触觉反馈)

### 3.1 硬件概述

| 参数 | 值 |
|------|-----|
| 芯片 | TI DRV2605L |
| 协议 | I2C，地址 `0x5A` |
| 支持马达 | LRA (线性谐振致动器) + ERM (偏心旋转质量) |
| 内置效果 | 123 种预设波形 (Library 6: LRA 优化) |
| 接线 | 与 BH1750 共享 I2C 总线 (GPIO41/42) |

### 3.2 DRV2605L 寄存器映射

| 寄存器 | 地址 | 读/写 | 说明 |
|--------|------|-------|------|
| STATUS | `0x00` | R | 设备状态 (校准结果) |
| MODE | `0x01` | R/W | 播放模式选择 |
| RTPIN | `0x02` | R/W | 实时播放输入值 |
| LIBRARY | `0x03` | R/W | 波形库选择 (1~6) |
| WAVESEQ1 | `0x04` | R/W | 波形序列槽 1 |
| WAVESEQ2 | `0x05` | R/W | 波形序列槽 2 |
| WAVESEQ3 | `0x06` | R/W | 波形序列槽 3 |
| WAVESEQ4 | `0x07` | R/W | 波形序列槽 4 |
| WAVESEQ5 | `0x08` | R/W | 波形序列槽 5 |
| WAVESEQ6 | `0x09` | R/W | 波形序列槽 6 |
| WAVESEQ7 | `0x0A` | R/W | 波形序列槽 7 |
| WAVESEQ8 | `0x0B` | R/W | 波形序列槽 8 (最后一个) |
| GO | `0x0C` | R/W | 触发播放 (写1启动, 自动清零) |
| RATEDVOL | `0x16` | R/W | 额定电压 (LRA 校准用) |
| ODCLAMP | `0x17` | R/W | 过驱动钳位电压 |
| FEEDBACK | `0x1A` | R/W | 反馈控制 (LRA/ERM 选择) |
| CONTROL1 | `0x1B` | R/W | 控制寄存器 1 (采样/驱动时间) |
| CONTROL2 | `0x1C` | R/W | 控制寄存器 2 (制动/空闲) |
| CONTROL3 | `0x1D` | R/W | 控制寄存器 3 (噪声门/软制动) |

**MODE 寄存器值：**

| 值 | 模式 | 说明 |
|----|------|------|
| `0x00` | Internal Trigger | 软件触发 (写 GO=1 启动) |
| `0x01` | External Trigger | GPIO 引脚触发 |
| `0x02` | Real-time Playback | PWM/模拟输入实时驱动 |
| `0x03` | Diagnostics | 诊断模式 |
| `0x05` | Waveform Sequencer | 波形序列模式 (最多 8 槽) |
| `0x07` | Auto Calibrate | 自动校准模式 |

### 3.3 初始化流程

```cpp
bool HapticDriver::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);

    // 1. I2C 设备检测
    _wire.beginTransmission(DRV2605_ADDR);
    if (_wire.endTransmission() != 0) {
        _available = false;
        return false;
    }

    // 2. 设置内部触发模式
    _writeRegister(REG_MODE, 0x00);

    // 3. 选择波形库 (Library 6 = LRA 优化)
    _writeRegister(REG_LIBRARY, 0x06);

    // 4. 反馈控制: LRA 模式 + 带宽中等
    _writeRegister(REG_FEEDBACK, 0xA0);    // bit7=1(LRA), bit[6:4]=带宽

    // 5. Control1: 采样时间 4x, 驱动时间 36us
    _writeRegister(REG_CONTROL1, 0x93);

    // 6. Control2: 双向制动 + 空闲时间 0
    _writeRegister(REG_CONTROL2, 0xF5);

    // 7. Control3: 电动制动 + 噪声门 + 软制动
    _writeRegister(REG_CONTROL3, 0xA0);

    _available = true;

    // 8. 自动校准 LRA 参数
    calibrate();

    // 9. 校准后重新配置工作模式
    _writeRegister(REG_MODE, 0x00);
    _writeRegister(REG_LIBRARY, 0x06);
    _writeRegister(REG_CONTROL1, 0x93);
    _writeRegister(REG_CONTROL2, 0xF5);
    _writeRegister(REG_CONTROL3, 0xA0);

    return true;
}
```

### 3.4 自动校准流程

DRV2605L 内置自动校准功能，通过测量马达的 Back-EMF 来优化驱动参数：

```cpp
bool HapticDriver::calibrate() {
    if (!_available) return false;

    // Step 1: 待机模式
    _writeRegister(REG_MODE, 0x00);
    delay(10);

    // Step 2: 设置 LRA 参数
    // 额定电压: 1.8V RMS
    // RatedVoltage = V_rms * 255 / 5.36V = 1.8 * 255 / 5.36 ≈ 85 (0x55)
    _writeRegister(REG_RATEDVOL, 0x55);

    // 过驱动钳位: 2.5V peak
    // ODClamp = V_peak * 255 / 5.6V = 2.5 * 255 / 5.6 ≈ 114 (0x72)
    _writeRegister(REG_ODCLAMP, 0x72);

    // Step 3: Feedback 寄存器 (LRA + back-EMF)
    _writeRegister(REG_FEEDBACK, 0xA0);

    // Step 4: Control2 默认参数
    _writeRegister(REG_CONTROL2, 0xF5);

    // Step 5: 进入自动校准模式
    _writeRegister(REG_MODE, 0x07);

    // Step 6: 触发校准
    _writeRegister(REG_GO, 0x01);

    // Step 7: 轮询等待 (最多 1.5s)
    unsigned long start = millis();
    while (millis() - start < 1500) {
        uint8_t go;
        if (!_readRegisterSafe(REG_GO, go)) {
            _available = false;
            return false;       // I2C 通信失败
        }
        if ((go & 0x01) == 0) {
            // GO 位自动清零 = 校准完成
            uint8_t diag;
            _readRegisterSafe(REG_STATUS, diag);
            _available = (diag == 0x00);   // STATUS=0 表示校准成功
            return _available;
        }
        delay(50);
    }

    _available = false;     // 超时
    return false;
}
```

**校准电压换算公式：**

| 参数 | 公式 | 示例 |
|------|------|------|
| RatedVoltage | `V_rms * 255 / 5.36V` | 1.8V -> `0x55` (85) |
| ODClamp | `V_peak * 255 / 5.6V` | 2.5V -> `0x72` (114) |

### 3.5 预设效果

| 效果 | ID | 快捷方法 | 用途 |
|------|----|----------|------|
| 轻击 | `1` | `click()` | 触摸确认反馈 |
| 软触 | `3` | `softTouch()` | 滑动反馈 |
| 持续嗡嗡 | `47` | `buzz()` | 通知提醒 |
| 强击 | `72` | `strongHit()` | 警告/长按 |
| 渐强 | `12` | `playEffect(12)` | 渐变效果 |

**单效果播放：**

```cpp
void HapticDriver::playEffect(uint8_t effectId) {
    if (!_available) return;
    _writeRegister(REG_MODE, MODE_INTERNAL);    // 0x00: 内部触发
    _writeRegister(REG_WAVESEQ1, effectId);     // 槽 0 = 效果 ID
    _writeRegister(REG_WAVESEQ2, 0x00);         // 槽 1 = 终止标记
    _writeRegister(REG_GO, 0x01);               // 触发播放
}
```

### 3.6 波形序列播放

DRV2605L 支持最多 8 个槽位的波形序列，按顺序播放，槽值为 0 表示终止：

```cpp
void HapticDriver::playWaveform(const uint8_t* sequence, uint8_t count) {
    if (!_available || count == 0) return;
    if (count > 8) count = 8;

    _writeRegister(REG_MODE, MODE_SEQUENCE);    // 0x05: 波形序列模式

    for (uint8_t i = 0; i < count; i++) {
        _writeRegister(REG_WAVESEQ1 + i, sequence[i]);
    }
    if (count < 8) {
        _writeRegister(REG_WAVESEQ1 + count, 0x00);  // 终止标记
    }

    _writeRegister(REG_GO, 0x01);               // 触发播放
}
```

**序列示例：** `{1, 50, 1, 0}` = 轻击 -> 延迟 -> 轻击 -> 结束

---

## 四、SoundManager (蜂鸣器音频)

### 4.1 硬件概述

| 参数 | 值 |
|------|-----|
| 引脚 | BUZZER_PIN (config.h 定义) |
| 类型 | 压电蜂鸣器 (无源) |
| PWM 载波 | 40 kHz (不可闻，适合压电蜂鸣器) |
| 正弦波 | 64 点查找表, DDS 合成 |
| I2S-PDM | 44.1 kHz, 8-bit, 单声道 (ESP32-S3 专用) |

### 4.2 PWM 方波后端

最简单的蜂鸣方式，直接通过 LEDC PWM 产生方波：

```cpp
void SoundManager::begin() {
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    // Arduino-ESP32 v3.x: 统一 API
    ledcAttach(BUZZER_PIN, 2000, 8);    // pin, freq, resolution
#else
    // Arduino-ESP32 v2.x: 分离 API
    ledcSetup(0, 2000, 8);             // channel, freq, resolution
    ledcAttachPin(BUZZER_PIN, 0);      // pin, channel
#endif
}

void SoundManager::beep(uint16_t freq, uint16_t duration) {
    ledcWriteTone(BUZZER_PIN, freq);    // 输出方波
    delay(duration);
    ledcWrite(BUZZER_PIN, 0);           // 停止
}
```

方波含有丰富的奇次谐波，声音尖锐刺耳，适合警报类音效。

### 4.3 正弦波 DDS 合成 (PWM 后端)

为实现柔和的"苹果级"听感，使用 DDS (Direct Digital Synthesis) 技术通过 40kHz
PWM 载波合成正弦波。

**SIN_LUT (64 点正弦查找表)：**

```cpp
// sin_lut.h
static const uint8_t SIN_LUT[64] = {
    128, 140, 152, 164, 176, 186, 196, 204,
    212, 218, 224, 228, 231, 233, 234, 233,
    231, 228, 224, 218, 212, 204, 196, 186,
    176, 164, 152, 140, 128, 116, 104,  92,
     80,  70,  60,  52,  44,  38,  32,  28,
     25,  23,  22,  23,  25,  28,  32,  38,
     44,  52,  60,  70,  80,  92, 104, 116,
    128, 140, 152, 164, 176, 186, 196, 204
};
#define SIN_LUT_SIZE    64
#define PWM_CARRIER_HZ  40000   // 40kHz 载波
```

**DDS 原理：**

```
步进值 step = freq * LUT_SIZE * STEP_SCALE / PWM_CARRIER_HZ

每个 PWM tick (40kHz):
    累加器 += step
    如果累加器 >= STEP_SCALE:
        LUT 索引 += 1 (循环)
    输出 SIN_LUT[索引] 作为 PWM 占空比
```

**硬件定时器 ISR (40kHz)：**

```cpp
static volatile uint8_t  s_sinIdx = 0;       // LUT 索引
static volatile uint16_t s_stepAcc = 0;      // DDS 累加器
static volatile uint16_t s_stepPerTick = 0;  // 每 tick 步进值

#define STEP_FRAC_BITS  10
#define STEP_SCALE      (1 << STEP_FRAC_BITS)  // 1024 (定点数精度)

static void IRAM_ATTR sineTimerISR(void* arg) {
    (void)arg;
    uint16_t step = s_stepPerTick;
    if (step == 0) return;

    s_stepAcc += step;
    if (s_stepAcc >= STEP_SCALE) {
        s_stepAcc -= STEP_SCALE;
        s_sinIdx = (s_sinIdx + 1) & 63;     // % 64，取模用位运算
    }
    s_pwmDuty = SIN_LUT[s_sinIdx];
    ledcWrite(BUZZER_PIN, s_pwmDuty);       // 更新 PWM 占空比
}
```

**步进值计算：**

```cpp
// 目标: 生成 freq Hz 的正弦波
// PWM 载波: 40000 Hz (每秒 40000 次 ISR)
// 每个正弦周期需要遍历 64 个 LUT 样本
s_stepPerTick = (uint32_t)freq * SIN_LUT_SIZE * STEP_SCALE / PWM_CARRIER_HZ;
// 例如 freq=1000Hz: step = 1000 * 64 * 1024 / 40000 = 1638
```

**频率范围：** 100 ~ 8000 Hz。超出范围时回退到方波 `beep()`。

### 4.4 I2S-PDM 后端 (ESP32-S3 专用)

ESP32-S3 支持 PDM (Pulse Density Modulation) 输出，提供更高保真度的音频。

**初始化（兼容 ESP-IDF v4.x 和 v5.x）：**

```cpp
// ESP-IDF v5.x / Arduino-ESP32 v3.x 新 API
void SoundManager::_initI2S() {
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 4;
    chan_cfg.dma_frame_num = 256;

    i2s_new_channel(&chan_cfg, &s_i2sTxChan, nullptr);

    i2s_pdm_tx_config_t pdm_cfg = {};
    pdm_cfg.clk_cfg = I2S_PDM_TX_CLK_DEFAULT_CONFIG(44100);
    pdm_cfg.slot_cfg = I2S_PDM_TX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_8BIT,
                                                       I2S_SLOT_MODE_MONO);
    pdm_cfg.gpio_cfg.dout = (gpio_num_t)BUZZER_PIN;

    i2s_channel_init_pdm_tx_mode(s_i2sTxChan, &pdm_cfg);
    i2s_channel_enable(s_i2sTxChan);
}
```

**I2S 正弦波 + ADSR 包络：**

```cpp
void SoundManager::_i2sTone(uint16_t freq, uint16_t duration) {
    // 生成正弦波基础缓冲区
    const int samplesPerCycle = 44100 / freq;
    const int bufLen = (samplesPerCycle > 256) ? 256 : samplesPerCycle;
    uint8_t baseBuf[256];

    for (int i = 0; i < bufLen; i++) {
        float angle = 2.0f * 3.14159f * i / bufLen;
        baseBuf[i] = (uint8_t)(128 + 120 * sinf(angle));   // 8-bit 中心值 128
    }

    // ADSR 参数
    uint16_t attackMs  = 8;     // 淡入 (消除启动爆音)
    uint16_t decayMs   = 0;     // 无衰减
    uint16_t releaseMs = 15;    // 淡出 (消除断尾爆音)

    // 短音保护: attack + release 不超过 duration 的 20%
    uint16_t envelopeBudget = (duration * 20) / 100;
    // ... 动态缩放 attackMs / releaseMs ...

    unsigned long endTime = millis() + duration;
    unsigned long releaseStart = endTime - releaseMs;

    while (millis() < endTime) {
        float gain = 1.0f;
        // Attack 阶段: 线性淡入
        if (t - now < attackMs) {
            gain = (float)(t - now) / (float)attackMs;
        }
        // Release 阶段: 线性淡出
        else if (t >= releaseStart) {
            gain = (float)(endTime - t) / (float)releaseMs;
        }

        // 应用包络后写入 I2S
        for (int i = 0; i < bufLen; i++) {
            envBuf[i] = (uint8_t)(128 + (int8_t)((baseBuf[i] - 128) * gain));
        }
        i2s_write(I2S_NUM_0, envBuf, bufLen, &bytesWritten, portMAX_DELAY);
    }
}
```

### 4.5 复合音效

系统预定义了多种复合音效，通过组合多段正弦波实现：

| 音效 | 方法 | 序列 | 总阻塞时长 |
|------|------|------|------------|
| 开机 | `playStartup()` | C5(1000Hz) -> E5(1500Hz) -> G5(2000Hz) | ~440ms |
| 通知 | `playNotification()` | 双短音 (2500Hz x 2) | ~160ms |
| 警告 | `playAlert()` | 三连短音 (1500Hz x 3) | ~650ms |
| OTA 进度 | `playOtaProgress()` | 单短音 (1800Hz) | ~30ms |
| OTA 成功 | `playOtaSuccess()` | 上行三音 (1000->1500->2000Hz) | ~600ms |
| OTA 失败 | `playOtaFail()` | 三连低音 (800Hz x 3) | ~900ms |

```cpp
// 开机音效: 上行 C-E-G 和弦
void SoundManager::playStartup() {
    beepSine(1000, 80);     // C5
    delay(80);
    beepSine(1500, 80);     // E5
    delay(80);
    beepSine(2000, 120);    // G5 (稍长)
}

// 通知音效: 双短音
void SoundManager::playNotification() {
    beepSine(2500, 60);
    delay(40);
    beepSine(2500, 60);
}
```

### 4.6 Arduino-ESP32 v2.x 与 v3.x 兼容性

ESP32 Arduino 核心 v3.x 对 LEDC 和 Timer API 进行了重大重构。SoundManager 通过
条件编译宏实现双版本兼容：

| 功能 | v2.x API | v3.x API |
|------|----------|----------|
| LEDC 初始化 | `ledcSetup(ch, freq, res)` + `ledcAttachPin(pin, ch)` | `ledcAttach(pin, freq, res)` |
| LEDC 写入 | `ledcWrite(ch, duty)` | `ledcWrite(pin, duty)` |
| 音调输出 | `ledcWriteTone(ch, freq)` | `ledcWriteTone(pin, freq)` |
| 定时器创建 | `timer_init()` + `timer_isr_register()` | `timerBegin(freq)` + `timerAttachInterrupt()` |
| 定时器启动 | `timer_start()` | `timerStart()` |
| 定时器停止 | `timer_pause()` | `timerStop()` |

---

## 五、传感器与渲染任务集成

### 5.1 FreeRTOS 双核架构

系统运行两个 FreeRTOS 任务：

| 任务 | 核心 | 职责 |
|------|------|------|
| `commTask` | Core 0 | WiFi/TCP 通信、JSON 解析、数据接收 |
| `renderTask` | Core 1 | 显示更新、动画渲染、传感器轮询、休眠管理 |

传感器读取全部在 `renderTask` (Core 1) 中完成，避免多线程竞争。

### 5.2 传感器在 renderTask 中的集成

```
renderTask 主循环:
    |
    +-- touch.update()                     // 触摸+接近感应
    |       |
    |       +-- proximity.update()         // 接近检测
    |       +-- 手势状态机                  // 单击/双击/长按
    |
    +-- ambientLight.readLux()             // 每 2 秒读取一次
    |       |
    |       +-- autoAdjustBacklight(lux)   // CIE 1931 映射
    |       +-- display.setBrightness(pwm) // 设置背光
    |
    +-- touch.proximity.isNear()           // 接近唤醒判断
    |       |
    |       +-- isProximityWakeActive()    // 15s 保持亮屏
    |
    +-- 动画帧更新
    +-- 休眠/唤醒状态管理
```

### 5.3 触摸回调与多传感器联动

触摸事件通过回调函数同时触发声音和触觉反馈：

```cpp
touch.begin();
touch.proximity.begin();

touch.setCallback([](TouchEvent e) {
    switch (e) {
        case TOUCH_SINGLE_TAP:
            sound.playNotification();   // 播放通知音
            hapticDriver.click();       // 触觉: 轻击
            break;
        case TOUCH_DOUBLE_TAP:
            sound.playNotification();
            hapticDriver.buzz();        // 触觉: 嗡嗡
            break;
        case TOUCH_LONG_PRESS:
            sound.playAlert();          // 播放警告音
            hapticDriver.strongHit();   // 触觉: 强击
            break;
        case TOUCH_PROXIMITY:
            // 接近事件: 仅触发唤醒，无声音/触觉
            break;
    }
});
```

### 5.4 接近唤醒流程

```
用户手指接近 (未触摸)
        |
        v
ProximitySensor: diff > 8 (RISING_THRESHOLD)
        |
        v
isProximityWakeActive() = true
        |
        v
屏幕从休眠状态唤醒 (亮度由 ambientLight 自动调节)
        |
        v
手指远离后: 最后接近时间记录在 _lastNearTime
        |
        v
15 秒 (PROX_WAKE_DURATION_MS) 内无新接近事件
        |
        v
isProximityWakeActive() = false
        |
        v
屏幕重新进入休眠
```

### 5.5 I2C 总线共享

BH1750 (0x23) 和 DRV2605L (0x5A) 共享同一条 I2C 总线 (GPIO41/42)。
两者各自持有独立的 `TwoWire` 实例（均使用总线 0），通过 I2C 地址区分。
ESP32 的 Wire 库内部有互斥锁保护，不会产生总线冲突。

---

## 附录：关键配置参数汇总

### 环境光传感器

| 参数 | 值 | 定义位置 |
|------|-----|----------|
| `BH1750_ADDR` | `0x23` | `ambient_light.h` |
| `EMA_ALPHA` | `0.15` | `ambient_light.h` |
| `MIN_PWM` | `15` | `ambient_light.cpp` |
| `MAX_LUX` | `10000` | `ambient_light.cpp` |

### 触摸与接近感应

| 参数 | 值 | 定义位置 |
|------|-----|----------|
| `TOUCH_PIN` | `GPIO1` | `config.h` |
| `TOUCH_THRESHOLD` | `40` | `config.h` |
| `TOUCH_LONG_PRESS_MS` | `1000` | `config.h` |
| `PROX_EMA_FAST_ALPHA` | `0.3` | `config.h` |
| `PROX_EMA_SLOW_ALPHA` | `0.05` | `config.h` |
| `PROX_RISING_THRESHOLD` | `8` | `config.h` |
| `PROX_FALLING_THRESHOLD` | `4` | `config.h` |
| `PROX_COOLDOWN_MS` | `2000` | `config.h` |
| `PROX_WAKE_DURATION_MS` | `15000` | `config.h` |

### 触觉反馈

| 参数 | 值 | 定义位置 |
|------|-----|----------|
| `DRV2605_ADDR` | `0x5A` | `haptic_driver.h` |
| `RatedVoltage` | `0x55` (1.8V RMS) | `haptic_driver.cpp` |
| `ODClamp` | `0x72` (2.5V peak) | `haptic_driver.cpp` |
| 校准超时 | `1500ms` | `haptic_driver.cpp` |

### 音频系统

| 参数 | 值 | 定义位置 |
|------|-----|----------|
| `PWM_CARRIER_HZ` | `40000` | `sin_lut.h` |
| `SIN_LUT_SIZE` | `64` | `sin_lut.h` |
| `STEP_FRAC_BITS` | `10` | `sound_manager.cpp` |
| I2S 采样率 | `44100` Hz | `sound_manager.cpp` |
| I2S 位深 | `8-bit` | `sound_manager.cpp` |
| I2S DMA 缓冲 | `4 x 256` | `sound_manager.cpp` |
