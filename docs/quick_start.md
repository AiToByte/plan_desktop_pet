# 快速开始指南

## 概述

桌面宠物监控系统是一个基于ESP32的桌面伴侣设备，通过PC监控程序实时显示AI Agent运行状态、Token使用统计和天气信息。

## 前置条件

- Python 3.8+
- ESP32开发板（已刷入固件）
- 串口连接或WiFi网络

## 安装

### 1. 克隆项目

```bash
git clone <repository-url>
cd plan_desktop_pet
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

或使用pip安装核心依赖：

```bash
pip install pyserial requests psutil
```

### 3. 配置

1. 复制配置模板：
   ```bash
   cp pc_monitor/config.example.json pc_monitor/config.json
   ```

2. 编辑 `pc_monitor/config.json`，修改以下配置：
   - `communication.mode`: 通信模式（"serial" 或 "wifi"）
   - `communication.port`: 串口端口（串口模式）
   - `communication.tcp_port`: TCP端口（WiFi模式）
   - `agent_monitor.url`: Agent监控地址

## 运行

### PC监控程序

```bash
cd pc_monitor
python main.py
```

### 像素工具

```bash
cd pixel_tool
python pixel_tool.py info          # 查看设备信息
python pixel_tool.py send -t status -d '{"cpu": 50}'  # 发送消息
python pixel_tool.py cmd -c home   # 发送命令
python pixel_tool.py convert -i image.png -o output.png  # 转换图片
```

## 通信模式

### 串口模式

适用于直接USB连接ESP32：

```json
{
  "communication": {
    "mode": "serial",
    "port": "COM3",
    "baudrate": 115200
  }
}
```

### WiFi模式

适用于WiFi连接ESP32：

```json
{
  "communication": {
    "mode": "wifi",
    "tcp_port": 8080,
    "udp_port": 8081
  }
}
```

## 常见问题

### 1. 串口连接失败

- 检查串口端口是否正确
- 确认ESP32已连接并上电
- 检查波特率设置

### 2. WiFi连接失败

- 确认PC和ESP32在同一网络
- 检查防火墙设置
- 确认TCP端口未被占用

### 3. Agent监控无数据

- 检查Agent服务是否运行
- 确认监控URL配置正确
- 检查网络连接

## 更多信息

- 项目结构说明：[README.md](../README.md)
- 硬件接线指南：[hardware_guide.md](../hardware_guide.md)
- ESP32固件源码：[esp32_firmware/](../esp32_firmware/)