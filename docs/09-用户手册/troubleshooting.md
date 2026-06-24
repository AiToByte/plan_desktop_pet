# 故障排除指南

> 本指南帮助你诊断和解决桌面电子宠物使用过程中的常见问题。
> 如果问题仍未解决，请查看 `pc_monitor.log` 或通过串口监视器获取详细日志。

---

## 一、连接问题

### 1.1 WiFi 连不上

**症状：** 屏幕显示 `"WiFi Failed!"` 或长时间停留在 `"Connecting WiFi..."`

**排查步骤：**

1. **确认 WiFi 名称和密码正确**
   - WiFi 名称区分大小写
   - 建议使用 2.4GHz 频段（ESP32-S3 不支持 5GHz 独立连接）
   - 避免使用包含特殊字符的 WiFi 密码

2. **确认信号强度**
   - 将设备移近路由器重试
   - 避免金属物体遮挡

3. **检查路由器设置**
   - 确认路由器未开启 MAC 地址过滤
   - 确认 DHCP 地址池未满
   - 尝试关闭路由器的 AP 隔离功能

4. **重新配网**
   - 长按触摸区域 3 秒以上触发重新配网
   - 或重新上电进入配网模式

5. **查看串口日志**
   ```bash
   # 使用 PlatformIO 串口监视器
   cd esp32_firmware
   pio device monitor --baud 115200
   ```
   关注日志中的 WiFi 连接错误码。

### 1.2 TCP 连接断开

**症状：** 设备屏幕切换为离线表情，PC 端日志显示连接断开

**排查步骤：**

1. **确认 PC 端程序正在运行**
   - 检查 `python main.py` 或 `python main.py --tray` 进程是否存在

2. **确认网络互通**
   - PC 和 ESP32 必须在同一局域网内
   - 在 PC 上 ping ESP32 的 IP 地址
   - 检查 Windows 防火墙是否阻止了 TCP 端口 19876

3. **检查端口配置**
   - PC 端 `config.json` 中的 `communication.wifi_port` 必须与设备配网时填写的端口一致
   - 默认端口：`19876`
   - 确认端口未被其他程序占用

4. **重连机制**
   - 设备内置自动重连，断连后按指数退避策略重试（间隔 5 秒起步）
   - 通常等待 10-30 秒可自动恢复
   - 如果超过 2 分钟仍未恢复，重启设备

5. **检查 TCP 超时配置**
   - 默认 TCP 超时：10 秒
   - Keepalive 探测：空闲 5 秒后开始，间隔 5 秒，3 次失败断开
   - 如网络环境较差，可在 `config.h` 中调大 `CLIENT_TCP_TIMEOUT`

### 1.3 配网失败

**症状：** Web 配网页面无法访问或提交后连接失败

| 现象 | 原因 | 解决方法 |
|------|------|----------|
| 找不到 `Pet-Setup` 热点 | 设备未进入配网模式 | 重新上电，等待自动进入配网 |
| 连接热点后无法打开页面 | DNS 未劫持或浏览器缓存 | 手动输入 `http://192.168.4.1` |
| 页面打开但无 WiFi 列表 | 扫描超时 | 刷新页面或重启设备 |
| 提交后一直转圈 | WiFi 密码错误 | 确认密码，注意大小写 |
| 提交后显示连接失败 | 信号弱或路由器拒绝 | 靠近路由器，检查路由器设置 |
| 配网超时自动退出 | 操作超过 2 分钟 | 重新上电，加快操作速度 |

---

## 二、显示问题

### 2.1 屏幕不亮

**排查步骤：**

1. **检查供电**
   - 确认 USB 线连接牢固
   - 尝试更换 USB 线或 USB 端口
   - 确认供电电流至少 500mA

2. **检查背光**
   - 屏幕可能处于休眠状态，触摸屏幕或手掌靠近唤醒
   - 检查 `config.h` 中 `LCD_BL` 引脚定义是否正确（默认 GPIO 48）

3. **检查初始化日志**
   - 通过串口监视器查看是否有 `"初始化显示..."` 日志
   - 如有 `"LCD init failed"` 等错误，可能是硬件故障

### 2.2 颜色异常

**症状：** 屏幕颜色偏色、反色或显示混乱

**排查步骤：**

1. **检查屏幕参数**
   - 确认 `config.h` 中 `SCREEN_ROTATION` 值正确（0-3）
   - 确认屏幕型号与固件匹配（ST7789V 驱动）

2. **检查 SPI 接线**
   - 确认 GPIO 引脚定义与硬件一致：
     ```
     LCD_CS:   GPIO 5
     LCD_RST:  GPIO 4
     LCD_DC:   GPIO 2
     LCD_MOSI: GPIO 11
     LCD_SCLK: GPIO 12
     ```

3. **夜览模式**
   - 设备根据 NTP 时间自动应用夜览色温滤镜
   - 如果不需要，可在代码中注释 `display.applyNightFilter()` 调用

### 2.3 动画卡顿

**症状：** 表情动画不流畅，有明显跳帧

**排查步骤：**

1. **检查 CPU 温度**
   - 温度过高会自动降频导致帧率下降
   - 串口日志中搜索 `"THERMAL"` 关键字
   - 改善散热条件

2. **检查帧率**
   - 串口日志中搜索 `"FPS"` 查看实际帧率
   - 正常情况下：
     - Agent 工作中：60fps
     - 普通状态：50fps
     - 空闲状态：5fps
     - 休眠状态：2fps

3. **检查通信负载**
   - 大量像素动画数据传输可能占用 CPU 资源
   - 减少同时传输的数据量

4. **检查 PSRAM 使用**
   - 串口日志中搜索 `"PSRAM"` 查看剩余空间
   - 如 PSRAM 不足，减少思考链历史上限或像素动画尺寸

---

## 三、传感器问题

### 3.1 触摸无反应

**排查步骤：**

1. **确认硬件连接**
   - 触摸传感器使用 GPIO 1（Touch1 引脚）
   - 确认触摸区域与开发板触摸焊盘对齐

2. **调整触摸阈值**
   - 默认阈值为 40，可能需要根据环境校准
   - 在 `config.h` 中修改 `TOUCH_THRESHOLD`
   - 值越小越灵敏，值越大越不灵敏
   - 建议范围：20-80

3. **检查环境干扰**
   - 潮湿环境可能影响电容触摸灵敏度
   - 金属物体靠近可能产生干扰
   - 尝试在干燥环境下测试

4. **查看串口日志**
   - 触摸事件会输出 `"Single tap"` / `"Double tap"` / `"Long press"` 日志
   - 如无日志输出，可能是硬件问题

### 3.2 光照不调节

**症状：** 屏幕亮度不会根据环境光自动变化

**排查步骤：**

1. **确认 BH1750 已连接**
   - I2C 接线：SDA → GPIO 41, SCL → GPIO 42
   - 确认模块供电正常（3.3V）

2. **检查初始化日志**
   - 串口搜索 `"BH1750 ready"` 或 `"BH1750 not found"`
   - 如显示 `"not found"`，检查 I2C 接线和地址

3. **检查 I2C 地址冲突**
   - BH1750 默认地址 0x23
   - DRV2605L 默认地址 0x5A
   - 如有地址冲突，修改模块上的地址跳线

4. **确认传感器读数**
   - 串口日志搜索 `"Light"` 查看当前光照值（单位：lux）
   - 正常室内光照约 100-500 lux

### 3.3 振动无感

**排查步骤：**

1. **确认 DRV2605L 已连接**
   - 与 BH1750 共享 I2C 总线
   - 确认振动马达已连接到 DRV2605L 的输出端

2. **检查初始化日志**
   - 串口搜索 `"DRV2605L ready"` 或 `"DRV2605L not found"`

3. **测试振动效果**
   - 单击触摸区域应触发轻击振动
   - 双击应触发嗡嗡振动
   - 长按应触发强击振动

4. **确认振动马达类型**
   - DRV2605L 支持 ERM（偏心转子）和 LRA（线性谐振）马达
   - 默认配置适用于常见 ERM 马达

---

## 四、PC 端问题

### 4.1 Agent 检测不到

**症状：** PC 端运行但设备始终显示离线状态

**排查步骤：**

1. **确认进程名称匹配**
   - 检查 `config.json` 中 `agent_monitor.process_names` 列表
   - 默认包含：`claudecode`, `codex`, `ooencode`
   - 使用任务管理器确认 AI Agent 进程的实际名称

2. **确认通信连接**
   - 查看 PC 端日志文件 `pc_monitor.log`
   - 搜索 `"无法连接到ESP32设备"` 错误
   - 确认 `communication.mode` 设置正确（`wifi` 或 `serial`）

3. **串口模式排查**
   - 确认 `serial_port` 与设备管理器中显示的端口号一致
   - Windows：`COM3`, `COM4` 等
   - 确认没有其他程序占用该串口

4. **WiFi 模式排查**
   - 确认 `wifi_port` 端口未被占用
   - 使用 `netstat -an | findstr 19876` 检查端口状态

### 4.2 Token 不更新

**症状：** Token 面板数据始终为 0 或不变化

**排查步骤：**

1. **确认 Token 统计已启用**
   - `config.json` 中 `token_stats.enabled` 应为 `true`

2. **确认日志路径正确**
   - `token_stats.log_paths` 必须指向 Agent 的实际日志目录
   - 路径必须存在且可读

3. **确认 Agent 正在产生日志**
   - Token 统计依赖 Agent 的日志输出
   - 不同 Agent 的日志格式可能不同

4. **检查更新间隔**
   - 默认 30 秒更新一次
   - 如需更频繁更新，减小 `token_stats.update_interval` 值

### 4.3 天气不刷新

**症状：** 天气面板显示旧数据或无数据

**排查步骤：**

1. **确认天气服务已启用**
   - `config.json` 中 `weather.enabled` 应为 `true`

2. **确认 API 密钥有效**
   - `weather.api_key` 必须填写有效的 OpenWeatherMap API 密钥
   - 注册地址：https://openweathermap.org/api
   - 免费账户每分钟限制 60 次调用

3. **确认城市名称正确**
   - 使用英文城市名或拼音，如 `Beijing`, `Shanghai`
   - 避免使用中文城市名

4. **检查网络连接**
   - PC 端需要能访问 `api.openweathermap.org`
   - 如使用代理，需配置系统代理环境变量

5. **自适应刷新率**
   - Agent 工作中：10 分钟刷新
   - 普通状态：30 分钟刷新（默认）
   - Agent 空闲：1 小时刷新
   - 这是正常行为，不是故障

6. **缓存机制**
   - 天气数据缓存在 `weather.cache_file` 指定的文件中
   - 网络不可用时自动使用缓存
   - 删除缓存文件可强制重新获取

---

## 五、固件问题

### 5.1 编译失败

**常见错误及解决方法：**

| 错误信息 | 原因 | 解决方法 |
|----------|------|----------|
| `NimBLEDevice.h: No such file` | 缺少 NimBLE 库 | `pio lib install` 自动安装依赖 |
| `ArduinoJson.h: No such file` | 缺少 ArduinoJson 库 | 同上 |
| `esp_sleep.h: No such file` | ESP-IDF 版本不匹配 | 检查 `platformio.ini` 中的 framework 版本 |
| `PSRAM not available` | 开发板不支持 PSRAM | 确认使用 ESP32-S3（带 PSRAM 版本） |
| `region 'dram' overflowed` | 内存溢出 | 检查全局变量大小，启用 PSRAM |

**通用解决步骤：**

```bash
# 清理编译缓存
cd esp32_firmware
pio run -t clean

# 重新编译
pio run

# 如仍有问题，删除 .pio 目录后重试
rm -rf .pio
pio run
```

### 5.2 烧录失败

**排查步骤：**

1. **检查 USB 连接**
   - 使用数据线而非充电线
   - 尝试不同的 USB 端口
   - 避免使用 USB Hub

2. **进入下载模式**
   - 按住 BOOT 键不放
   - 按一下 RST 键
   - 松开 BOOT 键
   - 此时设备进入下载模式，重新烧录

3. **检查串口权限**
   - Windows：确认设备管理器中 COM 端口无黄色感叹号
   - 如需安装驱动：https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers

4. **降低烧录波特率**
   ```ini
   # platformio.ini 中添加
   upload_speed = 115200
   ```

### 5.3 OTA 升级失败

**排查步骤：**

1. **确认网络稳定**
   - OTA 依赖 WiFi 传输固件数据
   - 网络中断会导致升级失败

2. **确认固件大小**
   - OTA 分区有大小限制
   - 使用 `pio run` 查看固件大小

3. **回滚机制**
   - 如果新固件导致崩溃，ESP32 自动回滚到上一版本
   - 首次成功接收 PC 端数据包后才确认新固件有效

4. **恢复方法**
   - OTA 失败后可通过 USB 烧录恢复
   - 进入下载模式（BOOT+RST），使用 `pio run -t upload` 重新烧录

---

## 六、日志分析方法

### 6.1 ESP32 串口日志

```bash
# 连接串口监视器
cd esp32_firmware
pio device monitor --baud 115200
```

**关键日志标签：**

| 标签 | 含义 |
|------|------|
| `[Heap]` | 堆内存使用情况（Internal + PSRAM） |
| `[Stack]` | 任务栈剩余空间 |
| `[FPS]` | 实际渲染帧率 |
| `[Light]` | 光照传感器读数 |
| `[Thermal]` | CPU 温度与降频状态 |
| `CommTask` | 通信任务状态 |
| `RenderTask` | 渲染任务状态 |
| `Pixel` | 像素动画相关操作 |
| `BLE` | 蓝牙配网状态 |
| `OTA` | 固件升级状态 |
| `Panic` | 崩溃信息 |

### 6.2 PC 端日志

日志文件：`pc_monitor/pc_monitor.log`

**关键日志内容：**

| 关键字 | 含义 |
|--------|------|
| `状态已发送` | 成功向设备发送 Agent 状态 |
| `天气已发送` | 成功向设备发送天气数据 |
| `Token统计已发送` | 成功向设备发送 Token 数据 |
| `无法连接到ESP32设备` | TCP 连接失败 |
| `配置验证警告` | config.json 配置项有问题 |
| `HealthGuard` | 线程健康守护器状态（自动重启崩溃线程） |
| `OTLP转发` | OTLP 思考链数据转发记录 |

### 6.3 日志级别调整

**ESP32 端：**

在 `config.h` 中设置：
```cpp
#define DEBUG_SERIAL 1  // 1=启用详细日志, 0=仅错误日志
```

**PC 端：**

在 `main.py` 中修改日志级别：
```python
logging.basicConfig(
    level=logging.DEBUG,    # DEBUG/INFO/WARNING/ERROR
    ...
)
```

### 6.4 常见日志模式速查

**正常启动序列（ESP32）：**
```
================================
桌面电子宠物 - ESP32-S3 (v2 Dual-Core)
================================
Double-buffer mode (no mutex needed)
初始化显示...
初始化蜂鸣器...
初始化触摸...
初始化BH1750光照传感器...
初始化DRV2605L触觉反馈...
连接WiFi...
Connected: 192.168.x.x
NTP sync started
初始化通信...
启动FreeRTOS双核任务...
CommTask@Core0, RenderTask@Core1
```

**正常运行时的周期日志：**
```
[Heap] Internal Free=xxx B, MaxAlloc=xxx B | PSRAM Free=xxx B, MaxAlloc=xxx B
[Stack] renderTask remaining=xxx B (min safe: 512)
[FPS] 50.0 fps (50 frames in 1000 ms)
[Light] 256 lux → PWM 160
```

**异常模式：**
```
45s无数据，进入OFFLINE模式          → PC 端停止发送数据
THERMAL WARNING 56.3°C → CPU 160MHz → CPU 过热降频
OOM circuit breaker: Free=xxx B      → 内存不足，跳过解析
Panic detected! Count: N             → 设备发生崩溃
```
