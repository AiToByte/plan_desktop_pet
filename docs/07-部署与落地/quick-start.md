# 5 分钟快速入门

> **目标**：从零开始，让桌面宠物屏幕亮起来并成功连接 PC。
>
> **预计时间**：5 ~ 15 分钟（不含固件首次编译下载依赖的时间）

---

## 一、准备清单

在动手之前，请确认以下物品和账号已就绪。

### 1.1 硬件

| # | 物品 | 规格说明 | 备注 |
|---|------|----------|------|
| 1 | **ESP32-S3 1.54" LCD 开发板** | 微雪 ESP32-S3 1.54inch LCD Module，**必须选 8MB PSRAM 版本** | 4MB 版本会 OOM 崩溃 |
| 2 | **USB 数据线** | Type-C，支持数据传输 | 纯充电线无法烧录 |
| 3 | PC（Windows / macOS / Linux） | 用于编译烧录和运行监控程序 | — |

> 最低配置只需以上三样即可跑通主流程。光照传感器、触觉马达等外设可后续再接。

### 1.2 软件

| 软件 | 最低版本 | 用途 | 安装方式 |
|------|----------|------|----------|
| **Python** | 3.9+ | PC 端监控程序 | [python.org](https://www.python.org/downloads/) 下载安装 |
| **PlatformIO CLI** | 最新版 | 编译烧录 ESP32 固件 | `pip install platformio` |
| **VS Code**（推荐） | 最新版 | IDE + PlatformIO 插件 | [code.visualstudio.com](https://code.visualstudio.com/) |
| **Git** | 任意版本 | 克隆项目代码 | [git-scm.com](https://git-scm.com/) |

### 1.3 账号

| 账号 | 用途 | 获取方式 |
|------|------|----------|
| **OpenWeatherMap API Key** | 天气显示功能 | 免费注册：[openweathermap.org/api](https://openweathermap.org/api) |

> 如果暂时不需要天气功能，可以跳过此步骤，在配置文件中将 `weather.enabled` 设为 `false`。

---

## 二、硬件连接

### 2.1 LCD 屏幕接线（SPI）

微雪 ESP32-S3 1.54" LCD 模块已将 LCD 集成在开发板上，**无需额外接线**。屏幕通过 SPI 总线与 ESP32-S3 通信，引脚分配如下：

| LCD 引脚 | ESP32 GPIO | 说明 |
|-----------|------------|------|
| SCLK | GPIO 12 | SPI 时钟 |
| MOSI | GPIO 11 | SPI 数据 |
| CS | GPIO 5 | SPI 片选 |
| DC | GPIO 2 | 数据/命令切换 |
| RST | GPIO 4 | LCD 复位 |
| BL | GPIO 48 | 背光 PWM |

> 以上引脚已在固件 `config.h` 中定义，使用微雪官方开发板时无需修改。

### 2.2 USB 连接

1. 将 Type-C USB 数据线一端插入 ESP32-S3 开发板
2. 另一端插入 PC 的 USB 口
3. Windows 用户打开「设备管理器」，确认出现新的 COM 端口（如 `COM3`）
4. macOS 用户确认出现 `/dev/cu.usbmodem*` 设备
5. Linux 用户确认出现 `/dev/ttyACM*` 设备

> 如果设备管理器中没有出现新端口，说明 USB 线是纯充电线，请更换支持数据传输的线。

---

## 三、烧录固件

### 3.1 克隆项目

```bash
git clone <repository-url>
cd plan_desktop_pet
```

### 3.2 编译固件

```bash
cd esp32_firmware
pio run
```

首次编译会自动下载 ESP32 工具链和库依赖（LovyanGFX、ArduinoJson、NimBLE-Arduino 等），耗时 5 ~ 15 分钟属正常。

编译成功后应看到：

```
RAM:   [=====     ]  51.1% (used 167420 bytes from 327680 bytes)
Flash: [===       ]  32.1% (used 1010985 bytes from 3145728 bytes)
========================= [SUCCESS] Took 20.62 seconds =========================
```

### 3.3 烧录到开发板

确保 USB 已连接 ESP32-S3，然后执行：

```bash
pio run -t upload
```

烧录参数：波特率 921600，通过 USB CDC 自动烧录，无需外部烧录器。

### 3.4 验证烧录

烧录完成后，打开串口监视器查看启动日志：

```bash
pio device monitor
```

预期输出：

```
=== ESP32 Desktop Pet ===
PSRAM: 8388608 bytes
[WiFiManager] No saved config, starting AP mode...
[WebConfig] AP started: Pet-Setup (12345678)
[DisplayManager] LCD initialized
```

看到 `LCD initialized` 说明固件烧录成功，屏幕应该已经亮起。

---

## 四、启动 PC 端

### 4.1 安装 Python 依赖

```bash
cd pc_monitor
pip install -r requirements.txt
```

依赖列表：`psutil`（进程监控）、`requests`（HTTP 请求）、`pyserial`（串口通信）。

### 4.2 创建配置文件

```bash
cp config/config.example.json config/config.json
```

编辑 `config/config.json`，至少修改以下字段：

```json
{
  "weather": {
    "api_key": "你的 OpenWeatherMap API Key",
    "city": "Beijing"
  },
  "token_stats": {
    "log_paths": ["你的 Agent 日志目录路径"]
  }
}
```

> 如果暂时不需要天气和 Token 统计，可保持默认值，不影响核心功能。

### 4.3 启动监控程序

```bash
python main.py
```

预期输出：

```
[INFO] Desktop Pet Monitor v1.0 starting...
[INFO] Communication mode: wifi
[INFO] TCP Server listening on 0.0.0.0:19876
[INFO] UDP broadcast started on port 19877
[INFO] Waiting for ESP32 connection...
```

PC 端已就绪，正在等待 ESP32 连接。

---

## 五、配网

ESP32 首次启动时没有 WiFi 配置，会自动进入配网模式。本节介绍最常用的 **Web AP 配网**方式。

### 5.1 连接设备热点

1. ESP32 上电后自动创建 WiFi 热点：
   - **SSID**: `Pet-Setup`
   - **密码**: `12345678`
2. 用手机或电脑连接此热点

### 5.2 打开配网页面

浏览器访问 `http://192.168.4.1`，打开配网页面。

### 5.3 填写配置

在配网页面中填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| WiFi SSID | 你的路由器 WiFi 名称 | `MyHomeWiFi` |
| WiFi 密码 | 你的路由器 WiFi 密码 | `mypassword123` |
| PC 服务器地址 | PC 的局域网 IP 地址 | `192.168.1.100` |
| PC 服务器端口 | TCP 通信端口 | `19876`（默认） |

> **如何查看 PC 的局域网 IP？**
> - Windows: `ipconfig` → 找到「以太网适配器」或「无线局域网适配器」的 IPv4 地址
> - macOS/Linux: `ifconfig` 或 `ip addr`

### 5.4 保存并连接

点击「保存并连接」，ESP32 会自动重启并连接到你的 WiFi，然后尝试连接 PC 端。

> 配网信息保存在 Flash（NVS）中，断电不丢失。如需重新配网，在启动时长按触摸区域进入配网模式。

---

## 六、验证

配网成功后，检查以下两项确认系统正常工作。

### 6.1 检查 LCD 屏幕

ESP32 屏幕应显示正常的表情界面（不再显示配网提示），包含：
- 表情动画（工作/空闲状态）
- 状态栏信息

### 6.2 检查 PC 端连接

在 PC 终端中应看到：

```
[INFO] ESP32 connected from 192.168.1.50:xxxxx
[INFO] Sending initial state update...
```

如果看到 `ESP32 connected`，说明软硬件通信已建立，桌面宠物系统正常运行。

### 6.3 串口日志确认

ESP32 串口日志应显示：

```
[WiFiManager] Connected to WiFi: YourSSID (192.168.1.50)
[CommManager] Connecting to 192.168.1.100:19876...
[CommManager] Connected!
```

---

## 七、常见卡点速查

遇到问题时，根据症状快速定位原因并解决。

### 7.1 编译烧录阶段

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| `pio: command not found` | PlatformIO 未安装或未加入 PATH | 执行 `pip install platformio`，重启终端 |
| 找不到串口 | USB 线是纯充电线 | 换一根支持数据传输的 Type-C 线 |
| 找不到串口 | 驱动未安装 | 安装 CP2102 或 CH340 驱动（取决于模块型号） |
| 烧录超时 | 未进入下载模式 | 按住 BOOT 键 → 按一下 RST → 松开 BOOT |
| `Failed to connect` | 串口被其他程序占用 | 关闭串口监视器或其他串口工具 |
| 编译报 PSRAM 错误 | platformio.ini 配置不对 | 确认 `memory_type = qio_opi`，且开发板为 8MB PSRAM 版 |
| 首次编译很慢 | 正在下载工具链和库 | 等待 5 ~ 15 分钟，属正常现象 |

### 7.2 配网阶段

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| 手机搜不到 `Pet-Setup` 热点 | ESP32 未进入配网模式 | 长按触摸区域 3 秒，或重新上电 |
| 配网页面打不开 | 未连接到 `Pet-Setup` 热点 | 先连接热点，再访问 `192.168.4.1` |
| 配网后连不上 WiFi | SSID 或密码填错 | 重新配网，注意区分大小写 |
| 配网后连不上 PC | PC IP 地址填错 | 确认 PC 的局域网 IP，确保 PC 端已启动 |

### 7.3 通信连接阶段

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| ESP32 不连 PC | PC 端监控程序未启动 | 先启动 `python main.py`，再给 ESP32 上电 |
| 连接后频繁断开 | WiFi 信号弱 | 将 ESP32 靠近路由器 |
| 连接后频繁断开 | 防火墙阻止 | 开放 TCP 端口 19876 入站规则 |
| UDP 自动发现失败 | 不在同一子网 | 手动在配网页面填写 PC IP |
| 天气不显示 | API Key 未配置 | 在 `config.json` 中填入 OpenWeatherMap API Key |
| Agent 状态不更新 | 进程名不匹配 | 在 `config.json` 的 `process_names` 中添加实际进程名 |

### 7.4 显示问题

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| 屏幕完全不亮 | 背光未开启或供电异常 | 检查 USB 供电，查看串口日志中是否有 `LCD initialized` |
| 屏幕白屏 | SPI 接线错误（自定义板） | 检查 GPIO 引脚定义是否与硬件匹配 |
| 动画卡顿 | 帧率过低 | 检查 ESP32 是否过热，降低动画复杂度 |
| 中文乱码 | 字体配置问题 | 确认 LovyanGFX 配置了中文字体 |

### 7.5 日志调试方法

```bash
# ESP32 串口日志
pio device monitor --baud 115200

# PC 端日志（实时查看）
# Windows PowerShell
Get-Content agent_status.log -Wait

# Linux / macOS
tail -f agent_status.log
```

---

## 下一步

快速入门完成后，可以继续探索：

- **自定义像素动画**：使用 `pixel_tool` 将 PNG/GIF 转换为 PXL 格式并发送到设备
- **详细部署手册**：参考 [deployment-guide.md](./deployment-guide.md) 了解完整部署流程
- **通信协议**：参考 [communication-protocol.md](../01-技术架构/communication-protocol.md) 了解消息格式
- **硬件接线**：参考 [hardware-wiring.md](../02-硬件指南/hardware-wiring.md) 了解外设扩展接线

---

> **文档版本**: v1.0
> **最后更新**: 2026-06-24
