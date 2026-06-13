# 通信协议 API 文档

## 概述

PC监控程序与ESP32设备之间通过自定义JSON协议进行通信，使用长度前缀帧格式确保数据完整性。

## 传输层

### 串口模式
- 波特率：115200（可配置）
- 数据格式：8N1
- 使用长度前缀帧协议

### WiFi模式
- TCP Server：PC端监听，ESP32作为客户端连接
- UDP广播：PC端广播设备发现信息
- 默认端口：TCP 8080, UDP 8081

## 帧格式

### 长度前缀帧

```
LEN:<payload_length>\n
<payload_json>\n
```

示例：
```
LEN:45
{"type":"status","data":{"cpu":50},"ts":1234567890}
```

## 消息类型

### 1. 状态消息 (status)

**PC → ESP32**
```json
{
  "type": "status",
  "data": {
    "cpu": 50,
    "memory": 60,
    "disk": 70
  },
  "ts": 1234567890
}
```

**字段说明：**
- `cpu`: CPU使用率 (0-100)
- `memory`: 内存使用率 (0-100)
- `disk`: 磁盘使用率 (0-100)

### 2. Token统计消息 (token)

**PC → ESP32**
```json
{
  "type": "token",
  "data": {
    "input_tokens": 1000,
    "output_tokens": 500,
    "total_tokens": 1500,
    "session_name": "main"
  },
  "ts": 1234567890
}
```

**字段说明：**
- `input_tokens`: 输入Token数量
- `output_tokens`: 输出Token数量
- `total_tokens`: 总Token数量
- `session_name`: 会话名称

### 3. 天气消息 (weather)

**PC → ESP32**
```json
{
  "type": "weather",
  "data": {
    "temp": 25,
    "humidity": 60,
    "description": "晴",
    "city": "北京"
  },
  "ts": 1234567890
}
```

**字段说明：**
- `temp`: 温度（摄氏度）
- `humidity`: 湿度（百分比）
- `description`: 天气描述
- `city`: 城市名称

### 4. 动画消息 (animation)

**PC → ESP32**
```json
{
  "type": "animation",
  "data": {
    "name": "happy",
    "duration": 2000
  },
  "ts": 1234567890
}
```

**字段说明：**
- `name`: 动画名称
- `duration`: 动画持续时间（毫秒）

### 5. 设备请求消息

**ESP32 → PC**

请求状态：
```json
{
  "type": "request_status",
  "data": {},
  "ts": 1234567890
}
```

请求天气：
```json
{
  "type": "request_weather",
  "data": {},
  "ts": 1234567890
}
```

请求Token统计：
```json
{
  "type": "request_tokens",
  "data": {},
  "ts": 1234567890
}
```

## 错误处理

### 连接断开
- 串口断开：自动尝试重连，最多10次，间隔5秒
- WiFi断开：等待新客户端连接

### 消息解析失败
- JSON解析失败：记录警告日志，忽略该消息
- 消息格式错误：记录警告日志，忽略该消息

## 示例代码

### Python发送消息

```python
from pc_monitor.modules.communication import DeviceMessage, create_communication

# 创建通信实例
config = {"mode": "serial", "port": "COM3", "baudrate": 115200}
comm = create_communication(config)
comm.connect()

# 发送状态消息
msg = DeviceMessage(
    msg_type="status",
    data={"cpu": 50, "memory": 60},
    timestamp=time.time()
)
comm.send_message(msg)
```

### ESP32接收消息（Arduino）

```cpp
void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    if (line.startsWith("LEN:")) {
      int len = line.substring(4).toInt();
      String payload = Serial.readStringUntil('\n');
      // 解析JSON
      DynamicJsonDocument doc(1024);
      deserializeJson(doc, payload);
      // 处理消息
    }
  }
}
```