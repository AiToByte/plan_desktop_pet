# 功能特性矩阵

> 本文档全面梳理桌面宠物项目的所有已实现功能，按模块分类，标注当前状态与关键实现细节。
> 状态标记: ✅ 已实现 | 🔧 开发中 | 📋 计划中 | ⚠️ 部分实现

---

## 一、显示功能

桌面宠物的核心显示系统运行在 ESP32-S3 的 Core 1 渲染任务中，通过 SPI 驱动微雪 1.54 寸 LCD 屏幕（240x240 分辨率）。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| Agent 表情系统 | `display_manager.cpp` | ✅ | 像素风格表情动画，支持 WORKING / IDLE / AUTH / OFFLINE 四种状态面部表情，带眨眼动画 |
| 天气面板 | `display_manager.cpp` | ✅ | 实时天气图标 + 温度 + 湿度显示，OpenWeatherMap API 数据源 |
| Token 统计面板 | `display_manager.cpp` | ✅ | 显示 Token 消耗量、请求数、预估费用，弹簧动画平滑过渡 |
| 思考链历史 | `display_manager.cpp` | ✅ | 显示 Agent 最近的思考/操作历史记录，支持滚动浏览 |
| 像素动画播放 | `pixel_player.cpp` | ✅ | PXL 格式像素动画解码与播放，PSRAM 静态池预分配 128KB，支持暂停/恢复 |
| 夜间色温 | `display_manager.cpp` | ✅ | 基于 NTP 时间自动应用暖色滤镜（22:00-06:00），降低蓝光保护视力 |
| 弹簧动画系统 | `spring_animation.cpp` | ✅ | 阻尼弹簧物理引擎 + 滞回死区，用于数值面板的平滑过渡动画，避免微小抖动 |
| 脏矩形优化 | `display_manager.cpp` | ✅ | 仅重绘变化区域，减少 SPI 传输量，降低功耗和延迟 |
| V-Sync 垂直同步 | `display_manager.cpp` | ✅ | TE（Tearing Effect）中断信号同步，防止画面撕裂 |
| DMA 渲染 | `display_manager.cpp` | ✅ | SPI DMA 传输，CPU 不阻塞等待 SPI 完成，释放算力给动画计算 |
| 离线时钟模式 | `display_manager.cpp` | ✅ | 断网后自动切换为时钟显示 + 眨眼动画，保持屏幕活跃 |
| 双缓冲架构 | `main.cpp` | ✅ | Core 0 写 back buffer，Core 1 读 front buffer，atomic 指针交换无锁同步 |
| SRAM 切片传输 | `display_manager.cpp` | ✅ | 512 词 SRAM 缓冲区分块传输，避免 PSRAM 带宽瓶颈 |
| 淡入淡出过渡 | `display_manager.cpp` | ✅ | Alpha 混合过渡动画，模式切换时平滑过渡 |

---

## 二、通信功能

通信系统运行在 ESP32-S3 的 Core 0 通信任务中，负责与 PC 端的数据交换。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| TCP 帧协议 | `comm_manager.cpp` / `communication.py` | ✅ | 长度前缀帧协议 `L` + `LEN:NNNN\n` + body，最大帧 256KB，兼容旧 JSON 行格式 |
| WiFi STA 模式 | `wifi_manager.cpp` | ✅ | Station 模式连接家庭路由器，自动重连 |
| mDNS 服务发现 | `wifi_manager.cpp` | ✅ | 注册 `_deskpet._tcp.local.` 服务，PC 端可自动发现设备地址 |
| UDP 广播发现 | `wifi_manager.cpp` / `communication.py` | ✅ | 端口 19877 广播 `DESKTOP_PET_SERVER:IP:PORT`，设备自动保存服务器地址到 Flash |
| BLE 配网 | `ble_config.cpp` | ✅ | NimBLE 库实现，Service UUID 0x1820，支持 SSID/密码/URL 特征写入，120 秒超时 |
| Web AP 配网 | `web_config.cpp` | ✅ | Captive Portal 热点模式，SSID `DeskPet-Config`，响应式 HTML 表单，保存后自动重启 |
| TCP Keep-Alive | `comm_manager.cpp` | ✅ | 空闲 60s 后探测，每 10s 一次，3 次无响应判定断开，检测死连接 |
| 指数退避重连 | `comm_manager.cpp` | ✅ | 失败间隔翻倍，上限 60 秒，连续 10 次失败触发 WiFi 硬重置 |
| 崩溃遥测 | `main.cpp` / `communication.py` | ✅ | RTC_NOINIT 记录崩溃次数，首次连接后上报 PC 端，支持冷却防刷屏 |
| 心跳机制 | `main.cpp` / `communication.py` | ✅ | 每 10 秒发送心跳，PC 端 30 秒无心跳判定断连 |
| 批量帧写入 | `comm_manager.cpp` | ✅ | 帧体阶段直接从 readBuf 批量拷贝，避免逐字符 String 追加 |
| JSON 转义 | `web_config.cpp` | ✅ | `escapeJsonString` 处理特殊字符，防止响应格式破坏 |

---

## 三、传感器交互

外设传感器通过 I2C 总线和 GPIO 连接，提供环境感知和人机交互能力。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| BH1750 自动背光 | `ambient_light.cpp` | ✅ | I2C 地址 0x23，连续高分辨率模式，0-1000 lx 分段线性映射 20%-100% 亮度 |
| 电容触摸 - 单击 | `touch_handler.cpp` | ✅ | ESP32 内置触摸传感器，EMA 双均线算法检测接近，支持单击事件 |
| 电容触摸 - 双击 | `touch_handler.cpp` | ✅ | 双击间隔检测，区分单击/双击/长按 |
| 电容触摸 - 长按 | `touch_handler.cpp` | ✅ | 长按阈值判定，触发特殊操作 |
| 接近唤醒 | `touch_handler.cpp` | ✅ | EMA 快慢均线差值检测接近/远离，上升沿/下降沿事件，带冷却时间防抖 |
| DRV2605L 振动 | `haptic_driver.cpp` | ✅ | I2C 触觉反馈驱动，LRA 电机，内置波形序列库（8 槽位），支持内部触发模式 |
| 蜂鸣器音效 | `sound_manager.cpp` | ✅ | 硬件定时器 ISR + 正弦 LUT 查表，PWM 驱动，支持音效播放 |
| Light Sleep 唤醒 | `main.cpp` | ✅ | 触摸唤醒 + WiFi Beacon 唤醒，RTC IO 状态保持（背光/蜂鸣器/SPI 片选） |

---

## 四、省电管理

多级省电策略，根据设备活动状态自动切换功耗模式。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| CPU 动态调频 | `main.cpp` | ✅ | 活跃 240MHz / 休眠 80MHz，`setCpuFrequencyMhz()` 动态切换 |
| WiFi 省电模式 | `main.cpp` | ✅ | 活跃时 `WIFI_PS_NONE`（最低延迟），休眠时 `WIFI_PS_MAX_MODEM` + `listen_interval=3` |
| 屏幕休眠 | `main.cpp` | ✅ | 三级：变暗（DIM_TIMEOUT）→ 关屏（SLEEP_TIMEOUT）→ Light Sleep（5 分钟） |
| Light Sleep | `main.cpp` | ✅ | ESP32 Light Sleep 模式，触摸 + WiFi Beacon 唤醒，GPIO Hold 锁定引脚电平 |
| VRR 动态帧率 | `display_manager.cpp` | 🔧 | 根据内容变化频率动态调整刷新率，静态画面降低帧率节省功耗 |
| 背光缓动 | `display_manager.cpp` | ✅ | 亮度变化使用缓动系统，避免突然变化和频繁调节 |
| 屏幕唤醒机制 | `main.cpp` | ✅ | 数据到达自动唤醒 + BOOT 键手动唤醒，恢复 CPU 全速 + WiFi 活跃 |

---

## 五、PC 端功能

PC 端监控程序负责数据采集、Agent 状态监控和设备通信。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| Agent 进程检测 | `agent_monitor.py` | ✅ | psutil 检测 Claude Code / Codex 进程，CPU 阈值判定 WORKING / AUTH / IDLE / OFFLINE |
| JSONL 授权检测 | `agent_monitor.py` | ✅ | 读取 Claude 项目目录 JSONL 文件末尾 8KB，检测 permission_request / AskUser 事件 |
| Token 统计 | `token_stats.py` | ✅ | LogTailer 增量读取日志，统计 input/output tokens、请求数、预估费用，24 小时滚动窗口 |
| 天气服务 | `weather.py` | ✅ | OpenWeatherMap API，支持缓存机制，根据 Agent 状态动态调整刷新频率（10-60 分钟） |
| OTLP 遥测接收 | `otlp_receiver.py` | ✅ | OpenTelemetry Protocol 接收器，采集设备运行指标 |
| 系统托盘 GUI | `tray_app.py` | ✅ | pystray 托盘图标 + tkinter 窗口，Token 使用曲线（matplotlib）、Agent 指标面板 |
| 线程健康守护 | `main.py` | ✅ | ThreadHealthGuard 心跳监控所有工作线程，超时或死亡自动重建，30s 检查间隔 |
| UDP 广播服务 | `communication.py` | ✅ | 端口 19877 周期广播服务器地址，供设备自动发现 |
| mDNS 服务注册 | `communication.py` | ✅ | 注册 `deskpet.local` 服务，设备可通过 mDNS 自动发现 |
| 异步发送队列 | `communication.py` | ✅ | Queue 最大 64 条，非阻塞发送，防止主线程阻塞 |
| 消息类型分发 | `main.py` / `communication.py` | ✅ | DeviceMessage 分发：status / token / weather / animation / crash_report |

---

## 六、像素工具

PC 端像素编辑与导出工具，用于创建桌面宠物的自定义动画。

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| 像素编辑器 | `pixel_tool.py` | ✅ | tkinter 画布，支持 32x32 像素网格绘制 |
| PXL 编码器 | `pxl_encoder.py` | ✅ | 自定义二进制格式编码，支持帧头/帧数据/时间戳 |
| Delta 帧压缩 | `pxl_encoder.py` | ✅ | 帧间差分编码，仅传输变化像素，大幅减少数据量 |
| 动画预览 | `pixel_tool.py` | ✅ | 实时预览像素动画效果 |
| 文件导出 | `pixel_tool.py` | ✅ | 导出 .pxl 文件，可通过 TCP 发送到设备播放 |

---

## 七、架构特性

| 特性 | 模块 | 状态 | 说明 |
|------|------|------|------|
| FreeRTOS 双核 | `main.cpp` | ✅ | Core 0 通信 + Core 1 渲染，双缓冲无锁同步 |
| PSRAM 内存池 | `main.cpp` | ✅ | 静态预分配 128KB 像素池 + 4KB JSON 解析缓冲，消除运行时 malloc 碎片化 |
| 统一日志系统 | `log.h` | ✅ | 分级日志（LOG_I / LOG_W / LOG_E），串口输出，带时间戳 |
| 配置持久化 | `web_config.cpp` | ✅ | ESP32 Preferences (NVS) 保存 WiFi/服务器配置，命名空间 `pet_config` |
| 统一命名空间 | `web_config.cpp` / `wifi_manager.cpp` | ✅ | Flash 存储统一使用 `pet_config` 命名空间和一致的 Key 命名 |

---

## 八、功能依赖关系

```
BH1750 自动背光 ──→ 显示亮度
电容触摸 ──→ 接近唤醒 ──→ 屏幕休眠管理
                    ──→ 触摸事件（单击/双击/长按）
WiFi STA ──→ TCP 帧协议 ──→ Agent 状态显示
        ──→ mDNS 发现
        ──→ UDP 广播发现
BLE 配网 ──→ WiFi 凭据写入
Web AP 配网 ──→ WiFi 凭据 + 服务器地址
         ──→ OTA 固件升级
Agent 进程检测 ──→ 状态映射 ──→ 表情动画
Token 统计 ──→ 面板显示
天气服务 ──→ 天气图标 + 温度面板
CPU 调频 ──→ 屏幕休眠 ──→ Light Sleep
```

---

## 九、硬件资源占用

| 资源 | 用途 | 说明 |
|------|------|------|
| Core 0 | 通信任务 | WiFi/TCP/JSON 解析/Web 配网 |
| Core 1 | 渲染任务 | LCD 显示/动画/休眠管理 |
| PSRAM (2MB) | 像素池 + JSON 缓冲 | 静态预分配，避免碎片化 |
| Flash (NVS) | 配置存储 | WiFi 凭据、服务器地址 |
| RTC Memory | 崩溃计数 | `RTC_NOINIT_ATTR` 重启不丢失 |
| SPI 总线 | LCD 显示 | DMA 传输，OTA 时释放给固件写入 |
| I2C 总线 0 | BH1750 + DRV2605L | 环境光传感器 + 触觉反馈 |
| GPIO 0 | BOOT 键 | 唤醒 / 停止像素播放 |
| Touch Pin | 电容触摸 | 接近检测 + 触摸事件 |
| LEDC PWM | 蜂鸣器 | 正弦波驱动 |

---

## 十、版本演进

| 版本 | 里程碑 | 关键变更 |
|------|--------|----------|
| v1.0 | 基础通信 | JSON 行格式，单核轮询，基础表情 |
| v1.1 | 显示增强 | 天气面板、Token 统计、弹簧动画 |
| v1.2 | 传感器集成 | BH1750 自动背光、电容触摸、接近唤醒 |
| v2.0 | 双核架构 | FreeRTOS 双核 + 双缓冲、长度前缀帧协议 |
| v2.1 | 省电优化 | CPU 调频、WiFi 省电、Light Sleep、V-Sync |
| v2.2 | 配网完善 | BLE 配网、Web AP 配网、mDNS/UDP 自动发现 |
| v2.3 | OTA 升级 | Web OTA、固件验证、回滚机制 |
| v2.4 | 像素动画 | PXL 格式、Delta 压缩、PSRAM 池预分配 |

---

## 十一、关键配置常量

### 网络配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `SERVER_PORT` | 19876 | TCP 服务器默认端口 |
| `UDP_BROADCAST_PORT` | 19877 | UDP 广播发现端口 |
| `CLIENT_TCP_TIMEOUT` | 5000ms | TCP 连接超时 |
| `RECONNECT_INTERVAL` | 5000ms | 初始重连间隔 |
| `KEEPALIVE_INTERVAL` | 10s | TCP Keep-Alive 探测间隔 |
| `KEEPALIVE_TIMEOUT` | 30s | Keep-Alive 判定超时 |
| `WIFI_TIMEOUT` | 15000ms | WiFi 连接超时 |

### 显示配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `SCREEN_WIDTH` | 240 | 屏幕宽度像素 |
| `SCREEN_HEIGHT` | 240 | 屏幕高度像素 |
| `UPDATE_INTERVAL` | 50ms | 显示刷新间隔 (20fps) |
| `LCD_BRIGHTNESS` | 80% | 默认背光亮度 |

### 省电配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `SCREEN_DIM_TIMEOUT` | 60s | 变暗超时 |
| `SCREEN_SLEEP_TIMEOUT` | 180s | 关屏超时 |
| `LIGHT_SLEEP_TIMEOUT` | 300s | Light Sleep 超时 |
| `OFFLINE_TIMEOUT_MS` | 45000ms | 离线判定超时 |

### 配网配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `AP_SSID` | DeskPet-Config | 热点名称 |
| `AP_PASSWORD` | 12345678 | 热点密码 |
| `CONFIG_PORT` | 80 | Web 配网端口 |
| `CONFIG_TIMEOUT` | 可配置 | 配网页面超时 |
| BLE 广播超时 | 120s | BLE 配网超时 |

### 传感器配置

| 常量 | 值 | 说明 |
|------|-----|------|
| `BH1750_ADDR` | 0x23 | I2C 地址 |
| `TOUCH_PIN` | 可配置 | 电容触摸引脚 |
| `BUZZER_PIN` | 可配置 | 蜂鸣器引脚 |

---

## 十二、技术栈总览

| 层级 | 技术 | 用途 |
|------|------|------|
| MCU | ESP32-S3 | 双核 Xtensa LX7, 2MB PSRAM |
| RTOS | FreeRTOS | 任务调度、双核管理 |
| 框架 | Arduino-ESP32 | GPIO/SPI/I2C/WiFi/BLE 抽象 |
| BLE 库 | NimBLE-Arduino | 低资源 BLE 协议栈 |
| 显示 | TFT_eSPI | SPI LCD 驱动 |
| 传感器 | BH1750 / DRV2605L | 环境光 / 触觉反馈 |
| 通信 | TCP + UDP + mDNS + BLE | 多通道设备发现与数据交换 |
| PC 端 | Python 3 | psutil / pystray / matplotlib |
| 构建 | PlatformIO | 固件编译与烧录 |
| 格式 | PXL (自定义) | 像素动画二进制编码 |
