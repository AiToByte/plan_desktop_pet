# 🐾 Desktop Pet - AI Agent Status Display

<p align="center">
<b>基于 ESP32-S3 LCD 的桌面电子宠物，实时监控 AI Agent 工作状态</b>
</p>

<p align="center">
<img src="https://img.shields.io/badge/Platform-ESP32--S3-blue?logo=espressif" alt="Platform">
<img src="https://img.shields.io/badge/Language-C%2B%2B%20%7C%20Python-yellow" alt="Language">
<img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License">
</p>

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🤖 **Agent 状态监控** | 实时检测 AI Agent 进程，显示 工作/空闲/需授权/离线 状态 |
| 📊 **Token 统计** | 自动统计 Token 消耗、请求数、费用估算 |
| 🌤️ **天气显示** | OpenWeatherMap API 实时天气 + 天气图标 |
| 🎭 **动画表情** | 工作/空闲/眨眼等可爱动画效果 |
| 🎨 **自定义像素** | 支持用户自定义 32×32 像素图片/GIF 显示（点阵屏效果） |
| 📡 **WiFi 通信** | PC ↔ ESP32 WiFi TCP 通信，支持自动重连 |

## 📷 界面预览

```
┌────────────────────────┐
│ Desktop Pet    ESP32-S3 │  ← 标题栏
├────────────────────────┤
│ ● WORKING              │  ← 状态指示
│ claudecode             │  ← 进程名
│ CPU:45%  MEM:128MB     │  ← 资源占用
├────────────────────────┤
│ ☀️  22.5°C  晴         │  ← 天气面板
│ 北京  H:45% W:3.5m/s   │
├────────────────────────┤
│ Tokens: 23000          │  ← Token 统计
│ Requests: 42   $0.35   │
├────────────────────────┤
│    ⚪  ⚪  ⚪           │  ← 动画区域
└────────────────────────┘
```

## 🏗️ 项目结构

```
plan_desktop_pet/
├── pc_monitor/                  # PC 端 Python 监控程序
│   ├── main.py                  # 主入口
│   ├── requirements.txt         # Python 依赖
│   └── config/
│       └── config.example.json  # 配置文件模板
│
├── esp32_firmware/              # ESP32 固件 (PlatformIO)
│   ├── platformio.ini
│   ├── include/
│   │   └── config.h             # WiFi/服务器配置
│   └── src/
│       ├── main.cpp             # 主程序入口
│       ├── display_manager.*    # 屏幕显示管理
│       ├── pixel_player.*       # 自定义像素播放器
│       ├── wifi_manager.*       # WiFi 连接管理
│       ├── weather.*            # 天气数据处理
│       └── config.*             # 配置管理
│
├── pixel_tool/                  # PC 端像素工具
│   ├── pixel_tool.py            # CLI 工具入口
│   ├── pxl_encoder.py           # PNG/GIF → PXL 编码器
│   ├── pxl_sender.py            # WiFi 发送器
│   ├── requirements.txt         # Python 依赖
│   └── examples/                # 示例 .pxl 文件
│
└── docs/
    ├── communication_protocol.md  # 通信协议文档
    └── pxl_format.md              # PXL 文件格式规范
```

## 🚀 快速开始

### 环境要求

- **PC 端**: Python 3.9+, pip
- **ESP32 端**: PlatformIO, [微雪 ESP32-S3 1.54inch LCD](https://www.waveshare.com/1.54inch-lcd-module.htm)

### 1. 烧录 ESP32 固件

```bash
# 安装 PlatformIO CLI
pip install platformio

# 配置 WiFi（修改 esp32_firmware/include/config.h）
#define WIFI_SSID     "your_wifi"
#define WIFI_PASSWORD "your_password"
#define SERVER_HOST   "192.168.x.x"  # PC 的 IP 地址

# 编译并烧录
cd esp32_firmware
pio run -t upload
pio run -t uploadfs  # 上传图片资源
```

### 2. 启动 PC 监控程序

```bash
cd pc_monitor

# 安装依赖
pip install -r requirements.txt

# 创建配置文件（根据实际情况修改）
cp config/config.example.json config/config.json
# 编辑 config.json，填写你的 log_paths、weather api_key 等

# 启动
python main.py
```

### 3. 发送自定义像素（可选）

```bash
cd pixel_tool

# 安装依赖
pip install -r requirements.txt

# 转换图片为 .pxl 格式
python pixel_tool.py convert heart.png -o heart.pxl

# 发送到 ESP32
python pixel_tool.py send heart.pxl 192.168.1.100

# 停止自定义像素，返回正常表情
python pixel_tool.py cmd stop 192.168.1.100
```

## 📖 详细文档

| 文档 | 路径 |
|------|------|
| 通信协议 | [`docs/communication_protocol.md`](docs/communication_protocol.md) |
| PXL 格式规范 | [`docs/pxl_format.md`](docs/pxl_format.md) |
| 像素工具使用 | [`pixel_tool/README.md`](pixel_tool/README.md) |
| 硬件接线指南 | [`hardware_guide.md`](hardware_guide.md) |

## 🔧 配置说明

### PC 端 (config.json)

> ⚠️ 不要直接提交 `config.json`，使用 `config.example.json` 作为模板。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `agent_monitor.process_names` | 监控的进程名列表 | claudecode, codex, ooencode |
| `agent_monitor.check_interval` | 检查间隔（秒） | 2 |
| `weather.api_key` | OpenWeatherMap API Key | - |
| `weather.city` | 城市名 | Beijing |
| `communication.wifi_port` | TCP 通信端口 | 19876 |

### ESP32 端 (config.h)

| 配置项 | 说明 |
|--------|------|
| `WIFI_SSID` / `WIFI_PASSWORD` | WiFi 凭据 |
| `SERVER_HOST` | PC 端 IP 地址 |
| `SERVER_PORT` | TCP 端口（需与 PC 一致） |

## ❓ 故障排除

### 连接问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| ESP32 无法连接 WiFi | SSID/密码错误 | 检查 `config.h` 中的 WiFi 配置 |
| ESP32 连接后断开 | 防火墙阻止 | 添加 19876 端口入站规则 |
| 串口连接失败 | 端口被占用 | 关闭其他串口工具，检查端口号 |
| WiFi连接超时 | 网络不稳定 | 检查PC和ESP32是否在同一网络 |

### 数据问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 无法检测 Agent 进程 | 进程名不匹配 | 修改 `config.json` 中的 `process_names` |
| 天气不显示 | API 密钥未配置 | 填入 OpenWeatherMap API Key |
| Token统计不准 | 日志路径错误 | 检查 `token_stats.log_file` 配置 |
| 数据不更新 | 定时器配置错误 | 调整 `check_interval` 参数 |

### 显示问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 屏幕无显示 | 接线错误 | 参考 `hardware_guide.md` |
| 中文乱码 | 字体缺失 | 确保 LovyanGFX 配置了中文字体 |
| 动画卡顿 | 帧率过低 | 检查ESP32性能，降低动画复杂度 |
| 像素图片不显示 | 格式错误 | 使用pixel_tool转换，确保PXL格式正确 |

### 日志调试

```bash
# 查看PC端日志
tail -f pc_monitor.log

# 查看ESP32串口日志
# Windows
type COM3
# Linux/Mac
screen /dev/ttyUSB0 115200
```

## 🛠️ 技术栈

**PC 端:**
- Python 3.9+ / psutil / requests / pyserial

**ESP32 端:**
- Arduino 框架 / LovyanGFX / ArduinoJson / ESP32 Arduino Core

**像素工具:**
- Python 3.9+ / Pillow

## 📄 License

本项目采用 [Apache License 2.0](LICENSE) 许可证。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request
