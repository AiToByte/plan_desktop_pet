# PC监控端总览

本文档描述桌面电子宠物项目的PC端监控程序（`pc_monitor/`）的整体架构、模块组成、配置体系和运行模型。

PC监控端是整个系统的"大脑"，负责检测本地AI Agent工作状态、采集Token用量、获取天气信息，并通过串口或WiFi将数据推送到ESP32设备端显示。

---

## 一、Python工程结构

```
pc_monitor/
├── main.py                      # 主程序入口，DesktopPetMonitor + 启动模式分发
├── tray_app.py                  # 系统托盘GUI（pystray + tkinter + matplotlib）
├── requirements.txt             # Python依赖清单
├── config/
│   ├── config.example.json      # 配置模板（提交到Git）
│   └── config.json              # 实际配置（.gitignore忽略）
├── modules/
│   ├── __init__.py
│   ├── agent_monitor.py         # Agent进程检测（psutil + CPU模式 + JSONL）
│   ├── token_stats.py           # Token用量统计（日志解析）
│   ├── weather.py               # 天气服务（API调用 + 缓存）
│   ├── communication.py         # 设备通信（串口 / WiFi TCP）
│   ├── otlp_receiver.py         # OTLP HTTP接收器（端口4318）
│   └── thinking_chain.py        # 思考链数据处理
└── pc_monitor.log               # 运行日志（自动生成）
```

### 各模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| 主程序 | `main.py` | 加载配置、初始化各子模块、管理线程生命周期、分发启动模式 |
| 托盘应用 | `tray_app.py` | 系统托盘图标、悬浮状态面板、Token使用曲线图 |
| Agent监控 | `agent_monitor.py` | 检测本地AI Agent进程状态（工作中/空闲/授权/离线） |
| Token统计 | `token_stats.py` | 解析Agent日志文件，累计Token消耗和请求次数 |
| 天气服务 | `weather.py` | 调用天气API，支持缓存和自适应刷新率 |
| 设备通信 | `communication.py` | 串口（COM）或WiFi（TCP）双模式与ESP32通信 |
| OTLP接收 | `otlp_receiver.py` | 监听HTTP端口，接收Agent上报的OpenTelemetry Span |

---

## 二、模块依赖关系图

```
                          ┌─────────────────────────┐
                          │       main.py           │
                          │   DesktopPetMonitor     │
                          └─────┬───┬───┬───┬───┬───┘
                                │   │   │   │   │
               ┌────────────────┘   │   │   │   └────────────────┐
               │                    │   │   │                    │
               ▼                    ▼   ▼   ▼                    ▼
    ┌──────────────────┐  ┌────────────────────┐      ┌──────────────────┐
    │  agent_monitor   │  │   token_stats      │      │    tray_app      │
    │  (psutil检测)     │  │   (日志解析)        │      │  (pystray+tk)    │
    └──────────────────┘  └────────────────────┘      └──────────────────┘
               │                    │
               ▼                    ▼
    ┌──────────────────┐  ┌────────────────────┐
    │    weather        │  │  communication     │
    │  (API + 缓存)     │  │ (serial / wifi)    │
    └──────────────────┘  └────────┬───────────┘
                                    │
                                    ▼
                           ┌──────────────────┐
                           │   ESP32 设备端    │
                           │  (BLE/WiFi显示)   │
                           └──────────────────┘

    ┌──────────────────┐
    │ otlp_receiver    │ ──→ 接收Agent Span ──→ 转发到ESP32
    │ (HTTP :4318)     │
    └──────────────────┘
```

### 依赖方向说明

- `main.py` 是唯一入口，持有所有子模块实例
- `agent_monitor` 被 `main.py` 定时调用，无外部依赖
- `token_stats` 被 `main.py` 定时调用，读取本地日志文件
- `weather` 被 `main.py` 定时调用，依赖外部HTTP API
- `communication` 被 `main.py` 用于发送数据到ESP32，同时接收设备请求消息
- `otlp_receiver` 独立HTTP服务器，收到Span后通过回调通知 `main.py`
- `tray_app` 被 `main.py` 推送指标数据，不主动拉取任何模块

---

## 三、配置文件说明

配置文件路径：`config/config.json`（基于 `config.example.json` 模板创建）。

### 完整字段说明

```jsonc
{
  // ---- Agent进程监控 ----
  "agent_monitor": {
    "process_names": ["claudecode", "codex", "ooencode"],
    //  要监控的进程名称列表（模糊匹配进程名和命令行参数）
    "check_interval": 2,
    //  检查间隔（秒），每次轮询Agent状态的周期
    "log_file": "agent_status.log"
    //  Agent状态日志输出路径（可选）
  },

  // ---- Token用量统计 ----
  "token_stats": {
    "enabled": true,
    //  是否启用Token统计模块
    "log_paths": ["/path/to/your/agent/logs"],
    //  Agent日志目录列表，用于解析Token消耗
    "update_interval": 30
    //  统计更新间隔（秒）
  },

  // ---- 天气服务 ----
  "weather": {
    "enabled": true,
    //  是否启用天气服务
    "api_key": "YOUR_API_KEY",
    //  天气API密钥（如OpenWeatherMap）
    "city": "Beijing",
    //  查询城市名称
    "update_interval": 1800,
    //  天气刷新间隔（秒），默认30分钟
    "cache_file": "weather_cache.json"
    //  天气缓存文件路径，避免频繁API调用
  },

  // ---- 设备通信 ----
  "communication": {
    "mode": "wifi",
    //  通信模式："serial"（串口）或 "wifi"（TCP）
    "serial_port": "COM3",
    //  串口端口号（仅serial模式生效）
    "serial_baud": 115200,
    //  串口波特率（仅serial模式生效）
    "wifi_host": "0.0.0.0",
    //  WiFi监听地址（仅wifi模式生效）
    "wifi_port": 19876,
    //  WiFi监听端口（仅wifi模式生效）
    "retry_interval": 5
    //  连接失败重试间隔（秒）
  },

  // ---- 显示设置 ----
  "display": {
    "update_interval": 1,
    //  状态推送间隔（秒），控制_periodic_update循环频率
    "animation_enabled": true
    //  是否启用动画效果
  },

  // ---- OTLP接收（可选） ----
  "otlp": {
    "port": 4318
    //  OTLP HTTP接收端口，默认4318（OpenTelemetry标准端口）
  }
}
```

### 配置验证逻辑

`DesktopPetMonitor._validate_config()` 在启动时执行以下检查：

1. `agent_monitor.url` 是否为字符串类型
2. `communication.mode` 是否为 `"serial"` 或 `"wifi"`
3. 串口模式下是否配置了 `communication.port`
4. WiFi模式下是否配置了 `communication.tcp_port`
5. `token_stats.log_file` 路径是否存在

验证失败不会阻止启动，仅输出警告日志。

---

## 四、启动模式

PC监控端支持三种启动模式，通过命令行参数控制：

### 4.1 纯CLI模式（默认）

```bash
python main.py
```

- 后台运行，无GUI界面
- 主线程进入 `while self.running: time.sleep(1)` 轮询循环
- 支持 `Ctrl+C`（SIGINT）和 `SIGTERM` 信号优雅退出
- 日志输出到控制台和 `pc_monitor.log` 文件

**适用场景**：服务器环境、后台守护进程、调试日志分析。

### 4.2 托盘+监控模式

```bash
python main.py --tray
```

- 后台启动完整监控逻辑（OTLP、定时更新、通信）
- 主线程运行 `tkinter.mainloop()` 作为GUI事件循环
- 系统托盘图标提供"Show Panel"和"Exit"菜单
- 状态面板实时显示Agent指标和Token曲线
- 退出时触发 `monitor.stop()` 清理所有资源

**适用场景**：日常开发使用，可视化监控Agent状态。

### 4.3 仅托盘模式（调试用）

```bash
python main.py --tray-only
```

- 不启动任何监控逻辑，不连接ESP32
- 启动一个后台线程 `_simulate_tray()` 生成随机模拟数据
- 仅用于调试托盘GUI的布局和交互
- 模拟数据每2秒刷新一次，随机切换Idle/Working/Auth状态

**适用场景**：GUI开发调试、UI布局验证。

### 启动模式对比

| 特性 | CLI模式 | 托盘+监控 | 仅托盘 |
|------|---------|-----------|--------|
| 监控逻辑 | 启用 | 启用 | 禁用 |
| ESP32通信 | 启用 | 启用 | 禁用 |
| OTLP接收 | 启用 | 启用 | 禁用 |
| GUI托盘 | 无 | 有 | 有 |
| 模拟数据 | 无 | 无 | 有 |
| 信号处理 | SIGINT/SIGTERM | tkinter退出 | tkinter退出 |

---

## 五、线程模型

PC监控端采用多线程架构，各线程职责明确：

```
主线程 (main)
  │
  ├── CLI模式: while(running) sleep(1)  ← 仅做保活，等待信号
  │   或
  ├── --tray模式: tkinter.mainloop()    ← GUI事件循环
  │
  ├── [daemon] periodic_update          ← 定时发送状态/Token/天气
  │     └── 每次循环调用 health_guard.heartbeat()
  │
  ├── [daemon] otlp_receiver            ← HTTP服务器监听 :4318
  │     └── 收到Span → callback → 转发ESP32
  │
  ├── [daemon] health_guard             ← 每30s检查线程心跳
  │     └── 心跳超时(60s)或线程死亡 → 自动重启
  │
  └── [daemon] communication            ← WiFi模式: TCP服务器
        └── 收到设备请求 → callback → 发送对应数据
```

### 线程详情

| 线程名 | 类型 | 创建位置 | 作用 |
|--------|------|----------|------|
| 主线程 | 主线程 | `main()` | CLI保活或tkinter事件循环 |
| periodic_update | daemon | `start()` | 周期性采集并推送Agent状态、Token、天气 |
| otlp_receiver | daemon | `OTLPReceiver.start()` | HTTP服务器接收OTLP Span |
| health_guard | daemon | `ThreadHealthGuard.start()` | 监控其他线程健康，异常时重启 |
| communication | daemon | `Communication.connect()` | WiFi模式下为TCP服务器线程 |

### 心跳机制

`periodic_update` 线程在每次循环末尾调用：

```python
self._health_guard.heartbeat("periodic_update")
```

更新心跳时间戳。`health_guard` 线程每30秒检查一次，如果某个线程超过60秒未更新心跳或已死亡，则触发自动重启。

---

## 六、ThreadHealthGuard 线程守护

`ThreadHealthGuard` 是PC监控端的线程可靠性保障机制，通过心跳超时检测实现故障自愈。

### 6.1 设计原理

```
注册线程 ──→ 心跳更新 ──→ 守护检查 ──→ 超时/死亡 ──→ 重启
   │              │            │
   │              │            ├── 每30s检查一次
   │              │            ├── 心跳超时阈值: 60s
   │              │            └── 线程.is_alive() 检测
   │              │
   │              └── 被监控线程每次循环调用 heartbeat(name)
   │
   └── register(name, factory, initial_thread)
       name: 线程标识（如 "periodic_update"）
       factory: 返回新线程对象的工厂函数
       initial_thread: 当前已运行的线程实例
```

### 6.2 核心API

```python
class ThreadHealthGuard:
    def __init__(self, check_interval=30.0, heartbeat_timeout=60.0)
    def register(name, thread_factory, initial_thread=None)
    def heartbeat(name)
    def start()
    def stop()
```

| 方法 | 说明 |
|------|------|
| `register()` | 注册受监控线程，提供名称、重建工厂和初始线程 |
| `heartbeat()` | 被监控线程调用，刷新心跳时间戳 |
| `start()` | 启动守护线程，开始周期性检查 |
| `stop()` | 停止守护线程 |

### 6.3 重启流程

当检测到线程异常（死亡或心跳超时）时：

1. 记录错误日志
2. 尝试 `join(old_thread, timeout=3.0)` 等待旧线程自然退出
3. 如果旧线程3秒内未退出，记录警告（旧线程为daemon，不阻止进程退出）
4. 调用 `factory()` 创建新线程实例
5. 启动新线程，重置心跳时间戳
6. 记录重启成功日志

### 6.4 设计要点

- **不使用 `PyThreadState_SetAsyncExc`**：该方法跨平台不可靠，采用等待自然退出策略
- **daemon线程**：所有被监控线程均为daemon，进程退出时自动清理
- **工厂模式**：通过 `factory` 函数重建线程，避免共享状态导致的竞态条件
- **双重检测**：先检查 `is_alive()`，再检查心跳超时，覆盖线程卡死场景

### 6.5 当前注册的线程

目前只有 `periodic_update` 线程被注册到健康守护器：

```python
self._health_guard.register(
    "periodic_update",
    lambda: threading.Thread(target=self._periodic_update, daemon=True),
    initial_thread=update_thread
)
```

`otlp_receiver` 和 `communication` 线程暂未注册，因为它们有各自的重连/重试机制。

---

## 附录：关键常量

| 常量 | 值 | 说明 |
|------|----|------|
| `MAIN_LOOP_INTERVAL` | 1秒 | 主循环轮询间隔 |
| `DEFAULT_OTLP_PORT` | 4318 | OTLP HTTP默认端口 |
| `check_interval` | 30秒 | 健康守护检查间隔 |
| `heartbeat_timeout` | 60秒 | 心跳超时阈值 |
| `join timeout` | 3秒 | 重启时等待旧线程退出的超时 |
