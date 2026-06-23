# 桌面电子宠物 · 完整部署调试手册 v1.0

> **适用版本**: 当前 main 分支（编译通过 0 错误 0 警告）  
> **目标读者**: 开发者 / 硬件爱好者 / 首次部署人员  
> **预计部署时间**: 2~4 小时（含硬件组装）

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [物料清单与采购](#2-物料清单与采购)
3. [硬件组装与接线](#3-硬件组装与接线)
4. [开发环境搭建](#4-开发环境搭建)
5. [固件编译与烧录](#5-固件编译与烧录)
6. [首次配网（WiFi 配置）](#6-首次配网wifi-配置)
7. [PC 端监控程序部署](#7-pc-端监控程序部署)
8. [软硬件联调](#8-软硬件联调)
9. [功能验证清单](#9-功能验证清单)
10. [进阶：自定义像素动画](#10-进阶自定义像素动画)
11. [故障排查手册](#11-故障排查手册)
12. [生产级部署建议](#12-生产级部署建议)
13. [附录：引脚速查表](#13-附录引脚速查表)

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    PC 端（Windows/macOS/Linux）          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Agent 监控    │  │ Token 统计    │  │ 天气服务      │ │
│  │ (进程检测)    │  │ (JSONL解析)   │  │ (OpenWeather) │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘ │
│         └─────────────────┼─────────────────┘           │
│                    ┌──────┴───────┐                      │
│                    │ 通信模块      │ ← WiFi TCP / 串口   │
│                    │ Server:19876 │                      │
│                    └──────┬───────┘                      │
│                    UDP 广播 (端口 19877)                  │
└────────────────────────────┼────────────────────────────┘
                             │ WiFi / USB 串口
┌────────────────────────────┼────────────────────────────┐
│                  ESP32-S3 设备                           │
│  ┌──────────┐  ┌──────────┴───┐  ┌──────────────────┐  │
│  │ LCD 显示  │  │ Comm Manager │  │ WiFi/BLE 配网    │  │
│  │ 240×240   │  │ (TCP Client) │  │ AP+BLE+UDP+mDNS │  │
│  │ ST7789V   │  └──────────────┘  └──────────────────┘  │
│  └──────────┘                                            │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ BH1750   │  │ DRV2605L     │  │ 触摸 + 旋转编码器│  │
│  │ 光照传感器│  │ 马达振动反馈  │  │ 用户交互输入     │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────┐                                            │
│  │ I2S 音频  │ ← GPIO47 (PDM)                           │
│  └──────────┘                                            │
└──────────────────────────────────────────────────────────┘
```

### 1.1 通信协议

| 层级 | 协议 | 说明 |
|------|------|------|
| 传输层 | WiFi TCP | PC 端作为 Server（`0.0.0.0:19876`），ESP32 作为 Client 主动连接 |
| 帧格式 | `LEN:<n>\n<payload>\n` | 长度前缀帧协议，单帧上限 **16 KB** |
| 消息格式 | JSON | `{ "type": "<msg_type>", "data": {...}, "ts": <epoch> }` |
| 保活 | ping/pong | ESP32 每 **10 秒** 发送 `ping`，PC 端回复 `pong`；**30 秒** 无 pong 视为断连 |
| 发现机制 | UDP 广播 | PC 端每 **5 秒** 向 `255.255.255.255:19877` 广播自身 IP |
| 发现备用 | mDNS | 服务名 `deskpet.local`，ESP32 可通过 mDNS 查询 PC 地址 |

### 1.2 消息类型一览

| type | 方向 | 用途 |
|------|------|------|
| `status` | PC→ESP32 | Agent 运行状态（idle/working/thinking） |
| `token` | PC→ESP32 | Token 使用统计 |
| `weather` | PC→ESP32 | 天气信息（图标+温度+描述） |
| `ping` / `pong` | 双向 | 心跳保活 |
| `pixel_data` | PC→ESP32 | 像素动画帧数据（分包传输） |
| `pixel_cmd` | PC→ESP32 | 像素播放控制（play/stop/pause/resume） |
| `crash_report` | ESP32→PC | 崩溃遥测上报 |
| `state` | ESP32→PC | 设备状态反馈 |

---

## 2. 物料清单与采购

### 2.1 核心器件

| # | 器件 | 型号/规格 | 数量 | 参考价格 | 备注 |
|---|------|-----------|------|----------|------|
| 1 | **主控+屏幕** | 微雪 ESP32-S3 1.54inch LCD Module | 1 | ¥70 | 必须选 **8MB PSRAM** 版本 |
| 2 | USB 数据线 | Type-C（支持数据传输） | 1 | ¥10 | ⚠️ 纯充电线不行 |
| 3 | 光照传感器 | BH1750FVI 模块 | 1 | ¥5 | I2C 接口，地址 0x23 |
| 4 | 触觉马达 | DRV2605L 模块 + LRA 马达 | 1 | ¥25 | I2C 接口，地址 0x5A |
| 5 | 触摸传感器 | TTP223 电容触摸模块 | 1 | ¥3 | 或使用 ESP32 电容触摸引脚 |
| 6 | 旋转编码器 | EC11 带按键旋转编码器 | 1 | ¥5 | 旋转+A/B 相+按压 |
| 7 | 蜂鸣器 | 无源蜂鸣器模块 | 1 | ¥3 | 由 I2S PDM GPIO47 驱动 |

### 2.2 连接线材

| 器件 | 线材 | 数量 |
|------|------|------|
| BH1750 / DRV2605L | 母对母杜邦线 | 4 根（SDA/SCL/VCC/GND 共用） |
| 触摸传感器 | 母对母杜邦线 | 3 根（SIG/VCC/GND） |
| 旋转编码器 | 母对母杜邦线 | 5 根（A/B/SW/VCC/GND） |
| 蜂鸣器 | 母对母杜邦线 | 2 根（SIG/GND） |

### 2.3 预算总览

| 项目 | 金额 |
|------|------|
| ESP32-S3 LCD 模块 | ¥70 |
| 外围传感器模块 | ¥40 |
| 线材 + USB 线 | ¥15 |
| 3D 外壳（可选） | ¥30~50 |
| **合计** | **¥125~175** |

### 2.4 采购注意事项

> ⚠️ **关键提醒**
> 1. ESP32-S3 模块必须选 **1.54 inch** 版本，不要选 1.28 inch 圆屏版
> 2. 确认选 **8MB PSRAM**（用于动画帧缓存），4MB 版本会 OOM
> 3. BH1750 和 DRV2605L 共享 I2C 总线，地址不冲突（0x23 vs 0x5A）
> 4. USB 线必须支持数据传输，纯充电线无法烧录

---

## 3. 硬件组装与接线

### 3.1 引脚分配速查

```
┌─────────────────────────────────────────────────────┐
│                ESP32-S3 引脚分配                      │
├─────────────┬───────────┬───────────────────────────┤
│ 功能         │ GPIO 引脚  │ 说明                      │
├─────────────┼───────────┼───────────────────────────┤
│ LCD SCLK     │ 10        │ SPI 时钟                  │
│ LCD MOSI     │ 11        │ SPI 数据                  │
│ LCD CS       │ 12        │ SPI 片选                  │
│ LCD DC       │ 13        │ 数据/命令切换              │
│ LCD RST      │ 14        │ LCD 复位                  │
│ LCD BL       │ 21        │ 背光 PWM (通道7)           │
├─────────────┼───────────┼───────────────────────────┤
│ I2C SDA      │ 41        │ BH1750 + DRV2605L 共用    │
│ I2C SCL      │ 42        │ BH1750 + DRV2605L 共用    │
├─────────────┼───────────┼───────────────────────────┤
│ Touch        │ 4 (T0)    │ 电容触摸输入               │
│ Encoder A    │ 5         │ 旋转编码器 A 相            │
│ Encoder B    │ 6         │ 旋转编码器 B 相            │
│ Encoder SW   │ (编码器按键)│ 旋转编码器按压             │
├─────────────┼───────────┼───────────────────────────┤
│ Buzzer/I2S   │ 47        │ PDM 音频输出               │
├─────────────┼───────────┼───────────────────────────┤
│ USB D+/D-    │ 内置       │ Type-C 烧录/串口           │
└─────────────┴───────────┴───────────────────────────┘
```

### 3.2 接线图

```
                    ESP32-S3 1.54" LCD Module
                   ┌──────────────────────────┐
                   │    ┌──────────────┐       │
                   │    │  1.54" LCD   │       │
                   │    │  240×240     │       │
                   │    │  ST7789V     │       │
                   │    └──────────────┘       │
                   │                            │
                   │  GPIO41 (SDA)──┬───────────┼──── BH1750 SDA
                   │  GPIO42 (SCL)──┼───────────┼──── BH1750 SCL
                   │                │           │     ┌─────────┐
                   │                ├───────────┼──── │ BH1750  │
                   │                │           │     │ VCC→3.3V│
                   │                │           │     │ GND→GND │
                   │                │           │     └─────────┘
                   │                │           │
                   │                └───────────┼──── DRV2605L SDA
                   │                └───────────┼──── DRV2605L SCL
                   │                            │     ┌──────────┐
                   │                            ├──── │ DRV2605L │
                   │                            │     │ VCC→3.3V │
                   │                            │     │ GND→GND  │
                   │                            │     │ OUT→LRA  │
                   │                            │     └──────────┘
                   │                            │
                   │  GPIO4  (T0)───────────────┼──── TTP223 触摸 OUT
                   │  GPIO5  ───────────────────┼──── EC11 A 相
                   │  GPIO6  ───────────────────┼──── EC11 B 相
                   │                            │
                   │  GPIO47 ───────────────────┼──── 蜂鸣器 SIG
                   │                            │
                   │       [Type-C USB]          │
                   └────────────────────────────┘
                           │
                           │ USB 数据线
                           ▼
                      PC (烧录/供电/串口)
```

### 3.3 I2C 总线接线说明

BH1750 和 DRV2605L **共享同一条 I2C 总线**（GPIO41/42），接线时将两个模块的 SDA 和 SCL 分别并联：

```
GPIO41 ───┬──── BH1750 SDA
          └──── DRV2605L SDA

GPIO42 ───┬──── BH1750 SCL
          └──── DRV2605L SCL

3.3V ─────┬──── BH1750 VCC
          └──── DRV2605L VCC

GND  ─────┬──── BH1750 GND
          └──── DRV2605L GND
```

> 💡 **提示**: I2C 总线无需额外上拉电阻，ESP32 内部上拉已启用，且 BH1750/DRV2605L 模块通常自带上拉。

### 3.4 组装顺序建议

1. **先测试裸板**：不接任何外部器件，仅 USB 供电，确认 ESP32-S3 能正常进入配网模式（屏幕亮起显示 AP 信息）
2. **接 BH1750**：验证 I2C 通信正常（串口日志可看到光照值）
3. **接触摸传感器**：验证触摸事件响应
4. **接编码器**：验证旋转和按压事件
5. **接 DRV2605L + LRA 马达**：验证振动反馈
6. **接蜂鸣器**：验证音频输出
7. **全部接好后**：整机联调

---

## 4. 开发环境搭建

### 4.1 必需软件

| 软件 | 版本要求 | 用途 |
|------|----------|------|
| **VS Code** | 最新版 | IDE |
| **PlatformIO IDE 插件** | 最新版 | 编译/烧录/串口监视 |
| **Python** | ≥ 3.8 | PC 端监控程序 |
| **Git** | 任意版本 | 代码管理 |

### 4.2 PlatformIO 插件安装

1. 打开 VS Code → 扩展商店（`Ctrl+Shift+X`）
2. 搜索 `PlatformIO IDE` → 安装
3. 等待 PlatformIO 核心自动安装完成（首次约 5~10 分钟）
4. 安装完成后重启 VS Code

### 4.3 项目配置文件说明

项目使用 `platformio.ini` 配置：

```ini
[env:esp32s3]
platform = espressif32              # ESP32 平台
board = esp32-s3-devkitc-1          # 开发板型号
framework = arduino                 # Arduino 框架

lib_deps = 
    lovyan03/LovyanGFX@^1.1.8       # LCD 显示驱动
    bblanchon/ArduinoJson@^6.21.0    # JSON 解析
    ESPmDNS                         # mDNS 服务发现
    h2zero/NimBLE-Arduino@^1.4.0   # BLE 配网

monitor_speed = 115200              # 串口波特率
upload_speed = 921600               # 烧录速度
board_build.partitions = huge_app.csv  # 大 APP 分区（OTA 友好）
board_build.filesystem = littlefs   # 文件系统
board_build.arduino.memory_type = qio_opi  # PSRAM OPI 模式

build_flags = 
    -DBOARD_HAS_PSRAM               # 启用 PSRAM
    -DARDUINO_USB_MODE=1            # USB CDC 模式
    -DARDUINO_USB_CDC_ON_BOOT=1     # 开机启用 USB 串口
    -std=c++17                      # C++17 标准
```

### 4.4 Python 环境（PC 端）

```bash
# 进入 PC 端目录
cd plan_desktop_pet/pc_monitor

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -r ../requirements.txt
```

**依赖列表**（requirements.txt）：
- `pyserial` — 串口通信
- `requests` — HTTP 请求（天气 API）
- `psutil` — 进程监控
- 其他见 `requirements.txt`

---

## 5. 固件编译与烧录

### 5.1 编译固件

```bash
# 方式一：VS Code PlatformIO
# 打开项目文件夹 → 点击底部工具栏 ✓ (Build)

# 方式二：命令行
cd plan_desktop_pet/esp32_firmware
pio run
```

**预期输出**：
```
RAM:   [=====     ]  51.1% (used 167420 bytes from 327680 bytes)
Flash: [===       ]  32.1% (used 1010985 bytes from 3145728 bytes)
========================= [SUCCESS] Took 20.62 seconds =========================
```

> ⚠️ 首次编译会自动下载 ESP32 工具链和库依赖，耗时 5~15 分钟属正常。

### 5.2 烧录固件

1. 用 Type-C USB 线连接 ESP32-S3 到电脑
2. 确认设备管理器中出现串口（Windows: `COMx`，macOS: `/dev/cu.usbmodem*`，Linux: `/dev/ttyACM*`）

```bash
# 方式一：VS Code
# 点击底部工具栏 → (Upload)

# 方式二：命令行
pio run --target upload
```

**烧录参数**：
- 波特率：921600
- 芯片：ESP32-S3（自动检测 USB-JTAG）
- 烧录方式：USB CDC（无需外部烧录器）

### 5.3 烧录失败排查

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| 找不到串口 | USB 线是纯充电线 | 换支持数据传输的 Type-C 线 |
| 找不到串口 | 驱动未安装 | 安装 CP2102/CH340 驱动（看模块型号） |
| 烧录超时 | 未进入下载模式 | 按住 BOOT 键 → 按一下 RST → 松开 BOOT |
| `Failed to connect` | 串口被占用 | 关闭串口监视器/其他程序 |
| `A fatal error occurred: Wrong boot mode` | USB-JTAG 模式冲突 | 按 BOOT 进入下载模式后重试 |

### 5.4 串口监视

```bash
# 命令行
pio device monitor

# 或 VS Code 底部 → 🔌 (Serial Monitor)
```

**串口参数**：波特率 `115200`，数据位 8，停止位 1，无校验

首次启动后，串口应输出类似：
```
=== ESP32 Desktop Pet ===
PSRAM: 8388608 bytes
[WiFiManager] No saved config, starting AP mode...
[WebConfig] AP started: Pet-Setup (12345678)
[WebConfig] Config page: http://192.168.4.1
[BLEConfig] BLE started, name: DeskPet-XXXX
[TouchHandler] Calibrated baseline: 12345
[SoundManager] Ready
[HapticDriver] DRV2605L initialized (LRA)
[DisplayManager] LCD initialized
```

---

## 6. 首次配网（WiFi 配置）

ESP32 首次启动时没有 WiFi 配置，会自动进入配网模式。提供 **三种配网方式**：

### 6.1 方式一：Web AP 配网（推荐）

**适用场景**：最通用，任何有浏览器的设备均可操作

1. ESP32 上电后自动创建热点：
   - **SSID**: `Pet-Setup`
   - **密码**: `12345678`
2. 用手机/电脑连接此热点
3. 浏览器打开 `http://192.168.4.1`
4. 在配网页面中填写：
   - **WiFi SSID**：你的路由器 WiFi 名称
   - **WiFi 密码**：你的路由器 WiFi 密码
   - **PC 服务器地址**：PC 的局域网 IP（如 `192.168.1.100`）
   - **PC 服务器端口**：`19876`（默认）
5. 点击「保存并连接」
6. ESP32 会自动重启，连接到你的 WiFi，并尝试连接 PC

> 💡 **提示**：配网信息保存在 Flash（NVS）中，断电不丢失。如需重新配网，在启动时长按触摸区域进入配网模式。

### 6.2 方式二：BLE 蓝牙配网

**适用场景**：无法连接 AP 热点时（如手机无法切换 WiFi）

BLE 服务 UUID: `0x1820`，特征值：

| UUID | 名称 | 权限 | 说明 |
|------|------|------|------|
| `0x2A69` | WiFi SSID | 读/写 | 设置 WiFi 名称 |
| `0x2A6A` | WiFi Password | 写 | 设置 WiFi 密码 |
| `0x2A6B` | Resource URL | 写 | 资源服务器 URL（可选） |
| `0x2A6C` | Status | 读/通知 | 配网状态 |

**操作步骤**：
1. 使用 nRF Connect 等 BLE 工具扫描，设备名 `DeskPet-XXXX`
2. 连接设备
3. 向 `0x2A69` 写入 WiFi SSID
4. 向 `0x2A6A` 写入 WiFi 密码
5. 监听 `0x2A6C` 通知，状态码：
   - `0x01` — 配网中
   - `0x02` — WiFi 连接成功
   - `0x03` — 连接失败

### 6.3 方式三：UDP 自动发现

**适用场景**：ESP32 和 PC 已在同一局域网，但不知道 PC 的 IP

1. PC 端监控程序启动后，每 5 秒向 UDP `255.255.255.255:19877` 广播自身 IP
2. ESP32 启动时自动监听 UDP 广播（超时 15 秒）
3. 收到广播后自动提取 PC IP 并发起 TCP 连接

> ⚠️ UDP 自动发现要求 ESP32 和 PC 在**同一子网**。如果路由器隔离了广播，需手动配置 PC IP。

### 6.4 配网验证

配网成功后，串口日志应显示：
```
[WiFiManager] Connected to WiFi: YourSSID (192.168.1.50)
[WiFiManager] mDNS: deskpet.local
[CommManager] Connecting to 192.168.1.100:19876...
[CommManager] Connected!
```

屏幕应显示正常表情界面（不再显示配网提示）。

---

## 7. PC 端监控程序部署

### 7.1 配置文件

编辑 `pc_monitor/config/config.json`：

```json
{
  "agent_monitor": {
    "process_names": ["claudecode", "codex", "python"],
    "check_interval": 2,
    "log_file": "agent_status.log"
  },
  "token_stats": {
    "enabled": true,
    "log_paths": [
      "D:/your/project/path/logs"
    ],
    "update_interval": 30,
    "auto_discover": true,
    "auto_discover_dirs": ["~/.claude/projects"],
    "auto_discover_pattern": "*.jsonl"
  },
  "weather": {
    "enabled": true,
    "api_key": "YOUR_OPENWEATHER_API_KEY",
    "city": "Beijing",
    "update_interval": 1800,
    "cache_file": "weather_cache.json"
  },
  "communication": {
    "mode": "wifi",
    "serial_port": "COM3",
    "serial_baud": 115200,
    "wifi_host": "0.0.0.0",
    "wifi_port": 19876,
    "retry_interval": 5
  },
  "display": {
    "update_interval": 1,
    "animation_enabled": true
  }
}
```

**关键配置说明**：

| 字段 | 说明 |
|------|------|
| `communication.mode` | `"wifi"` 或 `"serial"`，WiFi 模式为默认推荐 |
| `communication.wifi_host` | 监听地址，`"0.0.0.0"` 表示接受任意来源连接 |
| `communication.wifi_port` | 监听端口，`19876`（与 ESP32 配网时填写的端口一致） |
| `weather.api_key` | OpenWeatherMap API Key，前往 https://openweathermap.org/api 免费申请 |
| `weather.city` | 城市名，如 `"Beijing"`, `"Shanghai"` |
| `token_stats.log_paths` | Agent 日志目录路径，PC 程序从中解析 Token 使用情况 |

### 7.2 启动 PC 端

```bash
cd plan_desktop_pet/pc_monitor
python main.py
```

**预期输出**：
```
[INFO] Desktop Pet Monitor v1.0 starting...
[INFO] Communication mode: wifi
[INFO] TCP Server listening on 0.0.0.0:19876
[INFO] UDP broadcast started on port 19877
[INFO] Agent monitor started (processes: claudecode, codex, python)
[INFO] Weather service started (city: Beijing, interval: 1800s)
[INFO] Waiting for ESP32 connection...
[INFO] ESP32 connected from 192.168.1.50:xxxxx
[INFO] Sending initial state update...
```

### 7.3 串口模式（备选）

如果 WiFi 不可用，可使用 USB 串口直连：

1. 修改 `config.json`：`"mode": "serial"`, `"serial_port": "COM3"`（改为实际端口）
2. ESP32 通过 USB 连接 PC
3. 启动 PC 端程序

> ⚠️ 串口模式下 ESP32 和 PC 通过 USB 线直连，无法使用 WiFi 自动发现。

### 7.4 开机自启（Windows）

创建快捷方式放入启动文件夹：

```powershell
# 打开启动文件夹
shell:startup

# 创建快捷方式，目标：
pythonw D:\path\to\plan_desktop_pet\pc_monitor\main.py
```

使用 `pythonw` 而非 `python`，避免弹出命令行窗口。

---

## 8. 软硬件联调

### 8.1 联调流程图

```
ESP32 上电
    │
    ▼
配网模式 ──(WiFi配置)──▶ 连接路由器
    │                        │
    ▼                        ▼
启动 UDP 监听 ◀──── PC 端 UDP 广播
    │
    ▼
TCP 连接 PC ──(握手)──▶ 通信建立
    │
    ▼
┌───────────────────────────────────┐
│          正常运行循环              │
│                                   │
│  PC 发送:                         │
│    • status (每 2 秒)             │
│    • token  (每 30 秒)            │
│    • weather (每 30 分钟)         │
│    • pixel_data (按需)            │
│                                   │
│  ESP32 处理:                      │
│    • 更新显示（表情/状态/天气）    │
│    • 触摸/编码器交互              │
│    • 光照自适应亮度               │
│    • 触觉反馈                     │
│    • 音效播放                     │
│                                   │
│  保活: ping(10s) / pong(30s)      │
│  断线: 自动重连（指数退避）        │
└───────────────────────────────────┘
```

### 8.2 联调检查点

#### 阶段一：连接建立

| # | 检查项 | 预期结果 | 验证方式 |
|---|--------|----------|----------|
| 1 | ESP32 连上 WiFi | 串口显示 IP 地址 | 串口监视器 |
| 2 | ESP32 连接 PC | 串口显示 `Connected!` | 串口监视器 |
| 3 | PC 端收到连接 | 日志显示 `ESP32 connected` | PC 终端 |

#### 阶段二：数据收发

| # | 检查项 | 预期结果 | 验证方式 |
|---|--------|----------|----------|
| 4 | PC 发送 status | ESP32 屏幕显示对应表情 | 目视屏幕 |
| 5 | PC 发送 weather | 屏幕显示天气图标+温度 | 目视屏幕 |
| 6 | PC 发送 token | 屏幕显示 Token 柱状图 | 目视屏幕 |
| 7 | 心跳正常 | 不出现断连重连日志 | 双端日志 |

#### 阶段三：交互功能

| # | 检查项 | 预期结果 | 验证方式 |
|---|--------|----------|----------|
| 8 | 触摸 | 触发表情切换/振动反馈 | 触摸+观察 |
| 9 | 编码器旋转 | 调节亮度或切换模式 | 旋转+观察 |
| 10 | 光照自适应 | 遮挡传感器 → 屏幕变暗 | 遮挡 BH1750 |
| 11 | 音效 | 触发事件时蜂鸣器响 | 触摸或状态变更 |

#### 阶段四：稳定性

| # | 检查项 | 预期结果 | 验证方式 |
|---|--------|----------|----------|
| 12 | 断网恢复 | 拔网线再插回，自动重连 | 拔线→等待→看日志 |
| 13 | 长时间运行 | 连续运行 24h+ 无崩溃/内存泄漏 | 隔夜测试 |
| 14 | 热重启 | 按 RST 后自动恢复正常 | 按 RST |

---

## 9. 功能验证清单

### 9.1 显示模块 ✅

- [ ] 屏幕亮起，亮度可调（编码器旋转控制）
- [ ] 表情动画播放流畅（60 FPS 目标）
- [ ] 天气图标正确渲染
- [ ] Token 柱状图正确显示
- [ ] 状态栏信息更新及时（≤2 秒延迟）
- [ ] 模式切换有淡入淡出效果（16 帧渐变）
- [ ] 接近唤醒亮屏（手靠近传感器）

### 9.2 通信模块 ✅

- [ ] WiFi 连接稳定
- [ ] TCP 帧协议收发正常（LEN: 前缀）
- [ ] 心跳 ping/pong 不超时
- [ ] 断线自动重连（指数退避，最大间隔 60 秒）
- [ ] UDP 广播发现 PC
- [ ] mDNS 解析正常（`deskpet.local`）

### 9.3 交互模块 ✅

- [ ] 触摸单击响应（切换表情）
- [ ] 触摸双击响应
- [ ] 触摸长按响应（进入设置）
- [ ] 接近感应灵敏（20~50mm 检测距离）
- [ ] 旋转编码器顺时针/逆时针正确识别
- [ ] 编码器按压事件

### 9.4 音频/触觉模块 ✅

- [ ] 蜂鸣器能发出不同频率声音
- [ ] 触觉马达 click/buzz 效果明显
- [ ] 自定义波形振动序列

### 9.5 配网模块 ✅

- [ ] AP 模式配网页面正常显示
- [ ] BLE 广播可被手机发现
- [ ] 配网信息持久化（断电重连）
- [ ] 重新配网流程正常（长按触发）

---

## 10. 进阶：自定义像素动画

### 10.1 PXL 文件格式

PXL（PiXeL）是本项目专用的紧凑二进制像素格式：

```
┌─────────────────────────────────────┐
│ 文件头 (16 bytes)                    │
│   Magic: "PXL" (3B)                 │
│   Version: uint8 (1B)               │
│   Flags: uint8 (1B) [bit0=loop]     │
│   Width: uint16 LE (2B)             │
│   Height: uint16 LE (2B)            │
│   FrameCount: uint16 LE (2B)        │
│   FrameDelay: uint16 LE (2B) ms     │
│   Reserved: uint32 (4B)             │
├─────────────────────────────────────┤
│ 帧数据 (N × frame_size bytes)       │
│   支持原始 RGB565 或 RLE 压缩       │
└─────────────────────────────────────┘
```

### 10.2 制作 PXL 文件

```python
"""
将图片序列转换为 PXL 文件
需要: pip install Pillow
"""
import struct
from PIL import Image

def images_to_pxl(image_paths, output_path, size=(32, 32), delay=100, loop=True):
    """将多张图片合并为一个 PXL 动画文件"""
    frames = []
    for path in image_paths:
        img = Image.open(path).convert('RGB').resize(size)
        pixels = img.load()
        frame_data = bytearray()
        for y in range(size[1]):
            for x in range(size[0]):
                r, g, b = pixels[x, y]
                # RGB565: RRRRRGGGGGGBBBBB
                rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                frame_data.extend(struct.pack('<H', rgb565))
        frames.append(bytes(frame_data))
    
    # 写入文件
    with open(output_path, 'wb') as f:
        # 文件头
        magic = b'PXL'
        version = 1
        flags = 0x01 if loop else 0x00
        header = struct.pack('<3sBBHHHBI', 
            magic, version, flags,
            size[0], size[1], len(frames), delay, 0)
        f.write(header)
        # 帧数据
        for frame in frames:
            f.write(frame)
    
    print(f"PXL written: {output_path} ({len(frames)} frames, {size[0]}x{size[1]})")

# 使用示例
images_to_pxl(
    ['frame1.png', 'frame2.png', 'frame3.png', 'frame4.png'],
    'animation.pxl',
    size=(32, 32),
    delay=150,  # 150ms 每帧
    loop=True
)
```

### 10.3 发送像素动画到 ESP32

通过 PC 端通信模块发送 `pixel_data` 消息：

```python
import json
import base64

def send_pxl_animation(sock, pxl_path, chunk_size=4096):
    """分包发送 PXL 文件到 ESP32"""
    with open(pxl_path, 'rb') as f:
        data = f.read()
    
    total_packets = (len(data) + chunk_size - 1) // chunk_size
    
    for i in range(total_packets):
        chunk = data[i * chunk_size : (i + 1) * chunk_size]
        msg = {
            "type": "pixel_data",
            "data": {
                "packet_index": i,
                "total_packets": total_packets,
                "chunk": base64.b64encode(chunk).decode('ascii')
            },
            "ts": time.time()
        }
        frame = f"LEN:{len(json.dumps(msg))}\n{json.dumps(msg)}\n"
        sock.send(frame.encode('utf-8'))
    
    # 发送播放命令
    play_cmd = {
        "type": "pixel_cmd",
        "data": {"action": "play"},
        "ts": time.time()
    }
    frame = f"LEN:{len(json.dumps(play_cmd))}\n{json.dumps(play_cmd)}\n"
    sock.send(frame.encode('utf-8'))
```

---

## 11. 故障排查手册

### 11.1 ESP32 相关

| 症状 | 可能原因 | 排查步骤 | 解决方案 |
|------|----------|----------|----------|
| 屏幕不亮 | 背光引脚/电源 | 1. 检查 USB 供电 2. 串口看启动日志 | 确认 GPIO21 连接背光 |
| 屏幕白屏 | SPI 接线错误 | 检查 GPIO10/11/12/13/14 | 重新接线 |
| 屏幕颜色反转 | ST7789V invert 配置 | 正常现象 | 已在驱动中 `invert=true` 处理 |
| PSRAM 初始化失败 | 选错模块 | 串口看 `PSRAM:` 行 | 确认 8MB PSRAM 版本 |
| 编译报 `PSRAM` 错误 | platformio.ini 配置 | 检查 `memory_type = qio_opi` | 与模块型号匹配 |
| WiFi 连不上 | SSID/密码错误 | 进 AP 配网重配 | 长按触摸重置配网 |
| TCP 连不上 PC | IP/端口不匹配 | 1. `ping` PC IP 2. 检查防火墙 | 开放 19876 端口 |
| 内存不足崩溃 | 动画帧过大 | 串口看 `heap` 日志 | 已内置 16KB 帧限制+OOM 熔断 |
| I2C 设备无响应 | 接线/地址错误 | 串口看 I2C 扫描日志 | 确认 SDA=41, SCL=42 |

### 11.2 PC 端相关

| 症状 | 可能原因 | 排查步骤 | 解决方案 |
|------|----------|----------|----------|
| `ModuleNotFoundError` | 依赖未安装 | `pip install -r requirements.txt` | 激活虚拟环境后重装 |
| `Permission denied` 串口 | 串口被占用 | 关闭串口监视器/其他程序 | 只保留一个连接 |
| 天气不更新 | API Key 无效 | 检查 `config.json` 中 `api_key` | 重新申请 OpenWeather Key |
| Agent 状态不更新 | 进程名不匹配 | 检查 `process_names` 配置 | 添加实际进程名 |
| Token 数据为空 | 日志路径错误 | 检查 `log_paths` 是否存在 | 指向正确的 Agent 日志目录 |
| ESP32 频繁断连 | WiFi 信号弱/keepalive 超时 | 检查 WiFi 信号强度 | 靠近路由器/检查天线 |

### 11.3 联调相关

| 症状 | 可能原因 | 排查步骤 | 解决方案 |
|------|----------|----------|----------|
| ESP32 启动后不连 PC | 未配网/PC 端未启动 | 1. 看串口日志 2. 确认 PC 端在运行 | 先启动 PC 端，再给 ESP32 上电 |
| 数据乱码 | 帧协议不匹配 | 检查 LEN: 前缀格式 | 确认两端使用相同帧协议 |
| 显示延迟高 | 网络延迟/帧率设置 | 1. `ping` ESP32 IP 2. 检查 update_interval | 降低 update_interval 值 |
| UDP 发现失败 | 不在同一子网 | 检查 IP 前三段是否相同 | 手动配置 PC IP |

### 11.4 日志查看方法

**ESP32 串口日志**：
```bash
pio device monitor --baud 115200
```

**PC 端日志**：
```bash
# 日志文件位于
pc_monitor/agent_status.log

# 实时查看
tail -f agent_status.log    # Linux/macOS
Get-Content agent_status.log -Wait  # PowerShell
```

---

## 12. 生产级部署建议

### 12.1 电源管理

| 场景 | 供电方式 | 注意事项 |
|------|----------|----------|
| 开发调试 | USB 供电 | Type-C 口直接供电 |
| 桌面使用 | USB 5V 电源适配器 | 建议 ≥1A 输出 |
| 户外/移动 | 充电宝 | 注意 WiFi 范围限制 |

### 12.2 散热建议

- ESP32-S3 在 240MHz 双核满载时功耗约 200~300mA
- LCD 背光全亮额外约 60mA
- 长时间运行建议：
  - 外壳留通风孔
  - 背光亮度不超过 80%（编码器可调）
  - 避免阳光直射导致 LCD 过热

### 12.3 固件 OTA 升级

项目使用 `huge_app.csv` 分区表，支持 A/B 分区 OTA：

```cpp
// web_config.h 中已实现 OTA 端点
// 访问 http://<esp32-ip>/update 上传新固件
```

OTA 升级流程：
1. 编译新固件：`pio run`
2. 产物路径：`.pio/build/esp32s3/firmware.bin`
3. 浏览器访问 `http://<esp32-ip>/update`
4. 上传 `firmware.bin`
5. 等待自动重启

### 12.4 安全建议

| 风险 | 措施 |
|------|------|
| AP 配网热点暴露 | 配网完成后自动关闭热点；超时 2 分钟自动关闭 |
| TCP 无认证 | 仅限局域网使用；后续可加 token 认证 |
| BLE 配网明文密码 | 配网窗口短（2 分钟）；完成后关闭 BLE 广播 |
| OTA 无签名验证 | 后续可加固件签名验证 |

### 12.5 多设备部署

如需部署多个宠物设备：

1. 每台 ESP32 独立配网，指向同一 PC
2. PC 端可扩展为支持多连接（当前代码已支持）
3. 通过 `comm_manager` 的连接 ID 区分不同设备
4. 每台设备可配置不同角色/表情

---

## 13. 附录：引脚速查表

### 13.1 完整引脚映射（config.h 定义）

| 宏定义 | GPIO | 功能 | 备注 |
|--------|------|------|------|
| `LCD_SCLK` | 10 | SPI 时钟 | LCD 专用 |
| `LCD_MOSI` | 11 | SPI MOSI | LCD 专用 |
| `LCD_MISO` | -1 | SPI MISO | 未使用 |
| `LCD_CS` | 12 | SPI 片选 | LCD 专用 |
| `LCD_DC` | 13 | 数据/命令 | LCD 专用 |
| `LCD_RST` | 14 | LCD 复位 | LCD 专用 |
| `LCD_BL` | 21 | 背光 PWM | 通道 7，44.1KHz |
| `BH1750_SDA_PIN` | 41 | I2C 数据 | 与 DRV2605L 共享 |
| `BH1750_SCL_PIN` | 42 | I2C 时钟 | 与 DRV2605L 共享 |
| `TOUCH_PIN` | 4 | 电容触摸 | T0 通道 |
| `ENCODER_A_PIN` | 5 | 编码器 A 相 | — |
| `ENCODER_B_PIN` | 6 | 编码器 B 相 | — |
| `BUZZER_PIN` | 47 | I2S PDM 输出 | — |

### 13.2 I2C 设备地址

| 设备 | 地址 | 用途 |
|------|------|------|
| BH1750FVI | `0x23` | 光照传感器 |
| DRV2605L | `0x5A` | 触觉马达驱动 |

### 13.3 网络端口

| 端口 | 协议 | 用途 |
|------|------|------|
| 19876 | TCP | PC↔ESP32 主通信 |
| 19877 | UDP | PC 广播发现 |
| 80 | TCP (ESP32 AP) | Web 配网页面 |
| 5353 | UDP | mDNS 服务发现 |

### 13.4 关键时间常量

| 参数 | 值 | 位置 |
|------|-----|------|
| WiFi 连接超时 | 10 秒 | config.h `WIFI_TIMEOUT` |
| 配网超时 | 2 分钟 | config.h `CONFIG_TIMEOUT` |
| 心跳发送间隔 | 10 秒 | communication.py `KEEPALIVE_INTERVAL` |
| 心跳超时判定 | 30 秒 | communication.py `KEEPALIVE_TIMEOUT` |
| 重连间隔（初始） | 5 秒 | config.json `retry_interval` |
| 重连间隔（最大） | 60 秒 | comm_manager 指数退避上限 |
| Agent 状态轮询 | 2 秒 | config.json `check_interval` |
| Token 统计更新 | 30 秒 | config.json `update_interval` |
| 天气更新 | 30 分钟 | config.json `update_interval` |
| 光照读取间隔 | 2 秒 | config.h `BH1750_READ_INTERVAL` |
| UDP 广播间隔 | 5 秒 | communication.py `DEFAULT_UDP_BROADCAST_INTERVAL` |
| 淡入淡出帧数 | 16 帧 | display_manager.h `FADE_FRAMES` |
| 帧长度上限 | 16 KB | comm_manager 帧协议 |
| OOM 熔断阈值 | 16 KB FreeHeap | main.cpp 检查逻辑 |

---

## 快速启动 Checklist

```
□ 1. 采购器件（ESP32-S3 LCD + 传感器模块 + USB 线）
□ 2. 安装 VS Code + PlatformIO 插件
□ 3. 克隆项目，用 PlatformIO 打开
□ 4. 编译固件（pio run）→ 确认 SUCCESS
□ 5. USB 连接 ESP32 → 烧录（pio run --target upload）
□ 6. 串口监视器查看启动日志
□ 7. 手机连接 Pet-Setup 热点 → 浏览器 192.168.4.1 配网
□ 8. PC 端：编辑 config.json → python main.py
□ 9. 等待 ESP32 自动连接 PC → 屏幕显示 Agent 状态
□ 10. 触摸/旋转编码器交互测试
□ 11. 连续运行 24h 稳定性测试
□ 12. （可选）3D 打印外壳组装
```

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-22  
> **项目路径**: `plan_desktop_pet/`  
> **固件路径**: `plan_desktop_pet/esp32_firmware/`  
> **PC端路径**: `plan_desktop_pet/pc_monitor/`
