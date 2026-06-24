# 完整用户手册

> 本手册面向桌面电子宠物的终端用户，涵盖从开箱到日常使用的全部流程。
> 项目硬件基于 **微雪 ESP32-S3 1.54inch LCD** 开发板，PC 端为 Python 监控程序。

---

## 一、开箱与组装

### 1.1 包装清单

| 物品 | 数量 | 说明 |
|------|------|------|
| ESP32-S3 1.54inch LCD 开发板 | 1 | 主控+屏幕一体模块 |
| USB-C 数据线 | 1 | 供电与烧录 |
| BH1750 光照传感器模块 | 1 | 自动背光调节（可选） |
| DRV2605L 触觉反馈模块 | 1 | 振动马达驱动（可选） |
| 连接线若干 | - | I2C 总线共享 SDA/SCL |

### 1.2 硬件组装

**基本连接（必选）：**

开发板已集成屏幕，无需额外接线。使用 USB-C 线连接电脑即可同时供电和烧录固件。

**可选传感器连接：**

BH1750 和 DRV2605L 共享 I2C 总线，接线如下：

```
ESP32-S3          BH1750 / DRV2605L
─────────         ─────────────────
GPIO 41 (SDA) ──→ SDA
GPIO 42 (SCL) ──→ SCL
3.3V          ──→ VCC
GND           ──→ GND
```

> 注意：两个传感器模块的 I2C 地址不同（BH1750: 0x23, DRV2605L: 0x5A），可并联在同一总线上。

**蜂鸣器连接（可选）：**

```
ESP32-S3          无源蜂鸣器
─────────         ──────────
GPIO 18       ──→ 信号脚
GND           ──→ GND
```

### 1.3 上电测试

1. 使用 USB-C 线连接开发板与电脑
2. 屏幕亮起，显示初始化画面 `"Initializing..."`
3. 蜂鸣器播放启动音效（如已连接）
4. 等待 WiFi 连接（详见下节配网流程）

---

## 二、首次配网

设备首次使用时需要配置 WiFi 网络和 PC 端服务器地址。提供两种配网方式。

### 2.1 方式一：Web 配网（推荐）

适用于任何有浏览器的设备（手机、平板、电脑）。

**步骤：**

1. **设备进入配网模式**
   - 首次上电或 WiFi 信息未设置时自动进入
   - 屏幕显示 `"AP: Pet-Setup"`

2. **手机连接设备热点**
   - WiFi 名称：`Pet-Setup`
   - 默认密码：`pet`（设备会根据 MAC 地址生成唯一密码，详见屏幕提示）

3. **打开浏览器访问配网页面**
   - 连接热点后自动跳转，或手动访问 `http://192.168.4.1`
   - 配网页面会列出周围可用的 WiFi 网络

4. **选择 WiFi 并输入密码**
   - 选择你的家庭/办公 WiFi
   - 输入 WiFi 密码
   - 填写 PC 端服务器 IP 地址（如 `192.168.1.100`）和端口（默认 `19876`）

5. **等待连接**
   - 设备尝试连接 WiFi，成功后屏幕显示 IP 地址
   - 配网超时时间为 **2 分钟**

> 提示：配网信息保存在设备 Flash 中，断电后不丢失。如需重新配网，长按触摸区域 3 秒以上。

### 2.2 方式二：BLE 蓝牙配网

适用于支持 BLE 的手机。

**步骤：**

1. 设备进入 BLE 广播模式（屏幕提示或 LED 指示）
2. 使用支持 BLE 配网的 App 扫描设备
3. 设备名称：`Pet-Setup`（BLE 广播 UUID: `1820`）
4. 通过 BLE 写入以下特征值：
   - **SSID**（UUID `2A69`）：WiFi 名称
   - **Password**（UUID `2A6A`）：WiFi 密码
   - **Server URL**（UUID `2A6B`）：PC 端服务器地址（可选）
5. 设备收到凭据后自动尝试连接 WiFi
6. 通过状态特征（UUID `2A6C`）接收配网进度通知

**BLE 配网状态码：**

| 状态值 | 含义 |
|--------|------|
| 0 | 空闲 (Idle) |
| 1 | 广播中 (Advertising) |
| 2 | 已连接 (Connected) |
| 3 | 凭据已接收 (Credentials) |
| 4 | 连接 WiFi 中 (Connecting) |
| 5 | WiFi 已连接 (Connected) |
| 6 | WiFi 连接失败 (Failed) |
| 7 | 配网完成 (Done) |

### 2.3 配网失败排查

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| 找不到 `Pet-Setup` 热点 | 设备未进入配网模式 | 重新上电或长按触摸区域 |
| 连接热点后无法打开页面 | 浏览器未自动跳转 | 手动访问 `http://192.168.4.1` |
| WiFi 连接失败 | 密码错误或信号弱 | 确认密码正确，靠近路由器重试 |
| 配网超时 | 操作超过 2 分钟 | 重新上电再次尝试 |

---

## 三、日常使用

### 3.1 界面说明

屏幕为 **240x240 像素** 的方形 LCD，显示内容分为以下几个区域：

#### 表情区域（主显示区）

宠物会根据 AI Agent 的工作状态显示不同表情：

| 表情 | 对应状态 | 触发条件 |
|------|----------|----------|
| 开心/微笑 | 空闲 (Idle) | Agent 无任务运行 |
| 专注/思考 | 工作中 (Working) | Agent 正在执行任务 |
| 等待/眨眼 | 认证中 (Auth) | Agent 等待用户授权 |
| 睡眠/断线 | 离线 (Offline) | 45 秒未收到 PC 数据 |

#### 状态栏

屏幕底部或侧边显示以下信息：

- **CPU 使用率**：Agent 进程的 CPU 占用百分比
- **内存使用**：Agent 进程的内存占用（MB）
- **运行时长**：Agent 本次运行的持续时间

#### 天气面板

显示当前天气信息（需 PC 端配置天气 API）：

- 当前城市名称
- 实时温度与体感温度
- 天气状况图标（晴、多云、雨、雪等）
- 湿度与风速

#### Token 面板

显示 AI Agent 的 Token 使用统计：

- **输入/输出 Token 数**：累计消耗
- **请求数**：总 API 调用次数
- **最近一小时用量**：近期消耗趋势
- **预估费用**：按美元计的使用成本

#### 思考链显示

当 AI Agent 处于思考状态时，屏幕实时显示思考步骤：

- 最多同时显示 **5 条**最近步骤
- 支持滚动动画切换，动画时长 800ms
- 单步文本最长 64 字符
- 历史记录最多保存 40 步（存储在 PSRAM 中）

### 3.2 触摸交互

设备配备电容触摸传感器（GPIO 1），支持以下手势：

| 手势 | 操作 | 反馈 |
|------|------|------|
| **单击** | 显示当前详细状态 | 蜂鸣器短响 + 触觉轻击 |
| **双击** | 切换显示面板（天气/Token/状态） | 蜂鸣器短响 + 触觉嗡嗡 |
| **长按**（1秒以上） | 进入配网模式 / 重置操作 | 蜂鸣器警报 + 触觉强击 |

> 触摸阈值默认为 40，如感觉触摸不灵敏或过于灵敏，可在固件 `config.h` 中调整 `TOUCH_THRESHOLD` 值。

### 3.3 接近唤醒

设备利用电容触摸传感器实现接近感应功能：

- 手掌靠近设备时自动唤醒屏幕
- 唤醒后屏幕保持亮起 **15 秒**
- 唤醒期间如再次检测到接近，计时器重置
- 冷却时间 **2 秒**，防止误触发

**接近检测参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 上升阈值 | 8 | 检测手掌靠近的灵敏度 |
| 下降阈值 | 4 | 检测手掌远离的灵敏度 |
| 冷却时间 | 2000ms | 两次触发的最小间隔 |
| 唤醒时长 | 15000ms | 唤醒后屏幕保持时间 |

### 3.4 自定义像素动画

你可以将图片或 GIF 转换为自定义像素动画，发送到设备上播放。

#### 准备工作

确保 PC 端已安装 Python 环境，进入 `pixel_tool/` 目录。

#### 转换图片为 .pxl 文件

```bash
# 静态图片转换（32x32 像素，200ms 间隔）
python pixel_tool.py convert input.png -o output.pxl -w 32 -H 32 --interval 200

# GIF 动画转换（最多 64 帧，循环播放）
python pixel_tool.py convert animation.gif -o output.pxl -w 32 -H 32 --max-frames 64 --loop

# 精灵图转换（将一张大图按网格切分为多帧动画）
python pixel_tool.py convert spritesheet.png -o output.pxl -w 32 -H 32 --sprite --interval 150
```

#### 发送到设备

```bash
# 发送 .pxl 文件到 ESP32（自动切换到像素播放模式）
python pixel_tool.py send output.pxl --host 192.168.1.100 --port 19876

# 发送后不自动切换模式
python pixel_tool.py send output.pxl --host 192.168.1.100 --no-switch
```

#### 播放控制

```bash
# 播放已加载的动画
python pixel_tool.py cmd play --host 192.168.1.100

# 暂停播放
python pixel_tool.py cmd pause --host 192.168.1.100

# 恢复播放
python pixel_tool.py cmd resume --host 192.168.1.100

# 停止播放并返回普通模式
python pixel_tool.py cmd stop --host 192.168.1.100
```

> 也可通过 BOOT 键（GPIO0）短按停止像素播放，返回普通显示模式。

#### .pxl 文件信息查看

```bash
python pixel_tool.py info output.pxl
```

---

## 四、PC 端设置

PC 端监控程序负责检测 AI Agent 状态、获取天气、统计 Token，并通过 TCP 将数据推送到 ESP32 设备。

### 4.1 配置文件说明

配置文件路径：`pc_monitor/config/config.json`

首次使用请复制示例配置：

```bash
cp pc_monitor/config/config.example.json pc_monitor/config/config.json
```

完整配置项说明：

```jsonc
{
  // === Agent 监控配置 ===
  "agent_monitor": {
    "process_names": ["claudecode", "codex", "ooencode"],
    // 要监控的 AI Agent 进程名列表
    // 支持：Claude Code、Codex、OOEncode 等

    "check_interval": 2,
    // 进程检测间隔（秒）

    "log_file": "agent_status.log"
    // Agent 状态日志文件路径
  },

  // === Token 统计配置 ===
  "token_stats": {
    "enabled": true,
    // 是否启用 Token 统计

    "log_paths": ["/path/to/your/agent/logs"],
    // Agent 日志目录路径，用于提取 Token 使用数据
    // 请修改为你的实际 Agent 日志路径

    "update_interval": 30
    // Token 数据刷新间隔（秒）
  },

  // === 天气服务配置 ===
  "weather": {
    "enabled": true,
    // 是否启用天气服务

    "api_key": "YOUR_API_KEY",
    // OpenWeatherMap API 密钥
    // 注册地址: https://openweathermap.org/api

    "city": "Beijing",
    // 城市名称（英文或拼音）

    "update_interval": 1800,
    // 天气刷新间隔（秒），默认 30 分钟
    // Agent 工作时自动缩短为 10 分钟，空闲时延长为 1 小时

    "cache_file": "weather_cache.json"
    // 天气缓存文件，网络不可用时使用缓存数据
  },

  // === 通信配置 ===
  "communication": {
    "mode": "wifi",
    // 通信模式: "wifi"（TCP）或 "serial"（USB 串口）

    "serial_port": "COM3",
    // 串口模式下的端口号（仅 serial 模式生效）

    "serial_baud": 115200,
    // 串口波特率（仅 serial 模式生效）

    "wifi_host": "0.0.0.0",
    // WiFi 模式下监听地址（0.0.0.0 表示接受所有连接）

    "wifi_port": 19876,
    // WiFi 模式下 TCP 监听端口
    // 配网时需填入与此一致的端口号

    "retry_interval": 5
    // 连接断开后重试间隔（秒）
  },

  // === 显示配置 ===
  "display": {
    "update_interval": 1,
    // 状态数据发送间隔（秒）

    "animation_enabled": true
    // 是否启用动画效果
  }
}
```

### 4.2 启动方式

**命令行模式：**

```bash
cd pc_monitor
python main.py
```

**带托盘图标的 GUI 模式：**

```bash
python main.py --tray
```

**仅托盘面板（调试模式，使用模拟数据）：**

```bash
python main.py --tray-only
```

### 4.3 依赖安装

```bash
pip install requests pystray Pillow matplotlib
```

| 依赖 | 用途 | 必需？ |
|------|------|--------|
| requests | 天气 API 请求 | 是 |
| pystray | 系统托盘图标 | 否（无托盘时用命令行） |
| Pillow | 托盘图标绘制 | 否（同上） |
| matplotlib | Token 使用曲线图 | 否（面板中图表不可用） |

---

## 五、托盘图标使用

启动 `python main.py --tray` 后，系统托盘区域会出现宠物图标。

### 5.1 托盘菜单

| 菜单项 | 功能 |
|--------|------|
| Show Panel（默认点击） | 打开/聚焦 Agent 指标面板 |
| Exit | 退出监控程序 |

### 5.2 状态面板

面板显示以下实时数据：

- **Status**：Agent 当前状态（Idle / Working / Auth）
- **CPU**：Agent 进程 CPU 占用率
- **Memory**：Agent 进程内存占用
- **Uptime**：Agent 运行时长
- **Crash Count**：设备崩溃计数（从 ESP32 上报）
- **Token 曲线图**：最近的输入/输出 Token 使用趋势

面板支持以下交互：

- **拖拽移动**：按住面板标题区域拖动
- **边缘磁吸**：拖拽到屏幕边缘附近自动吸附
- **多显示器定位**：面板自动出现在鼠标所在的显示器上

---

## 六、多显示器支持

PC 端托盘面板完全支持多显示器环境：

- 面板首次显示时自动定位到鼠标当前所在的显示器
- 拖拽移动时跨显示器边界不会丢失
- 边缘磁吸检测基于当前显示器的工作区边界（排除任务栏）
- 支持不同分辨率和 DPI 的显示器混合使用

---

## 七、固件升级

### 7.1 通过 USB 烧录（首次/恢复）

```bash
# 使用 PlatformIO 编译并烧录
cd esp32_firmware
pio run -t upload

# 仅编译不烧录
pio run
```

### 7.2 OTA 空中升级

设备支持通过 WiFi 进行 OTA 升级，无需 USB 连接：

1. PC 端通过 TCP 发送 OTA 固件数据
2. 设备接收固件并写入 OTA 分区
3. 自动重启并运行新固件
4. 首次成功接收 PC 端数据包后确认升级有效，取消回滚

> 如果新固件导致设备崩溃，ESP32 会自动回滚到上一个版本。

### 7.3 崩溃遥测

设备具备崩溃遥测功能：

- 使用 RTC 内存记录崩溃次数（断电不丢失）
- 重启后自动上报崩溃次数和复位原因到 PC 端
- PC 端托盘面板的 Crash Count 指标即为此数据

---

## 八、维护与保养

### 8.1 日常维护

- **清洁屏幕**：使用柔软的微纤维布轻轻擦拭，避免使用酒精或化学清洁剂
- **检查连接**：定期确认 USB 线或电源连接牢固
- **散热**：设备长时间运行时注意通风，CPU 温度超过 65°C 会自动降频保护

### 8.2 省电模式

设备在无数据交互时会自动进入省电状态：

| 阶段 | 触发条件 | 行为 |
|------|----------|------|
| 变暗 | 30 秒无数据 | 屏幕亮度降低 |
| 休眠 | 60 秒无数据 | 关闭背光，CPU 降频至 80MHz |
| Light Sleep | 休眠 5 分钟后 | ESP32 深度睡眠，仅触摸和 WiFi 唤醒 |

唤醒方式：

- PC 端发送新数据时自动唤醒
- 手掌接近（接近感应唤醒）
- 触摸屏幕
- BOOT 键按下

### 8.3 WiFi 省电

设备在空闲时自动启用 WiFi 省电模式：

- 空闲超过 30 秒：进入 Light Sleep WiFi 模式
- 活跃态 DTIM 间隔：1（最低延迟）
- 空闲态 DTIM 间隔：10（省电优先）
- BSS 最大空闲时间：300 秒

### 8.4 温控保护

设备内置温控机制，防止 CPU 过热：

| 温度范围 | CPU 频率 | 说明 |
|----------|----------|------|
| < 50°C | 240 MHz | 正常运行 |
| 50-55°C | 240 MHz → 160 MHz | 轻度降频 |
| 55-65°C | 160 MHz | 持续降频 |
| > 65°C | 80 MHz | 严重降频 + 降低亮度 |

温控检测每 10 秒执行一次，温度回落后自动恢复频率。

### 8.5 自动背光

如连接了 BH1750 光照传感器，设备会根据环境光照自动调节屏幕亮度：

- 每 2 秒读取一次光照值
- 根据光照强度自动映射到合适的背光 PWM 值
- 环境越亮屏幕越亮，环境越暗屏幕越暗
- 使用一阶缓动算法平滑过渡，避免亮度突变

### 8.6 常用参数速查

| 参数 | 默认值 | 配置位置 |
|------|--------|----------|
| 屏幕变暗超时 | 30 秒 | `config.h` → `SCREEN_DIM_TIMEOUT` |
| 屏幕休眠超时 | 60 秒 | `config.h` → `SCREEN_SLEEP_TIMEOUT` |
| 离线检测超时 | 45 秒 | `config.h` → `OFFLINE_TIMEOUT_MS` |
| 触摸阈值 | 40 | `config.h` → `TOUCH_THRESHOLD` |
| 长按时间 | 1000ms | `config.h` → `TOUCH_LONG_PRESS_MS` |
| 接近唤醒时长 | 15 秒 | `config.h` → `PROX_WAKE_DURATION_MS` |
| 天气刷新间隔 | 30 分钟 | `config.json` → `weather.update_interval` |
| Token 刷新间隔 | 30 秒 | `config.json` → `token_stats.update_interval` |
| TCP 监听端口 | 19876 | `config.json` → `communication.wifi_port` |
| 光照读取间隔 | 2 秒 | `config.h` → `BH1750_READ_INTERVAL` |
| 思考链历史上限 | 40 步 | `config.h` → `THINKING_HISTORY_MAX` |
| 可见思考步骤 | 5 条 | `config.h` → `THINKING_VISIBLE_COUNT` |
