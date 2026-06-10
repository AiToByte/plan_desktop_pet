# 通信协议文档

## 概述

PC端与ESP32之间通过 WiFi TCP 连接进行通信，使用 JSON 格式交换数据。

## 连接方式

### WiFi TCP (默认)
- **PC端**: TCP Server，监听端口 19876，等待 ESP32 连接
- **ESP32**: TCP Client，主动连接到 PC 的 IP 和端口
- **默认端口**: 19876

### 串口 (备选)
- **波特率**: 115200
- **数据格式**: 8N1

## 消息格式

所有消息均为单行 JSON，以 `\n` 结尾。

```json
{
  "type": "消息类型",
  "data": { ... },
  "timestamp": 1234567890
}
```

## 消息类型

### 1. 握手消息 (ESP32 → PC)

建立连接后发送的第一条消息。

```json
{
  "type": "handshake",
  "device": "esp32s3",
  "version": "1.0.0"
}
```

---

### 2. 状态消息 (PC → ESP32)

发送 Agent 工作状态。

```json
{
  "type": "status",
  "data": {
    "status": "idle|working|auth|offline",
    "process": "进程名称",
    "cpu": 45.2,
    "memory": 128.5,
    "uptime": 3600
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | idle/working/auth/offline |
| process | string | 当前运行的进程名 |
| cpu | float | CPU使用率 (0-100) |
| memory | float | 内存使用量 (MB) |
| uptime | int | 运行时长 (秒) |

---

### 3. Token统计 (PC → ESP32)

```json
{
  "type": "token",
  "data": {
    "input": 15000,
    "output": 8000,
    "requests": 42,
    "hour": 2500,
    "cost": 0.35
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| input | int | 输入Token总数 |
| output | int | 输出Token总数 |
| requests | int | 总请求数 |
| hour | int | 最近1小时Token数 |
| cost | float | 预估费用 (USD) |

---

### 4. 天气信息 (PC → ESP32)

```json
{
  "type": "weather",
  "data": {
    "city": "北京",
    "temp": 22.5,
    "feels_like": 21.0,
    "humidity": 45,
    "desc": "晴",
    "icon": "sun",
    "wind": 3.5
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| city | string | 城市名 |
| temp | float | 温度 (℃) |
| humidity | int | 湿度 (%) |
| icon | string | sun/cloud/rain/snow/fog |

---

### 5. 心跳 (ESP32 → PC)

```json
{
  "type": "heartbeat",
  "ts": 1234567890
}
```

---

### 6. 像素数据 (PC → ESP32)

发送自定义PXL像素文件数据。支持单包和分包传输。

**单包传输（小文件 ≤1KB）：**

```json
{
  "type": "pixel_data",
  "data": "UElM...base64编码的.pxl文件数据...",
  "chunk": 0,
  "total": 1,
  "last": true
}
```

**分包传输（大文件 >1KB）：**

```json
{
  "type": "pixel_data",
  "data": "base64编码的数据分片",
  "chunk": 0,
  "total": 3,
  "last": false
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data | string | Base64编码的PXL像素数据 |
| chunk | int | 当前分包索引（从0开始） |
| total | int | 总分包数 |
| last | bool | 是否最后一个分包 |

> ESP32收到`last=true`后自动加载并开始播放

---

### 7. 像素控制命令 (PC → ESP32)

控制自定义像素显示的播放状态。

```json
{
  "type": "pixel_cmd",
  "data": {
    "action": "play|stop|pause|resume"
  }
}
```

| action | 说明 |
|--------|------|
| play | 加载像素数据并切换到像素显示模式 |
| stop | 停止播放，返回正常表情显示模式 |
| pause | 暂停动画播放 |
| resume | 恢复动画播放 |

---

### 8. 天气信息 (PC → ESP32)

| 数据类型 | 更新间隔 |
|----------|----------|
| Agent状态 | 2秒 |
| Token统计 | 30秒 |
| 天气信息 | 30分钟 |
| 心跳 | 10秒 |

## 错误处理

- **连接断开**: ESP32每5秒尝试重连
- **JSON解析错误**: 跳过当前消息，继续处理
- **数据超时**: 超过60秒无数据显示OFFLINE
