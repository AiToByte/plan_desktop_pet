# 常见问题解答

> 收集用户最常提出的问题及其解答。如未找到你的问题，请参阅 [故障排除指南](troubleshooting.md) 或 [用户手册](user-manual.md)。

---

## 基本信息

### Q: 这个项目是什么？

这是一个基于 ESP32-S3 的桌面电子宠物设备，通过 1.54 英寸 LCD 屏幕显示像素风格的表情动画，并实时反映 PC 端 AI Agent（如 Claude Code、Codex 等）的工作状态、Token 使用量和天气信息。

### Q: 支持哪些 AI Agent？

目前支持以下 Agent 的自动检测：

- **Claude Code** — Anthropic 的命令行编程助手
- **Codex** — OpenAI 的代码生成工具
- **OOEncode** — 其他编码类 Agent

PC 端通过进程名检测 Agent 运行状态。如需支持其他 Agent，可在 `config.json` 的 `agent_monitor.process_names` 中添加对应进程名。

此外，项目支持 **OTLP 协议**接收 Agent 的遥测数据（思考链、工具调用等），任何实现了 OTLP span 上报的 Agent 均可接入。

### Q: 需要什么硬件？总成本多少？

**必需硬件：**

| 硬件 | 参考价格 |
|------|----------|
| 微雪 ESP32-S3 1.54inch LCD 开发板 | 约 60-80 元 |
| USB-C 数据线 | 约 5-10 元 |

**可选硬件：**

| 硬件 | 参考价格 | 用途 |
|------|----------|------|
| BH1750 光照传感器 | 约 5-10 元 | 自动背光调节 |
| DRV2605L 触觉反馈模块 | 约 15-25 元 | 触摸振动反馈 |
| 无源蜂鸣器 | 约 2-5 元 | 音效提示 |

**总成本：** 基础版约 70-90 元，完整版（含所有可选传感器）约 100-130 元。

PC 端无额外硬件需求，只需一台运行 Python 的电脑。

### Q: 支持哪些操作系统？

**PC 端：**

- Windows 10/11（主要开发和测试平台）
- macOS（支持，需自行安装依赖）
- Linux（支持，需自行安装依赖）

**固件端：**

- 使用 ESP-IDF / Arduino 框架，与操作系统无关
- 仅需 PlatformIO 进行编译和烧录

---

## 功能相关

### Q: 可以自定义表情吗？

可以。项目提供像素动画工具 `pixel_tool/`，支持将自定义图片或 GIF 转换为设备可播放的 `.pxl` 格式：

```bash
# 将 GIF 转换为像素动画并发送到设备
python pixel_tool/pixel_tool.py convert my_animation.gif -o my_anim.pxl -w 32 -H 32 --loop
python pixel_tool/pixel_tool.py send my_anim.pxl --host 192.168.1.100
```

支持的输入格式：PNG、JPG、JPEG、BMP、WebP、GIF。输出分辨率为 32x32 像素。

### Q: 屏幕显示什么内容？

240x240 像素的 LCD 屏幕根据状态显示不同内容：

- **Agent 工作时：** 表情动画 + CPU/内存使用率 + 思考链步骤
- **Agent 空闲时：** 微笑表情 + 天气面板 + Token 统计
- **离线时：** 时钟显示 + 眨眼动画
- **自定义模式：** 播放用户上传的像素动画

### Q: 天气数据从哪里来？

天气数据通过 PC 端调用 **OpenWeatherMap API** 获取，然后通过 TCP 推送到 ESP32 设备显示。需要：

1. 注册 OpenWeatherMap 账号获取免费 API 密钥
2. 在 `config.json` 中配置 `weather.api_key` 和 `weather.city`

### Q: 思考链是什么？如何工作？

思考链（Thinking Chain）是 AI Agent 执行任务时的实时步骤展示。当 Agent 进入思考、工具调用、生成等状态时：

1. Agent 通过 OTLP 协议上报当前状态
2. PC 端接收并转发到 ESP32
3. 屏幕实时显示最近 5 步思考内容
4. 支持滚动动画，历史最多保存 40 步

---

## 性能与功耗

### Q: 功耗多少？

| 状态 | 功耗 | 说明 |
|------|------|------|
| 正常运行 | 约 150-250mA @ 5V | 屏幕常亮 + WiFi 活跃 |
| 屏幕变暗 | 约 100-150mA @ 5V | 30 秒无数据后 |
| 屏幕休眠 | 约 50-80mA @ 5V | 60 秒无数据后，CPU 降频 |
| Light Sleep | 约 10-20mA @ 5V | 休眠 5 分钟后，深度睡眠 |

实际功耗取决于传感器配置、WiFi 信号强度和 CPU 负载。

### Q: 设备会一直亮屏吗？

不会。设备有三级省电机制：

1. **30 秒无数据：** 屏幕变暗
2. **60 秒无数据：** 关闭背光，CPU 降至 80MHz
3. **休眠 5 分钟后：** 进入 ESP32 Light Sleep 深度睡眠

可通过手掌接近（接近感应）或触摸屏幕随时唤醒。

### Q: WiFi 省电模式是什么？

设备在空闲时自动启用 WiFi 省电模式（Modem Sleep），仅在路由器发送 DTIM beacon 时唤醒接收数据，可节省约 50% 的 WiFi 功耗。收到新数据时自动恢复全速模式。

---

## 使用场景

### Q: 可以离线使用吗？

部分功能可以。设备在无法连接 PC 端时会进入离线模式：

- **可用：** 时钟显示、眨眼动画、接近唤醒、触摸交互
- **不可用：** Agent 状态显示、Token 统计、天气信息、思考链

WiFi 配网信息保存在 Flash 中，断电后不丢失。恢复网络后自动重连。

### Q: 可以同时连接多台设备吗？

当前版本支持一对一连接（一台 PC 连接一台 ESP32）。如需多设备，可以在 PC 端运行多个监控实例，使用不同的端口号。

### Q: 可以放在公司/公共网络使用吗？

可以，但需注意：

- 设备作为 TCP 客户端连接 PC 端，PC 端作为 TCP 服务端监听
- 需确保 PC 端的监听端口（默认 19876）未被防火墙阻止
- 配网时设备会创建临时热点 `Pet-Setup`，配网完成后自动关闭

---

## 安全与隐私

### Q: 数据安全如何保障？

- **本地通信：** 所有数据通过局域网 TCP 传输，不经过外部服务器
- **无云端依赖：** 设备本身不连接互联网（天气数据由 PC 端代理获取）
- **配网安全：** BLE 配网使用 UUID 隔离，Web 配网热点使用随机密码
- **无敏感数据：** 传输的数据仅包含 Agent 状态、Token 统计和天气信息，不含代码内容或密钥

### Q: 天气 API 密钥安全吗？

天气 API 密钥仅存储在 PC 端的 `config.json` 文件中，不会传输到 ESP32 设备。建议：

- 不要将包含密钥的 `config.json` 提交到版本控制系统
- `.gitignore` 已排除 `config.json`，仅保留 `config.example.json` 作为示例

---

## 开发与参与

### Q: 如何参与开发？

1. Fork 项目仓库
2. 创建功能分支：`git checkout -b feature/my-feature`
3. 提交代码并推送
4. 创建 Pull Request

项目使用 Python（PC 端）和 C++（ESP32 固件），构建工具为 PlatformIO。

### Q: 项目的技术栈是什么？

| 组件 | 技术栈 |
|------|--------|
| ESP32 固件 | C++ / Arduino / ESP-IDF / FreeRTOS |
| PC 监控端 | Python 3 / pystray / matplotlib |
| 像素工具 | Python 3 / Pillow |
| 构建系统 | PlatformIO |
| 通信协议 | TCP + JSON / BLE / OTLP |
| 屏幕驱动 | LovyanGFX (ST7789V) |

### Q: 如何编译固件？

```bash
# 安装 PlatformIO CLI
pip install platformio

# 编译固件
cd esp32_firmware
pio run

# 编译并烧录
pio run -t upload

# 查看串口日志
pio device monitor --baud 115200
```

### Q: 如何报告 Bug 或建议功能？

请在项目仓库的 Issues 页面提交，包含以下信息：

- 问题描述和复现步骤
- 串口日志或 PC 端日志
- 硬件配置（哪些传感器已连接）
- 固件版本和 PC 端版本

---

## 快速参考

### 关键端口与地址

| 项目 | 默认值 |
|------|--------|
| Web 配网地址 | `http://192.168.4.1` |
| 配网热点名称 | `Pet-Setup` |
| TCP 端口 | `19876` |
| OTLP 端口 | `4318` |
| BLE 服务 UUID | `1820` |

### 文件位置速查

| 文件 | 用途 |
|------|------|
| `pc_monitor/config/config.json` | PC 端配置文件 |
| `pc_monitor/pc_monitor.log` | PC 端运行日志 |
| `esp32_firmware/include/config.h` | 固件编译配置 |
| `pixel_tool/pixel_tool.py` | 像素动画工具 |
| `docs/09-用户手册/user-manual.md` | 完整用户手册 |
| `docs/09-用户手册/troubleshooting.md` | 故障排除指南 |
