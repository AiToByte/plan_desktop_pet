# 桌面宠物 — 项目总览

> **文档版本**: v1.0 | **最后更新**: 2026-06-24 | **适用仓库**: plan_desktop_pet

---

## 一、项目简介

### 1.1 一句话定义

**桌面宠物（Desktop Pet）** 是一款基于 ESP32-S3 的 1.54 英寸 LCD 桌面电子设备，通过 PC 端 Python 程序实时监控 AI Agent 进程状态，并以 WiFi TCP 方式将数据流式传输到 ESP32，在 240x240 像素屏幕上渲染像素风格表情、天气面板、Token 用量统计和思考链可视化内容。

### 1.2 它做什么

当开发者使用 Claude Code、Codex 等 AI 编程助手时，桌面宠物会：

- **实时感知** AI Agent 的工作/空闲/等待授权/离线状态，在 LCD 上显示对应表情
- **统计展示** Token 消耗量、API 调用次数、费用估算等关键指标
- **天气面板** 自动获取 OpenWeatherMap 数据，显示温度、湿度、风速和天气图标
- **思考链可视化** 通过 OTLP 遥测协议接收 Agent 的思维过程，以滚动文字形式呈现最近 40 步历史
- **像素动画** 支持用户自定义 32x32 PXL 格式动画，通过 RLE/Delta 压缩高效传输
- **多传感器交互** 光照自动背光、电容触摸手势、接近唤醒、触觉反馈（振动马达）和蜂鸣器提示音

### 1.3 设计哲学

桌面宠物的设计遵循三个核心理念：

**物理数字状态（Physical Digital Status）**
将虚拟世界中 AI Agent 的运行状态具象化为一个实体设备。开发者无需反复切换窗口查看终端日志，只需瞥一眼桌面，就能通过像素表情和指示灯了解 Agent 当前是否在工作、是否需要授权介入。这种"环境感知"（Ambient Awareness）设计大幅降低了上下文切换的认知成本。

**像素美学（Pixel Aesthetics）**
刻意采用 240x240 分辨率的像素风格，而非追求高分辨率显示。32x32 的像素块表情具有独特的"复古可爱"质感，与当今主流的光滑矢量 UI 形成差异化。自定义 PXL 格式支持 RLE 压缩和差分帧更新，使得在 240MHz 双核 MCU 上也能实现流畅的 60fps 动画。

**低功耗常亮（Low-Power Always-On）**
设备设计为 7x24 小时常开不假死。系统在检测到静默后，自动在"全亮 60fps -> 变暗 5fps -> 休眠 2fps + Modem-Sleep -> Light Sleep"之间平滑切换，在保障 WiFi TCP 常开的同时大幅降低待机功耗与射频发热。接近传感器可在用户靠近时自动唤醒屏幕，无需任何物理操作。

---

## 二、核心功能

### 2.1 Agent 状态实时显示

系统通过 PC 端 `psutil` 库每 2 秒扫描一次进程列表，检测 `claudecode`、`codex`、`ooencode` 等 AI Agent 进程的存在与资源占用，并映射为四种状态：

| 状态 | 编码 | 表情 | 触发条件 |
|------|------|------|----------|
| **IDLE** | 0 | 平静/眨眼动画 | Agent 进程存在但 CPU 占用极低 |
| **WORKING** | 1 | 工作中/专注表情 | Agent 进程 CPU 占用高于阈值 |
| **AUTH** | 2 | 等待授权/求助表情 | Agent 输出中包含授权确认关键字 |
| **OFFLINE** | 3 | 休眠/离线表情 | 45 秒无数据推送 |

状态切换后，固件端立即更新 LCD 显示区域的表情像素图、进程名称、CPU 百分比和内存占用量。

### 2.2 天气面板

PC 端通过 OpenWeatherMap API 获取实时天气数据（默认每 30 分钟刷新一次），包含以下信息：

- **温度**：当前温度与体感温度
- **湿度**：百分比显示
- **风速**：m/s 单位
- **天气描述**：如"晴"、"多云"、"小雨"等
- **天气图标**：在 LCD 上渲染对应的像素风格天气图标

天气数据通过 `WeatherInfo` 结构体传输，包含 `city`、`temperature`、`feelsLike`、`humidity`、`description`、`iconCode`、`windSpeed` 等字段。

### 2.3 Token 使用统计

PC 端 `token_stats` 模块自动解析 AI Agent 的日志文件，统计以下指标：

| 指标 | 字段 | 说明 |
|------|------|------|
| 输入 Token | `inputTokens` | 发送给 API 的 Token 总量 |
| 输出 Token | `outputTokens` | API 返回的 Token 总量 |
| 总请求数 | `totalRequests` | API 调用次数 |
| 小时 Token | `hourTokens` | 最近一小时的 Token 消耗 |
| 费用估算 | `costUSD` | 基于 Token 单价的费用估算（美元） |

统计数据以 JSON 格式推送到 ESP32，在屏幕的专用区域显示，帮助开发者直观掌握 API 使用情况和成本。

### 2.4 思考链可视化

这是桌面宠物最具特色的功能之一。PC 端通过 OTLP/HTTP 协议（端口 4318）接收 AI Agent 的遥测数据，解析其中的思维过程（thinking chain），并通过 `ThinkingState` 枚举标识当前状态：

| 状态 | 枚举值 | 含义 |
|------|--------|------|
| `THINK_IDLE` | 0 | 空闲，无思考活动 |
| `THINK_THINKING` | 1 | Agent 正在思考 |
| `THINK_TOOL_CALL` | 2 | Agent 正在调用工具 |
| `THINK_RESPONDING` | 3 | Agent 正在生成回复 |
| `THINK_ERROR` | 4 | 思考过程出错 |
| `THINK_DONE` | 5 | 思考完成 |

固件端使用 PSRAM 环形缓冲区存储最近 40 步（`THINKING_HISTORY_MAX`）的思考历史，屏幕同时可见 5 步（`THINKING_VISIBLE_COUNT`），当内容超过可见区域时自动以 800ms 动画时长进行滚动展示。单步文本最大长度为 64 字节。

### 2.5 自定义像素动画

桌面宠物支持用户自定义 32x32 像素图片或 GIF 动画显示，通过专用的 PXL 格式实现高效传输和播放：

**PXL 格式特点：**
- 32x32 像素，RGB565 色彩深度（每像素 2 字节）
- RLE（Run-Length Encoding）压缩：支持复制、重复、字面三种操作模式，最大游程 127
- 差分帧（Delta Frame）：完整帧标记 `0x01`，差分帧标记 `0x02`，仅传输变化的像素区域
- Base64 编码传输：通过 JSON `pixel_data` 消息的 `chunk_base64` 字段分块传输

**像素工具链：**
```
PNG/GIF 图片 --> pxl_encoder.py (RLE压缩) --> .pxl 文件 --> pxl_sender.py (WiFi发送) --> ESP32 播放
```

固件端使用 PSRAM 静态块缓冲区池（`g_pxlPool`，32x32x2x64 = 128KB）预分配像素内存，彻底避免运行时 `malloc` 造成的堆碎片化。

### 2.6 多传感器交互

桌面宠物集成了多种传感器和外设，提供丰富的物理交互体验：

**光照传感器（BH1750）**
- I2C 接口（SDA: GPIO41, SCL: GPIO42）
- 每 2 秒读取一次环境光强度
- 自动调节 LCD 背光亮度，暗光环境自动降低亮度减少刺眼感

**电容触摸（EC11 / Touch1）**
- 触摸引脚：GPIO1，阈值 40（需校准）
- 支持短按和长按（1 秒）两种手势
- 短按：切换显示面板（表情/天气/Token）
- 长按：进入配网模式或触发特殊动画

**接近感应（基于电容微量差分检测）**
- 使用快速 EMA（alpha=0.3）和慢速 EMA（alpha=0.05）双滤波器
- 上升差分阈值 8 检测接近，下降差分阈值 4 检测远离
- 接近事件冷却时间 2 秒（防抖）
- 接近唤醒后亮屏时长 15 秒

**触觉反馈（DRV2605L）**
- I2C 接口，与 BH1750 共享总线
- 线性谐振执行器（LRA）振动马达
- 在状态切换、触摸确认、错误提示时提供物理振动反馈

**蜂鸣器**
- 无源蜂鸣器，GPIO18 驱动
- 可播放简单旋律和提示音
- 用于配网成功、连接断开等事件的声音提示

### 2.7 屏幕休眠与省电

系统实现了多级自动省电策略，确保 7x24 小时常开的同时降低功耗：

| 阶段 | 触发条件 | 背光 | 帧率 | WiFi 模式 | 功耗状态 |
|------|----------|------|------|-----------|----------|
| **全亮** | 有数据活动 | 200/255 | 60fps | Active | 正常 |
| **变暗** | 30 秒无数据 | 降至最低 | 5fps | Active | 低 |
| **休眠** | 60 秒无数据 | 关闭 | 2fps | Modem-Sleep | 极低 |
| **Light Sleep** | 空闲超时 30 秒 | 关闭 | 唤醒检查 500ms | Light Sleep | 最低 |

当通信任务接收到新数据时，通过 `g_forceWake` 原子标志强制唤醒屏幕，恢复全亮 60fps 模式。WiFi 省电配置支持 DTIM 间隔调节（活跃态 DTIM=1，空闲态 DTIM=10），BSS 最大空闲时间 300 秒。

---

## 三、技术栈一览表

### 3.1 ESP32 固件端

| 层级 | 技术 | 用途 |
|------|------|------|
| **MCU** | ESP32-S3（双核 Xtensa LX7, 240MHz） | 主控芯片，512KB SRAM + 8MB PSRAM + 16MB Flash |
| **开发框架** | Arduino + FreeRTOS | 双核 SMP 架构：Core 0 通信、Core 1 渲染 |
| **屏幕驱动** | LovyanGFX | SPI 接口驱动 ST7789V（240x240 IPS LCD） |
| **JSON 解析** | ArduinoJson | 流式解析 PC 端推送的 JSON 数据帧 |
| **蓝牙** | NimBLE | BLE 配网服务，低功耗蓝牙广播 |
| **OTA** | esp_ota_ops | 固件空中升级支持 |
| **睡眠管理** | esp_sleep + esp_wifi | Active / Modem-Sleep / Light Sleep 三级省电 |

### 3.2 PC 监控端

| 层级 | 技术 | 用途 |
|------|------|------|
| **语言** | Python 3.11 | 主程序语言 |
| **进程监控** | psutil | 每 2 秒扫描 AI Agent 进程状态 |
| **天气 API** | requests | 调用 OpenWeatherMap REST API |
| **串口通信** | pyserial | 备用串口通信通道 |
| **系统托盘** | pystray | Windows 系统托盘常驻图标 |
| **数据可视化** | matplotlib | Token 统计图表生成 |
| **OTLP 接收** | otlp_receiver | 接收 Agent 遥测数据（端口 4318） |
| **思考链解析** | thinking_chain | 解析 OTLP span 中的思维过程 |

### 3.3 通信协议

| 协议 | 技术 | 用途 |
|------|------|------|
| **主通信** | TCP Framed Protocol（端口 19876） | PC -> ESP32 数据推送（JSON 帧） |
| **遥测采集** | OTLP/HTTP（端口 4318） | 接收 AI Agent 的 OpenTelemetry 数据 |
| **设备发现** | UDP Broadcast + mDNS | 局域网内自动发现 ESP32 设备 |
| **配网** | BLE Provisioning | 蓝牙低功耗配网，AP 热点备选 |
| **像素传输** | Base64 over JSON | PXL 动画数据分块传输 |

### 3.4 像素工具

| 层级 | 技术 | 用途 |
|------|------|------|
| **语言** | Python 3.9+ | CLI 工具 |
| **图像处理** | Pillow | PNG/GIF 读取、缩放、量化为 32x32 |
| **压缩** | 自研 PXL Encoder | RLE + Delta 帧压缩编码 |
| **传输** | pxl_sender | WiFi TCP 发送 .pxl 文件到 ESP32 |

---

## 四、项目目录结构

```
plan_desktop_pet/
│
├── README.md                          # 项目说明文档（英文）
├── LICENSE                            # Apache 2.0 开源许可
├── hardware_guide.md                  # 硬件选购与接线指南（原始版本）
├── docs/
│   ├── 00-项目总览/
│   │   ├── project-overview.md        # 项目总览（本文档）
│   │   └── feature-matrix.md          # 功能特性矩阵
│   ├── 01-技术架构/
│   │   ├── system-architecture.md     # 系统架构全景图
│   │   ├── data-flow.md              # 数据流转链路详解
│   │   └── communication-protocol.md  # TCP 通信协议详细规范
│   ├── 02-硬件指南/
│   │   ├── hardware-components.md     # 硬件组件选型详解
│   │   ├── hardware-wiring.md        # 接线指南与引脚图
│   │   ├── bom-list.md               # 物料清单与采购指南
│   │   └── hardware-design-notes.md   # 硬件设计参考
│   ├── 03-固件解析/
│   │   ├── firmware-overview.md       # 固件工程总览
│   │   ├── dual-core-architecture.md  # FreeRTOS 双核架构
│   │   ├── display-engine.md         # 显示引擎实现
│   │   ├── communication-stack.md     # 通信栈实现
│   │   ├── sensor-system.md          # 传感器系统
│   │   ├── power-management.md       # 电源与功耗管理
│   │   └── pxl-format.md             # PXL 像素格式规范
│   ├── 04-PC端解析/
│   │   ├── pc-monitor-overview.md     # PC 监控端总览
│   │   ├── agent-detection.md        # Agent 进程检测
│   │   ├── token-tracking.md         # Token 统计系统
│   │   ├── otlp-integration.md       # OTLP 遥测集成
│   │   └── tray-gui.md               # 托盘 GUI 实现
│   ├── 05-像素工具/
│   │   ├── pixel-tool-guide.md       # 像素工具使用指南
│   │   └── pixel-animation-tutorial.md # 像素动画制作教程
│   ├── 06-软硬件结合/
│   │   ├── sw-hw-integration.md      # 软硬件结合点详解
│   │   ├── provisioning-flow.md      # 设备配网全流程
│   │   └── ota-update.md             # OTA 固件升级机制
│   ├── 07-部署与落地/
│   │   ├── quick-start.md            # 5 分钟快速入门
│   │   ├── build-guide.md            # 固件编译指南
│   │   ├── deployment-guide.md       # 完整部署指南
│   │   └── production-roadmap.md     # 量产落地路线图
│   ├── 08-开发指南/
│   │   ├── dev-environment.md        # 开发环境搭建
│   │   ├── contributing.md           # 贡献指南
│   │   ├── testing-guide.md          # 测试指南
│   │   └── api-reference.md          # API 参考手册
│   └── 09-用户手册/
│       ├── user-manual.md            # 完整用户手册
│       ├── troubleshooting.md        # 故障排除指南
│       └── faq.md                    # 常见问题解答
├── plan.md                            # 项目规划文档
├── pyproject.toml                     # Python 项目配置
├── requirements.txt                   # Python 全局依赖
├── uv.lock                            # uv 包管理器锁定文件
├── .gitignore                         # Git 忽略规则
│
├── esp32_firmware/                    # ESP32-S3 固件（PlatformIO 项目）
│   ├── platformio.ini                 # PlatformIO 构建配置
│   ├── sdkconfig.defaults             # ESP-IDF SDK 配置默认值
│   ├── build.log                      # 构建日志
│   ├── include/                       # 公共头文件
│   │   ├── config.h                   # WiFi/屏幕/传感器/省电等全局配置
│   │   ├── types.h                    # 数据结构定义（AgentState/TokenStats/WeatherInfo/DisplayData）
│   │   └── log.h                      # 统一日志宏定义
│   ├── src/                           # 源代码
│   │   ├── main.cpp                   # 主程序入口，FreeRTOS 双核任务创建
│   │   ├── display_manager.cpp/.h     # LCD 显示管理（面板渲染、表情动画）
│   │   ├── pixel_player.cpp/.h        # 自定义像素动画播放器（PXL 解码）
│   │   ├── comm_manager.cpp/.h        # TCP 通信管理（JSON 帧解析、数据分发）
│   │   ├── wifi_manager.cpp/.h        # WiFi 连接管理（STA 模式、自动重连）
│   │   ├── web_config.cpp/.h          # Web 配网界面（AP 模式热点配置）
│   │   ├── ble_config.cpp/.h          # BLE 配网服务（NimBLE）
│   │   ├── ble_provisioner.cpp/.h     # BLE 配网数据处理
│   │   ├── ambient_light.cpp/.h       # BH1750 光照传感器管理
│   │   ├── haptic_driver.cpp/.h       # DRV2605L 触觉反馈驱动
│   │   ├── sound_manager.cpp/.h       # 蜂鸣器声音管理
│   │   ├── touch_handler.cpp/.h       # 电容触摸手势处理
│   │   ├── spring_animation.cpp/.h    # 弹簧物理动画引擎
│   │   └── sin_lut.h                  # 正弦查找表（动画优化）
│   ├── data/                          # SPIFFS 文件系统数据
│   │   └── images/                    # 内置像素图片资源
│   └── lib/                           # 第三方库（PlatformIO 管理）
│
├── pc_monitor/                        # PC 端 Python 监控程序
│   ├── main.py                        # 主入口（初始化模块、启动主循环）
│   ├── tray_app.py                    # Windows 系统托盘应用（pystray）
│   ├── requirements.txt               # Python 依赖清单
│   ├── config/                        # 配置目录
│   │   ├── config.example.json        # 配置文件模板（提交到 Git）
│   │   └── config.json                # 实际配置文件（Git 忽略）
│   └── modules/                       # 功能模块
│       ├── __init__.py                # 模块初始化
│       ├── agent_monitor.py           # Agent 进程监控（psutil 扫描）
│       ├── communication.py           # TCP 通信客户端（线程安全发送队列）
│       ├── token_stats.py             # Token 统计解析（日志文件分析）
│       ├── weather.py                 # 天气数据获取（OpenWeatherMap API）
│       ├── otlp_receiver.py           # OTLP/HTTP 遥测数据接收器
│       └── thinking_chain.py          # 思考链数据解析与管理
│
├── pixel_tool/                        # PC 端像素工具
│   ├── pixel_tool.py                  # CLI 入口（convert/send/cmd 子命令）
│   ├── pxl_encoder.py                 # PNG/GIF -> PXL 编码器（RLE + Delta 压缩）
│   ├── pxl_decoder.py                 # PXL -> PNG 解码器（调试用）
│   ├── pxl_sender.py                  # WiFi 发送器（TCP 传输 .pxl 到 ESP32）
│   ├── requirements.txt               # Python 依赖（Pillow）
│   ├── README.md                      # 像素工具使用说明
│   └── examples/                      # 示例素材
│       ├── heart.png / heart.pxl      # 爱心动画示例
│       ├── rainbow.png / rainbow.pxl  # 彩虹动画示例
│       └── smile.png / smile.pxl      # 笑脸动画示例
│
├── tests/                             # Python 测试套件
│   ├── conftest.py                    # pytest 全局 fixture
│   ├── test_agent_monitor.py          # Agent 监控模块测试
│   ├── test_communication.py          # 通信模块测试
│   ├── test_token_stats.py            # Token 统计测试
│   ├── test_weather.py                # 天气模块测试
│   ├── test_otlp_receiver.py          # OTLP 接收器测试
│   ├── test_thinking_chain.py         # 思考链解析测试
│   ├── test_pxl_encoder.py            # PXL 编码器测试
│   ├── test_pxl_decoder.py            # PXL 解码器测试
│   ├── test_helpers.py                # 辅助函数测试
│   ├── test_smoke.py                  # 冒烟测试
│   └── helpers/                       # 测试辅助模块
│       ├── factories.py               # 测试数据工厂
│       ├── mock_communication.py      # 通信模拟对象
│       └── mock_psutil.py             # psutil 模拟对象
│
└── docs/                              # 项目文档
    ├── communication_protocol.md      # TCP 通信协议详细规范
    ├── pxl_format.md                  # PXL 文件格式规范
    ├── api.md                         # API 接口文档
    ├── quick_start.md                 # 快速开始指南
    ├── USER_GUIDE.md                  # 用户使用手册
    ├── DEPLOYMENT_GUIDE.md            # 部署指南
    ├── hardware_design_notes.md       # 硬件设计笔记
    ├── 项目目前阶段情况-2026年6月24日.md  # 项目成熟度评估报告
    ├── 00-项目总览/                    # 项目总览文档（本文档所在目录）
    ├── 01-技术架构/                    # 技术架构设计文档
    ├── 02-硬件指南/                    # 硬件选型与接线文档
    ├── 03-固件解析/                    # ESP32 固件源码解析
    ├── 04-PC端解析/                    # PC 监控程序源码解析
    ├── 05-像素工具/                    # 像素工具使用文档
    ├── 06-软硬件结合/                  # 软硬件联调与集成文档
    ├── 07-部署与落地/                  # 量产部署与商业化指南
    ├── 08-开发指南/                    # 开发环境搭建与贡献指南
    └── 09-用户手册/                    # 最终用户操作手册
```

---

## 五、适用场景

### 5.1 开发者伴侣 —— 实时看到 AI Agent 状态

桌面宠物最核心的使用场景是作为 AI 编程助手的物理伴侣。当开发者使用 Claude Code、Codex 等工具进行日常编程时，无需反复在终端和编辑器之间切换来检查 Agent 是否在运行、是否需要授权介入。桌面宠物用直观的像素表情实时反馈 Agent 状态：

- Agent 正在编码时，屏幕显示专注的"工作"表情
- Agent 等待授权确认时，屏幕显示"求助"表情并伴随蜂鸣器提示
- Agent 空闲或离线时，屏幕显示"休息"或"睡眠"表情

Token 统计功能帮助开发者直观掌握 API 使用成本，避免意外超支。思考链可视化则让开发者实时了解 Agent 的推理过程，增强对 AI 工作方式的理解和信任。

### 5.2 桌面摆件 —— 天气、时钟与像素动画

即使不连接 AI Agent，桌面宠物本身也是一个精巧的桌面摆件：

- **天气面板**：自动获取并显示当地实时天气，出门前瞥一眼即可
- **像素动画**：通过像素工具将任意 PNG/GIF 图片转换为 32x32 像素风格动画，显示在 1.54 英寸屏幕上
- **环境光自适应**：根据环境光线自动调节屏幕亮度，白天清晰、夜间不刺眼
- **接近唤醒**：手靠近设备时自动亮屏，离开后自动变暗休眠

### 5.3 开源学习平台 —— ESP32 双核、传感器与通信协议

桌面宠物是一个优秀的嵌入式系统学习项目，涵盖了以下核心技术点：

- **FreeRTOS 双核 SMP 架构**：Core 0 负责网络通信与 JSON 流式解析，Core 1 负责 LCD 硬件刷新与交互，两核通过 `std::atomic` 指针和双缓冲进行无锁状态交换
- **多传感器集成**：BH1750 光照传感器（I2C）、电容触摸、DRV2605L 触觉反馈（I2C）、无源蜂鸣器（PWM）
- **通信协议设计**：TCP Framed Protocol、JSON 流式解析、Base64 分块传输、RLE/Delta 压缩编码
- **功耗管理**：Active / Modem-Sleep / Light Sleep 三级省电策略，DTIM 间隔调节
- **BLE 配网**：NimBLE 协议栈实现蓝牙低功耗配网
- **PSRAM 内存管理**：静态块缓冲区池避免运行时堆碎片化

### 5.4 IoT 原型参考 —— 配网、OTA 与功耗管理

对于 IoT 产品开发者，桌面宠物提供了一套完整的物联网设备参考实现：

- **配网方案**：支持 Web AP 热点配网和 BLE 蓝牙配网两种方式，用户无需硬编码 WiFi 凭据
- **OTA 升级**：通过 `esp_ota_ops` 实现固件空中升级，支持远程迭代
- **自动重连**：PC 端采用带随机抖动的指数退避重连算法，固件端支持 TCP Keep-Alive 探测与自动复位
- **mDNS 发现**：局域网内自动发现设备，无需手动输入 IP 地址
- **系统托盘集成**：PC 端通过 `pystray` 实现 Windows 系统托盘常驻，支持开机自启动

---

## 六、项目成熟度

> 以下评估基于 2026 年 6 月 24 日对项目代码库的全面工程级审查，详细报告参见 `docs/项目目前阶段情况-2026年6月24日.md`。

### 6.1 总体阶段判定

**项目当前所处阶段：Pre-Production / PVT 前夕（准量产与小批量试产阶段）。**

在软件架构、并发安全、协议完备性、内存管理和边界防御等纯软件工程维度，该项目已经明显超越了普通创客（Maker）开源项目的范畴，具备了立即可用、高健壮性的特点。然而，要作为大众消费级硬件产品推向市场，在硬件量产设计、合规认证和用户侧无阻碍体验上仍存在明确的工程差距。

### 6.2 软件健壮性（已达工业级指标）

| 维度 | 当前状态 | 达成度 |
|------|----------|--------|
| **高并发与内存管理** | 彻底摒弃运行时动态 `malloc`，采用 PSRAM 静态块缓冲区复用（`g_pxlPool` 和 `g_jsonParseBuf`），规避 OOM 崩溃 | 95% |
| **双核 SMP 架构** | Core 0 通信 + Core 1 渲染，通过 `std::atomic` 指针和双缓冲无锁交换，避免 Mutex 死锁 | 95% |
| **多级省电策略** | 全亮 -> 变暗 -> 休眠 -> Light Sleep 平滑切换，WiFi TCP 常开 | 95% |
| **通信容错** | 线程安全异步发送队列 + 指数退避重连 + TCP Keep-Alive 探测 + 自动复位 | 95% |
| **PC 端体验** | Python 脚本运行，终端输出 | 60% |
| **硬件工程** | 模块散件 + 杜邦线插接 | 35% |

### 6.3 商业化差距与路线图

**硬件级瓶颈：**
- BOM 成本过高（当前约 120 元/台 vs 量产目标 35-45 元/台）
- 杜邦线物理连接抗震性差，需设计集成 PCB
- 需通过 SRRC/FCC/CE 等无线射频强制认证

**软件级瓶颈：**
- PC 端需打包为独立 EXE 安装包（PyInstaller），消除 Python 环境依赖
- TCP/OTLP 端口默认绑定 `0.0.0.0`，需改为 `127.0.0.1` 并引导用户显式授权局域网访问
- 配网热点密码硬编码，需根据 MAC 地址动态生成唯一密码

**商业化三步走：**
1. **硬件量产化**：设计集成 PCB 母板，将 ESP32-S3、LCD、传感器、LDO 供电集成在单板上
2. **配网与安全性升级**：AP 密码唯一化、安全沙箱隔离、BLE 配网优化
3. **PC 上位机产品级封装**：PyInstaller 打包 + Inno Setup 安装向导 + 防火墙自动放行

---

## 七、开源许可

本项目采用 **Apache License 2.0** 开源许可。

```
Copyright 2026 Desktop Pet Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

**这意味着：**
- 你可以自由使用、修改和分发本项目的代码
- 你可以在商业项目中使用本项目的代码
- 你必须保留原始版权声明和许可文件
- 你必须标注对源代码的修改
- 本项目不提供任何担保

欢迎提交 Issue 和 Pull Request 参与项目贡献。

---

## 附录 A：快速参考卡片

### 关键配置参数速查

| 参数 | 默认值 | 所在文件 | 说明 |
|------|--------|----------|------|
| `SERVER_PORT` | 19876 | config.h | TCP 通信端口 |
| `SCREEN_WIDTH` x `SCREEN_HEIGHT` | 240 x 240 | config.h | LCD 分辨率 |
| `LCD_BRIGHTNESS` | 200 | config.h | LCD 背光亮度（0-255） |
| `COMM_TASK_CORE` | 0 | config.h | 通信任务运行核心 |
| `RENDER_TASK_CORE` | 1 | config.h | 渲染任务运行核心 |
| `SCREEN_DIM_TIMEOUT` | 30000 | config.h | 变暗超时（30 秒） |
| `SCREEN_SLEEP_TIMEOUT` | 60000 | config.h | 休眠超时（60 秒） |
| `OFFLINE_TIMEOUT_MS` | 45000 | config.h | 离线判定超时（45 秒） |
| `THINKING_HISTORY_MAX` | 40 | config.h | 思考链历史最大步数 |
| `IDLE_POWER_MODE` | 2 | config.h | 空闲省电模式（Light Sleep） |

### 数据结构速查

| 结构体 | 头文件 | 核心字段 |
|--------|--------|----------|
| `AgentState` | types.h | status, thinkingState, processName, cpuPercent, memoryMB |
| `TokenStats` | types.h | inputTokens, outputTokens, totalRequests, hourTokens, costUSD |
| `WeatherInfo` | types.h | city, temperature, humidity, description, windSpeed |
| `DisplayData` | types.h | agent, tokens, weather, thinkingHistory, scrollOffset |

### 硬件引脚速查

| 外设 | 引脚 | 说明 |
|------|------|------|
| LCD SCLK | GPIO12 | SPI 时钟 |
| LCD MOSI | GPIO11 | SPI 数据 |
| LCD CS | GPIO5 | 片选 |
| LCD DC | GPIO2 | 数据/命令 |
| LCD RST | GPIO4 | 复位 |
| LCD BL | GPIO48 | 背光 |
| BH1750 SDA | GPIO41 | I2C 数据（与触觉共用） |
| BH1750 SCL | GPIO42 | I2C 时钟（与触觉共用） |
| BUZZER | GPIO18 | 无源蜂鸣器 |
| TOUCH | GPIO1 | 电容触摸 |

---

## 附录 B：相关文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 系统架构全景 | `docs/01-技术架构/system-architecture.md` | 三层架构、模块关系、双核分工 |
| 数据流转链路 | `docs/01-技术架构/data-flow.md` | 6 条数据链路完整追踪 |
| 通信协议规范 | `docs/01-技术架构/communication-protocol.md` | TCP 帧格式、JSON 消息类型、错误处理 |
| PXL 格式规范 | `docs/03-固件解析/pxl-format.md` | 文件头、RLE 编码、Delta 帧、Base64 传输 |
| 硬件组件详解 | `docs/02-硬件指南/hardware-components.md` | 每个硬件组件的选型与参数 |
| 接线指南 | `docs/02-硬件指南/hardware-wiring.md` | 完整接线表格与引脚图 |
| 物料清单 | `docs/02-硬件指南/bom-list.md` | BOM 表格与采购指南 |
| 硬件设计参考 | `docs/02-硬件指南/hardware-design-notes.md` | PCB 设计、ESD 保护、热管理 |
| 快速入门 | `docs/07-部署与落地/quick-start.md` | 5 分钟快速上手 |
| 完整部署指南 | `docs/07-部署与落地/deployment-guide.md` | 生产环境部署步骤 |
| 量产路线图 | `docs/07-部署与落地/production-roadmap.md` | DFM/BOM/认证/产测方案 |
| 用户手册 | `docs/09-用户手册/user-manual.md` | 日常使用操作说明 |
| 故障排除 | `docs/09-用户手册/troubleshooting.md` | 常见问题排查 |
| API 参考 | `docs/08-开发指南/api-reference.md` | ESP32/PC/像素工具 API |
| 像素工具使用 | `docs/05-像素工具/pixel-tool-guide.md` | PXL 编码/发送/播放操作说明 |
| 项目成熟度评估 | `docs/项目目前阶段情况-2026年6月24日.md` | Pre-Production 阶段详细分析 |
