# 显示引擎系统

> 本文档描述 ESP32-S3 桌面宠物项目的完整显示渲染管线，涵盖 LovyanGFX 驱动框架、
> Sprite 双缓冲渲染、脏矩形优化、表情动画、弹簧数值动画、思考链历史展示、夜间色温、
> 平滑背光、模式切换淡入淡出、V-Sync 同步及底层代码优化技巧。

---

## 目录

1. [LovyanGFX 框架概述](#1-lovyanGFX-框架概述)
2. [DisplayManager 类结构](#2-displaymanager-类结构)
3. [Sprite 双缓冲渲染流程](#3-sprite-双缓冲渲染流程)
4. [脏矩形优化](#4-脏矩形优化)
5. [表情系统（4 种 x 4 帧）](#5-表情系统4-种-x-4-帧)
6. [天气图标系统（11 种）](#6-天气图标系统11-种)
7. [弹簧动画系统](#7-弹簧动画系统)
8. [思考链历史展示（PSRAM 链表 + 缓动滚动）](#8-思考链历史展示psram-链表--缓动滚动)
9. [夜间色温模式（RGB565 矩阵）](#9-夜间色温模式rgb565-矩阵)
10. [平滑背光（EMA 滤波）](#10-平滑背光ema-滤波)
11. [模式切换淡入淡出（alpha 混合）](#11-模式切换淡入淡出alpha-混合)
12. [V-Sync 同步](#12-v-sync-同步)
13. [代码优化技巧](#13-代码优化技巧)

---

## 1. LovyanGFX 框架概述

### 1.1 为什么选择 LovyanGFX

LovyanGFX 是 ESP32 生态中最成熟的图形驱动库之一，相比原版 Adafruit_GFX 和
TFT_eSPI，它提供了以下关键优势：

- **DMA 传输**：SPI 数据通过 DMA 通道发送，CPU 在传输期间可执行其他任务
- **Sprite 缓冲**：内置 `LGFX_Sprite` 类，支持内存中帧缓冲与脏区域追踪
- **硬件抽象**：统一 API 覆盖 SPI / I2C / 并行接口的多种 LCD 驱动芯片
- **字体内置**：支持 TrueType 矢量字体和像素字体的混合渲染

### 1.2 LGFX 硬件配置

项目中定义的 `LGFX` 类继承自 `lgfx::LGFX_Device`，针对 240x240 ST7789V LCD
进行了精确的硬件参数配置：

```
接口:      SPI2_HOST
时钟频率:  80 MHz
DMA:       启用（自动分配通道）
背光:      GPIO48, PWM 通道 7

引脚分配:
  CS   -> GPIO 5
  DC   -> GPIO 2
  RST  -> GPIO 4
  MOSI -> GPIO 11
  SCLK -> GPIO 12
  MISO -> GPIO 13

面板配置:
  宽度:        240 px
  高度:        240 px
  驱动芯片:    ST7789V
  色彩格式:    RGB565 (16-bit)
  偏移:        根据屏幕版本调整（部分 ST7789V 需要 X/Y 偏移）
```

### 1.3 ST7789V 驱动特性

ST7789V 是一颗 240x320 分辨率的 TFT 驱动 IC，但本项目使用 240x240 的物理面板，
因此存在以下注意事项：

- **行列偏移**：部分面板模块的显示区域不在 (0,0) 起始，需要设置 `setOffset()` 补偿
- **色彩反转**：某些模块默认色彩为反转显示，需要发送 `INVON` 指令修正
- **刷新率**：80MHz SPI 时钟下，240x240x16bit 的完整帧传输耗时约 1.4ms（不含 TE 等待）

### 1.4 PWM 背光控制

背光通过 LEDC PWM 实现精细亮度调节：

- **PWM 通道**: 7（LEDC 高速通道）
- **频率**: 默认 5kHz（避免可闻噪声）
- **分辨率**: 8-bit（0-255 级亮度）
- **GPIO**: 48（部分板载可能需要反转极性）

---

## 2. DisplayManager 类结构

### 2.1 核心职责

`DisplayManager` 是显示子系统的总控制器，约 1370 行代码，负责：

- LCD 初始化与硬件配置
- 帧缓冲管理（主 Sprite + 过渡 Sprite）
- 所有 UI 面板的渲染调度
- 表情动画状态机
- 数值动画（弹簧物理）
- 色温与背光管理
- 显示模式切换（正常模式 / 像素模式）

### 2.2 成员变量

```
核心对象:
  _lcd             LGFX          硬件驱动实例
  _sprite          LGFX_Sprite   240x240 主帧缓冲
  _transitionSprite LGFX_Sprite  用于模式切换的过渡缓冲

动画系统:
  _tempSpring      SpringAnimation   温度数值弹簧动画
  _tokenSpring     SpringAnimation   Token 用量弹簧动画
  _cpuSpring       SpringAnimation   CPU 使用率弹簧动画
  _memorySpring    SpringAnimation   内存使用率弹簧动画

表情状态:
  _currentFace     FaceType          当前表情类型
  _faceFrame       uint8_t           当前帧索引
  _faceFrameTimer  unsigned long     帧切换定时器

显示模式:
  _displayMode     DisplayMode       NORMAL / PIXEL
  _nightShiftWarmth float           色温暖度系数 (0.0 ~ 1.0)
  _brightness      float             当前亮度 EMA 滤波值
  _fadeState       FadeState         淡入淡出状态
  _fadeFrame       uint8_t           当前淡入淡出帧索引
```

### 2.3 DisplayMode 枚举

```
enum DisplayMode {
  NORMAL,   // 标准仪表盘模式：温度/Token/天气/表情
  PIXEL     // 像素模式：全屏表情特写或自定义像素画
};
```

### 2.4 主渲染入口

`render()` 方法是每帧的入口点，按固定顺序调度所有渲染子系统：

```
render()
  |-> fillScreen(COLOR_BG)          // 清屏
  |-> drawHeader()                   // 顶部标题栏
  |-> drawStatusBar()                // 状态指标条
  |-> drawThinkingIndicator()        // 思考链指示器
  |-> drawWeatherPanel()             // 天气信息面板
  |-> drawTokenPanel()               // Token 用量面板
  |-> drawFaceAnimation()            // 表情动画区域
  |-> applyNightFilter()             // 夜间色温滤镜
  |-> pushSprite(0, 0)              // 推送到 LCD
```

---

## 3. Sprite 双缓冲渲染流程

### 3.1 双缓冲原理

项目使用 LovyanGFX 的 `LGFX_Sprite` 作为内存帧缓冲，实现"离屏渲染 -> 整帧推送"的
双缓冲策略，避免画面撕裂和闪烁：

```
  CPU 渲染流程:
  ┌──────────────────────────────────────────────┐
  │  1. 在 _sprite (RAM) 中绘制所有 UI 元素      │
  │  2. 应用滤镜（夜间色温等）                     │
  │  3. pushSprite() 通过 DMA 推送到 LCD GRAM    │
  └──────────────────────────────────────────────┘

  SPI DMA 传输:
  ┌──────────────────────────────────────────────┐
  │  pushSprite() 触发 DMA 传输                  │
  │  CPU 立即返回，可执行其他任务                  │
  │  DMA 完成后触发中断（或下次 push 前等待）      │
  └──────────────────────────────────────────────┘
```

### 3.2 Sprite 内存布局

`LGFX_Sprite` 240x240 在 RGB565 格式下占用内存：

```
  240 * 240 * 2 字节 = 115,200 字节 ≈ 112.5 KB
```

这个大小适合 ESP32-S3 的内部 SRAM（512KB），无需使用 PSRAM。
Sprite 在创建时通过 `createSprite()` 一次性分配，后续所有绘制操作直接写入这块内存。

### 3.3 DMA 等待机制

在每次 `pushSprite()` 之前，系统会等待上一次 DMA 传输完成：

```
等待 DMA 完成:
  _lcd.waitDMA()        // 阻塞直到 SPI DMA 传输结束
  _sprite.pushSprite()  // 发起新的 DMA 传输
```

这种"串行 DMA"模式确保数据一致性，同时让每次帧传输的 CPU 开销最小化。

### 3.4 色彩格式

RGB565 是 16-bit 色彩格式，每个像素的位布局：

```
  Bit:  15 14 13 12 11 | 10 9 8 7 6 5 | 4 3 2 1 0
  通道: R  R  R  R  R  | G  G  G  G  G | B  B  B  B  B
  位数:      5-bit     |     6-bit     |    5-bit
```

LovyanGFX 提供 `color565(r, g, b)` 和 `color332(r, g, b)` 等辅助函数进行色彩转换。

---

## 4. 脏矩形优化

### 4.1 动机

全屏 240x240 的 `pushSprite()` 传输量为 115,200 字节。在大多数帧中，只有表情区域
（32x32 或局部区域）发生变化。脏矩形优化通过只传输变化区域来减少 SPI 数据量。

### 4.2 setClipRect 机制

LovyanGFX 的 `setClipRect()` 方法设置裁剪区域，后续所有绘制操作（包括 `pushSprite()`）
都限制在该区域内：

```
// 设置裁剪区域仅覆盖表情区域
int faceY = getFaceYPosition();
_sprite.setClipRect(0, faceY - 4, 240, FACE_SIZE + 8);

// 此时 pushSprite 只传输裁剪区域内的像素
_sprite.pushSprite(&_lcd, 0, 0);

// 清除裁剪区域，恢复正常全屏绘制
_sprite.setClipRect(0, 0, 240, 240);
```

### 4.3 表情脏矩形参数

```
  X:      0          (全宽，因为表情可能水平移动)
  Y:      faceY - 4  (表情区域上方留 4px 安全边距)
  宽度:   240        (面板全宽)
  高度:   FACE_SIZE + 8  (表情高度 + 上下各 4px 边距)
```

安全边距确保表情动画的过渡帧不会被裁剪切断。

### 4.4 性能收益

```
  全屏传输:   240 * 240 * 2 = 115,200 bytes @ 80MHz SPI ≈ 1.4ms
  脏矩形传输: 240 * 40 * 2  =  19,200 bytes @ 80MHz SPI ≈ 0.23ms
  节省:       ~83% 传输量，CPU 空闲时间增加约 1.2ms/帧
```

---

## 5. 表情系统（4 种 x 4 帧）

### 5.1 表情类型

系统定义了 4 种表情状态，每种对应一个 `FaceType` 枚举值：

| 枚举值     | 含义     | 触发场景                 |
|-----------|----------|--------------------------|
| HAPPY     | 开心     | 系统空闲、任务完成        |
| WORKING   | 工作中   | 正在处理 AI 推理任务      |
| AUTH      | 认证中   | 等待用户授权或 API 认证   |
| OFFLINE   | 离线     | 网络断开或 PC 连接丢失    |

### 5.2 帧动画

每种表情包含 4 帧像素画数据，每帧为 32x32 像素：

```
  drawFace(x, y, faceType, frameIndex)
    faceType:    FaceType 枚举
    frameIndex:  0-3，表示动画的第几帧
    x, y:        屏幕绘制坐标
```

动画通过定时器 `_faceFrameTimer` 驱动帧切换，典型帧间隔约 200-300ms，形成
流畅的眨眼或呼吸动画效果。

### 5.3 像素画存储

32x32 的 RGB565 像素画数据存储在 PROGMEM（Flash）中，避免占用宝贵的 RAM：

```
  单帧大小:  32 * 32 * 2 = 2,048 字节
  总帧数:    4 种表情 x 4 帧 = 16 帧
  总存储:    16 * 2,048 = 32,768 字节 ≈ 32 KB (Flash)
```

### 5.4 表情绘制流程

```
drawFaceAnimation():
  1. 计算表情区域坐标 (居中或指定位置)
  2. 检查帧定时器，必要时递增 frameIndex (循环 0-3)
  3. 从 PROGMEM 读取像素数据
  4. 逐行写入 _sprite 缓冲区
  5. 如启用脏矩形，设置 clipRect 限制推送范围
```

---

## 6. 天气图标系统（11 种）

### 6.1 图标类型

系统支持 11 种天气状态的像素图标，每种为 20x20 像素的像素画：

| 编号 | 图标类型   | 描述               |
|------|-----------|--------------------|
| 0    | SUN       | 晴天（太阳）        |
| 1    | MOON      | 晴夜（月亮）        |
| 2    | CLOUD     | 多云               |
| 3    | RAIN      | 小雨               |
| 4    | HEAVY_RAIN| 大雨               |
| 5    | SNOW      | 雪                 |
| 6    | THUNDER   | 雷暴               |
| 7    | FOG       | 雾                 |
| 8    | DRIZZLE   | 毛毛雨             |
| 9    | WIND      | 大风               |
| 10   | UNKNOWN   | 未知/默认           |

### 6.2 图标数据

```
  单图标大小: 20 * 20 * 2 = 800 字节
  总图标数:   11 种
  总存储:     11 * 800 = 8,800 字节 ≈ 8.6 KB (Flash/PROGMEM)
```

### 6.3 天气面板渲染

天气面板位于屏幕的特定区域，渲染内容包括：

- 天气图标（20x20 像素画，从 PROGMEM 读取并绘制到 Sprite）
- 温度数值（通过弹簧动画平滑过渡）
- 天气描述文本（截断显示，避免溢出）

```
drawWeatherPanel():
  1. 获取当前天气数据
  2. 绘制天气图标 (drawWeatherIcon)
  3. 通过 _tempSpring 获取动画插值后的温度
  4. 格式化并绘制温度文本
  5. 绘制天气描述（如有）
```

---

## 7. 弹簧动画系统

### 7.1 设计动机

数值的突然跳变（如温度从 25 度跳到 28 度）在小型 LCD 上会显得生硬刺眼。弹簧动画
模拟物理弹簧的阻尼振荡，让数值变化自然平滑。

### 7.2 SpringAnimation 参数

```
  弹性系数 (stiffness):   0.01 ~ 0.10
    控制弹簧"硬度"，值越大，动画越快到达目标值
    低值 (0.01): 缓慢柔和的过渡
    高值 (0.10): 快速响应

  阻尼系数 (damping):     0.70 ~ 0.95
    控制振荡衰减速度
    低值 (0.70): 会有明显的过冲和振荡
    高值 (0.95): 几乎无振荡，平滑收敛

  迟滞死区 (hysteresis):  可选
    当目标值变化小于阈值时，忽略更新，避免微小扰动触发动画
```

### 7.3 动力学公式

每帧更新采用简化的弹簧-阻尼模型：

```
  velocity += (target - current) * stiffness
  velocity *= damping
  current  += velocity
```

这个模型的关键特性：
- **一阶连续**：位置不会突变，始终平滑
- **能量耗散**：damping < 1.0 确保振荡逐渐衰减
- **自适应速度**：距目标越远，速度越大

### 7.4 应用场景

系统中有 4 个独立的弹簧动画实例：

| 实例         | 动画内容           | stiffness | damping |
|-------------|-------------------|-----------|---------|
| _tempSpring | 温度数值           | 0.05      | 0.85    |
| _tokenSpring| Token 用量百分比    | 0.08      | 0.90    |
| _cpuSpring  | CPU 使用率         | 0.06      | 0.88    |
| _memorySpring| 内存使用率        | 0.06      | 0.88    |

### 7.5 与 ThinkingStepCache 的配合

弹簧动画还可用于思考链面板中的数值过渡效果，使 Token 计数和思考步骤的显示
更加流畅自然。

---

## 8. 思考链历史展示（PSRAM 链表 + 缓动滚动）

### 8.1 概述

当 AI 模型进行推理时，系统会实时展示模型的"思考步骤"，让用户了解模型的
推理过程。这是一个技术挑战较大的子系统，因为它需要在有限的屏幕上高效管理
动态增长的文本列表。

### 8.2 ThinkingStepCache 数据结构

使用 PSRAM 中的双向链表存储思考步骤：

```
节点结构 ThinkingNode:
  +-------------------+
  | ThinkingStep      |
  |  - timestamp      |   // 步骤产生的时间戳
  |  - text[64]       |   // 步骤文本，最多 63 字符 + '\0'
  +-------------------+
  | ThinkingNode* next|   // 指向更新的步骤
  | ThinkingNode* prev|   // 指向更旧的步骤
  +-------------------+

缓存容量: 最多 40 个节点 (MAX_THINKING_STEPS = 40)
内存分配: 使用 PSRAM (heap_caps_malloc with MALLOC_CAP_SPIRAM)
```

### 8.3 PSRAM 分配策略

ESP32-S3 的 PSRAM 适合存储大量非实时访问的数据：

```
  单节点大小:  64 (text) + 4 (timestamp) + 8 (两个指针) ≈ 76 字节
  40 节点总计: 40 * 76 ≈ 3,040 字节
  分配方式:    heap_caps_malloc(size, MALLOC_CAP_SPIRAM)
```

使用 PSRAM 的优势是将内部 SRAM 留给 Sprite 帧缓冲和实时渲染数据。

### 8.4 操作接口

```
addStep(const char* text):
  1. 在 PSRAM 中分配新 ThinkingNode
  2. 复制文本到 node->step.text（最多 63 字节）
  3. 记录当前时间戳
  4. 将新节点插入链表头部（最新在前）
  5. 若超过 40 节点，删除尾部最旧节点并释放内存

getRecentSteps(count):
  1. 从链表头部开始
  2. 收集最近 count 个步骤
  3. 返回指针数组（newest-first 顺序）
```

### 8.5 显示渲染

思考链面板在屏幕上的渲染参数：

```
  可见步数:    5 步
  文本截断:    28 字符（超出部分显示 "..."）
  背景面板:    半透明叠加层
  滚动方式:    CIE 缓动函数（smoothstep）
```

### 8.6 CIE 缓动滚动

当有新步骤加入时，面板内容以缓动动画滚动，避免突然跳变：

```
  CIE smoothstep 函数:
    f(t) = 3t^2 - 2t^3

  特性:
    f(0) = 0, f(1) = 1
    f'(0) = 0, f'(1) = 0
    加速开始，减速结束，无突变

  应用:
    scrollOffset = startOffset + (endOffset - startOffset) * f(progress)
    progress: 0.0 ~ 1.0，由动画定时器线性插值得出
```

### 8.7 半透明背景面板

思考链面板使用半透明背景来区分与其他 UI 元素的层次：

```
  实现方式:
    1. 计算面板区域的原始像素
    2. 与背景色进行 alpha 混合
    3. 在半透明背景上绘制文本

  混合公式:
    result = (bg * alpha + overlay * (16 - alpha)) >> 4
    alpha: 0-16 的整数（4-bit 精度）
```

---

## 9. 夜间色温模式（RGB565 矩阵）

### 9.1 功能描述

夜间色温模式在 20:00 至 08:00 期间自动启用，将屏幕色温调暖（偏橙黄色），
减少蓝光对用户睡眠的影响。这个功能参考了 f.lux 和 iOS Night Shift 的设计思路。

### 9.2 NTP 时间判断

系统通过 NTP 同步获取当前时间，判断是否处于夜间时段：

```
  夜间时段:  20:00:00 ~ 08:00:00
  判断逻辑:  hour >= 20 || hour < 8
  warmup:    日落前 30 分钟开始渐进过渡
  cooldown:  日出前 30 分钟开始渐进恢复
```

### 9.3 RGB565 三通道矩阵变换

色温调整通过 RGB565 的三个通道独立缩放实现：

```
  通道缩放系数（满色温时）:
    R:  x1.08  （红色略微增强，偏暖）
    G:  x0.88  （绿色适度降低）
    B:  x0.61  （蓝色大幅削减，去除蓝光）

  矩阵形式:
    [R']   [1.08  0    0  ] [R]
    [G'] = [0     0.88 0  ] [G]
    [B']   [0     0    0.61] [B]
```

### 9.4 Q8 定点数实现

为避免浮点运算的性能开销，系统使用 Q8 定点数格式：

```
  Q8 格式:  1.0 = 256

  计算公式:
    factor = 256 + warmth * N
    其中 warmth 为 0.0 ~ 1.0 的色温暖度
    N 为各通道的缩放系数（整数）

  通道计算:
    R' = (R * factor_R) >> 8
    G' = (G * factor_G) >> 8
    B' = (B * factor_B) >> 8

  示例（warmth = 1.0 时）:
    factor_R = 256 + 1.0 * 20  = 276  -> R * 1.078
    factor_G = 256 + 1.0 * (-30) = 226 -> G * 0.883
    factor_B = 256 + 1.0 * (-100) = 156 -> B * 0.609
```

### 9.5 像素级变换流程

```
applyNightFilter():
  if not nightTime: return

  1. 获取 _sprite 缓冲区指针 (uint16_t*)
  2. 遍历 240 * 240 = 57,600 个像素
  3. 对每个像素:
     a. 提取 R (5-bit), G (6-bit), B (5-bit)
     b. 乘以对应通道的 Q8 系数
     c. 右移 8 位得到新值
     d. 钳位到通道最大值 (R:31, G:63, B:31)
     e. 重新组合为 RGB565
  4. 写回 _sprite 缓冲区
  5. pushSprite 到 LCD
```

### 9.6 性能考量

```
  像素总数:     240 * 240 = 57,600
  每像素操作:   3 次乘法 + 3 次移位 + 位提取/组合
  优化手段:
    - 使用 DMA 等待期间进行计算（流水线重叠）
    - 可选: 使用 ESP32-S3 SIMD 指令加速
    - 仅在色温暖度变化时重新计算
```

---

## 10. 平滑背光（EMA 滤波）

### 10.1 问题描述

直接设置背光亮度（如从 255 跳到 100）会在视觉上产生突兀的闪烁感。
人眼对亮度变化的感知是非线性的，突然的亮度跳变尤其明显。

### 10.2 EMA 低通滤波器

指数移动平均（Exponential Moving Average）是一阶 IIR 低通滤波器：

```
  公式:
    y[n] = alpha * x[n] + (1 - alpha) * y[n-1]

  参数:
    alpha = 0.15  （滤波系数）
    x[n]  = 目标亮度
    y[n]  = 当前滤波输出

  时间常数:
    tau = 1 / alpha = 6.67 帧
    95% 响应时间 ≈ 3 * tau = 20 帧
    以 30fps 计算，约 0.67 秒达到 95% 目标值
```

### 10.3 三级亮度状态

系统定义了三种背光状态，对应不同的场景：

```
  状态转移:
    ACTIVE ──(超时)──> DIM ──(超时)──> SLEEP ──(事件)──> WAKEUP ──> ACTIVE

  ACTIVE:   LCD_BRIGHTNESS = 200  (用户活跃)
  DIM:      LCD_BRIGHTNESS = 60   (屏幕变暗提示)
  SLEEP:    LCD_BRIGHTNESS = 0    (完全关闭背光)
  WAKEUP:   LCD_BRIGHTNESS = 200  (唤醒瞬间)
```

### 10.4 三种背光 API

```
setBrightness(target):
  设置 EMA 目标值，滤波器会平滑过渡到新值
  用于正常的亮度调节（如环境光变化）

setBrightnessImmediate(value):
  立即设置背光，跳过 EMA 滤波
  用于 SLEEP -> WAKEUP 等需要瞬间响应的场景

applySmoothBacklight():
  每帧调用，执行 EMA 滤波计算并应用到硬件
  _brightness = alpha * _targetBrightness + (1 - alpha) * _brightness
  _lcd.setBrightness((uint8_t)_brightness)
```

### 10.5 人眼感知优化

由于人眼对亮度的感知是近似对数曲线的，直接线性 EMA 可能在低亮度区间
过渡不够平滑。系统可选用感知均匀的亮度映射：

```
  线性亮度:    0, 1, 2, ..., 255
  感知均匀:    0, 1, 4, 9, ..., 255  (平方映射)

  EMA 仍在感知空间中计算，确保视觉上均匀过渡
```

---

## 11. 模式切换淡入淡出（alpha 混合）

### 11.1 场景

当用户在 NORMAL（仪表盘）模式和 PIXEL（像素画）模式之间切换时，
屏幕内容会发生完全变化。如果直接切换，视觉效果会很突兀。
淡入淡出通过 16 帧的 alpha 混合实现平滑过渡。

### 11.2 16 帧混合算法

```
  帧数:     16 帧
  alpha:    从 0 线性增长到 16（整数）
  invAlpha: 从 16 线性减小到 0

  混合公式（逐像素）:
    result = (oldPixel * invAlpha + newPixel * alpha) >> 4

  其中:
    oldPixel: 旧画面（源模式）的像素值
    newPixel: 新画面（目标模式）的像素值
    alpha:    当前帧的混合系数 (0-16)
    invAlpha: 16 - alpha
    >> 4:     相当于除以 16，还原到原始范围
```

### 11.3 双 Sprite 缓冲

淡入淡出需要同时访问新旧两帧画面，因此使用了 `_transitionSprite`：

```
  _sprite:            当前正在显示的画面（旧内容）
  _transitionSprite:  预渲染的目标模式画面（新内容）

  切换流程:
    1. 保存当前 _sprite 内容到 _transitionSprite（或直接复用）
    2. 在 _sprite 中渲染新模式的内容
    3. 逐帧混合 _transitionSprite（旧）和 _sprite（新）
    4. 混合结果推送到 LCD
    5. 16 帧后，切换完成，释放过渡 Sprite
```

### 11.4 帧时序

```
  帧 0:   alpha=0   invAlpha=16  -> 100% 旧画面
  帧 1:   alpha=1   invAlpha=15  -> 6.25% 新 + 93.75% 旧
  帧 2:   alpha=2   invAlpha=14  -> 12.5% 新 + 87.5% 旧
  ...
  帧 8:   alpha=8   invAlpha=8   -> 50% 新 + 50% 旧（交叉点）
  ...
  帧 14:  alpha=14  invAlpha=2   -> 87.5% 新 + 12.5% 旧
  帧 15:  alpha=15  invAlpha=1   -> 93.75% 新 + 6.25% 旧
  帧 16:  alpha=16  invAlpha=0   -> 100% 新画面
```

### 11.5 性能优化

```
  每帧混合操作量: 240 * 240 = 57,600 像素
  每像素:         2 次乘法 + 1 次加法 + 1 次移位
  16 帧总增量:    仅在过渡期间发生，不影响稳态性能

  优化手段:
    - 使用 16-bit 整数运算避免浮点
    - >> 4 移位代替除法
    - 可选: ESP32-S3 SIMD 并行处理多像素
```

---

## 12. V-Sync 同步

### 12.1 画面撕裂问题

LCD 面板有自己的刷新周期（典型 60Hz，约 16.67ms 一帧）。如果 SPI 写入
发生在 LCD 正在扫描显示的过程中，屏幕上半部分显示旧帧、下半部分显示新帧，
产生可见的"撕裂线"。

### 12.2 TE（Tearing Effect）信号

ST7789V 提供 TE 引脚输出，信号行为：

```
  TE 引脚: 下降沿表示 LCD 开始 VBlank（垂直消隐期）
  时序:    LCD 完成一帧扫描后，TE 引脚产生下降沿
  意义:    此时 LCD 停止从 GRAM 读取像素，是安全写入的窗口
```

### 12.3 GPIO 中断方式

```
  硬件配置:
    TE 引脚 -> GPIO（项目中定义为 LCD_TE_PIN）
    中断类型: FALLING（下降沿触发）

  工作流程:
    1. 配置 GPIO 为输入，使能内部上拉
    2. 注册 FALLING 中断处理函数
    3. 中断处理函数设置 volatile 标志位
```

### 12.4 waitForVSync 实现

```
waitForVSync():
  if LCD_TE_PIN == -1:
    // 软件降级方案：固定延迟
    vTaskDelay(pdMS_TO_TICKS(16))
    return

  // 等待 TE 中断标志
  unsigned long start = millis()
  while (!teReceived):
    vTaskDelay(pdMS_TO_TICKS(1))  // 让出 CPU，允许其他任务运行
    if (millis() - start > 20):   // 20ms 超时保护
      break                       // 超时则放弃等待，直接推送

  teReceived = false  // 重置标志
```

### 12.5 软件降级方案

当 `LCD_TE_PIN` 设为 -1（未连接 TE 引脚）时，系统退化为固定延迟方案：

```
  软件 V-Sync:
    vTaskDelay(16ms)  // 大致对齐 60Hz 周期
    注意: 无法精确同步，可能存在轻微撕裂
```

### 12.6 任务让出机制

`vTaskDelay(1)` 在 FreeRTOS 中的含义：

```
  - 将当前任务放入就绪队列末尾
  - 允许同优先级或更高优先级的任务运行
  - 至少等待 1 个 tick（通常 1ms）
  - 避免忙等待（busy-wait）浪费 CPU 电量
```

---

## 13. 代码优化技巧

### 13.1 snprintf 替代 String 堆分配

**问题**: Arduino 的 `String` 类使用动态堆分配，频繁创建/销毁导致内存碎片。

**优化**: 使用 `snprintf` + 固定大小 `char[]` 缓冲区：

```
  优化前:
    String text = "温度: " + String(temp) + "°C";
    // 每次调用都进行堆分配

  优化后:
    char buf[32];
    snprintf(buf, sizeof(buf), "温度: %d°C", temp);
    // 栈上分配，零堆碎片
```

### 13.2 PROGMEM 256 条目正弦查找表

**问题**: 三角函数（sin/cos）是浮点运算，在 ESP32 上单次调用约 5-10us。

**优化**: 预计算 256 条正弦值的查找表，存储在 PROGMEM（Flash）中：

```
  查找表参数:
    条目数:    256（覆盖 0 ~ 2*PI）
    精度:      Q10 定点数（1024 = 1.0）
    存储位置:  PROGMEM（Flash，不占 RAM）
    大小:      256 * 2 = 512 字节

  查询:
    index = angle & 0xFF           // 取低 8 位作为索引
    sinValue = pgm_read_word(&sinLUT[index])  // 从 Flash 读取
    // 结果为 Q10 格式，需要除以 1024.0 转换为浮点
```

### 13.3 DMA 等待时序优化

**问题**: 如果在 `pushSprite()` 后立即开始下一帧的渲染计算，可能与 DMA 传输
争用 SPI 总线。

**优化策略**:

```
  最优时序:
    pushSprite()        // 启动 DMA 传输（CPU 立即返回）
    计算下一帧数据      // CPU 做渲染计算，DMA 同时传输
    waitDMA()           // 等待 DMA 完成（通常已在计算期间完成）
    pushSprite()        // 传输新一帧

  效果: DMA 传输与 CPU 计算并行，帧时间 = max(计算时间, 传输时间)
```

### 13.4 固定点数替代浮点数

在 ESP32-S3 上（无硬件 FPU 的部分运算），浮点乘法比整数乘法慢 3-5 倍：

```
  浮点:    result = pixel * 0.88f;    // ~15 CPU 周期
  定点:    result = (pixel * 225) >> 8;  // ~3 CPU 周期

  常用定点格式:
    Q8:    256 = 1.0, 精度 1/256 ≈ 0.39%
    Q10:   1024 = 1.0, 精度 1/1024 ≈ 0.098%
```

### 13.5 局部变量避免堆分配

```
  优化原则:
    - 小缓冲区（< 256 字节）使用栈上 char[]
    - 大缓冲区使用 PSRAM 的预分配池
    - 避免在渲染循环中调用 new/malloc
    - 使用 static 局部变量复用缓冲区
```

### 13.6 编译器提示

```
  常用编译器属性:
    PROGMEM:    数据存储在 Flash，需要 pgm_read 专用函数访问
    IRAM_ATTR:  中断处理函数放入 IRAM，避免 Flash 访问延迟
    DRAM_ATTR:  全局变量强制放入 DRAM（默认行为，显式标注增加可读性）

  优化级别:
    -O2:        推荐用于发布版本
    -Os:        空间优化，Flash 紧张时使用
```

---

## 附录：渲染管线时序图

```
一帧完整渲染（目标 30fps，33ms 周期）:

  时间轴 (ms):
  0          5          10         15         20         25    33
  |----------|----------|----------|----------|----------|-----|
  | 清屏+绘制 | 表情+面板 | 夜间滤镜  | DMA传输   | CPU空闲  |下一帧|
  | fillScreen| drawFace | nightFilt| pushDMA  | (其他任务)|     |
  | drawHeader| drawPanel|          |          |          |     |
  | drawStatus|          |          |          |          |     |

  性能预算:
    清屏+绘制:    ~5ms
    表情+面板:    ~3ms
    夜间滤镜:     ~2ms (仅夜间模式)
    DMA传输:      ~1.4ms (全屏) / ~0.2ms (脏矩形)
    剩余空闲:     ~21ms (用于其他 FreeRTOS 任务)
```

---

## 附录：关键数据结构汇总

```
LGFX_Sprite (_sprite):
  分辨率:    240 x 240
  格式:      RGB565 (16-bit)
  大小:      115,200 bytes
  分配位置:  内部 SRAM

ThinkingStepCache:
  节点数:    最多 40
  单节点:    ~76 bytes
  总大小:    ~3,040 bytes
  分配位置:  PSRAM

SpringAnimation (x4 实例):
  状态变量:  current, velocity, target
  参数:      stiffness, damping
  大小:      ~16 bytes/实例
  分配位置:  DisplayManager 成员

正弦查找表:
  条目:      256
  精度:      Q10
  大小:      512 bytes
  存储位置:  PROGMEM (Flash)

天气图标:
  数量:      11 种
  单图标:    20x20 RGB565 = 800 bytes
  总大小:    8,800 bytes
  存储位置:  PROGMEM (Flash)

表情帧:
  数量:      4 种 x 4 帧 = 16 帧
  单帧:      32x32 RGB565 = 2,048 bytes
  总大小:    32,768 bytes
  存储位置:  PROGMEM (Flash)
```

---

> 文档版本: v1.0
> 最后更新: 2026-06-24
> 适用固件: esp32_firmware/src/display_manager.cpp
