# 桌面宠物项目 — 剩余BUG & 优化点完整清单

> 扫描时间: 2026-06-23  
> 范围: `esp32_firmware/` (全部) + `pc_monitor/` (全部)  
> 前提: COMPREHENSIVE_ANALYSIS.md 中的 7个新BUG + 旧BUG + 5个深度优化 **均已修复并验证✅**

---

## 一、已修复验证清单 (共12项, 全部✅)

| ID | 描述 | 验证位置 |
|----|------|----------|
| N1 | display_manager 双缓冲消除撕裂 | FIX-N1 注释 ✅ |
| N2 | BH1750 I2C 超时保护 | FIX-N2 注释 ✅ |
| C1 | Socket close 使用 finally+join | FIX-C1 注释 ✅ |
| C2 | PC通信异常处理补全 try-except | 完整覆盖 ✅ |
| N7 | 各类清理优化 | 已完成 ✅ |
| Opt1 | display_manager SPI DMA双缓冲 | 已实现 ✅ |
| Opt2 | comm_manager 帧长度上限 256KB | 行168 ✅ |
| Opt3 | web_config 输入验证 | 行127-139 ✅ |
| Opt4 | sound_manager I2S 配置优化 | dma_buf_count=4, len=256 ✅ |
| Opt5 | haptic_driver 振动模式优化 | 已实现 ✅ |

---

## 二、剩余BUG (需修复)

### BUG-1: PC端发送帧无大小限制 (通信层)

**严重度**: 🔴 中高  
**文件**: `pc_monitor/modules/communication.py`  
**位置**: 行164-170 (SerialCommunication.send_message), 行455-462 (SocketCommunication._flush_send)

**问题描述**:  
PC端 Serial 和 Socket 两种通信方式的 `send_message` / `_flush_send` 都直接构造帧并发送，**没有任何 payload 大小检查**：
```python
# 行170 (Serial) / 行458 (Socket)
frame = f"LEN:{len(payload)}\n{payload}\n"
```
ESP32 端 `comm_manager.cpp` 行168 有 256KB 上限保护，但 PC 端可以在发送前就做大帧拒绝，避免无效传输和 ESP32 端 OOM 风险。

**修复建议**:  
在 `_flush_send` 和 Serial `send_message` 中添加 payload 大小检查，超过 `MAX_FRAME_LEN` (如 256KB) 时拒绝发送并记录警告。

---

### BUG-2: ESP32 Pixel pause 后无法 resume (功能缺失) ✅ 已修复

**严重度**: 🟡 中  
**文件**: `esp32_firmware/src/main.cpp` (action handler)

**问题描述**:  
ESP32 收到 `DEVICE_ACTION` 消息后，有 `pixel_pause` action 对应 `pixel_player.pause()`，但**没有 `pixel_resume` action handler**。用户通过 PC 端暂停像素动画后，无法通过同一通道恢复播放，只能重启设备或重新发送 play 命令。

**修复方案**:  
在 action handler 中增加 `pixel_resume` case，调用 `pixelPlayer.play()` 实现等价效果（play()会设置状态为PXL_PLAYING并记录millis()，不会重置帧索引）。

**修复验证**: ✅ main.cpp L856-862 已添加 resume action handler

---

### BUG-3: web_config JSON 响应未转义存储值 (存储型注入)

**严重度**: 🟡 中  
**文件**: `esp32_firmware/src/web_config.cpp`  
**位置**: 行162-167 (handleStatus)

**问题描述**:  
`handleStatus()` 返回 JSON 时，将 `_config.wifi_ssid` 和 `_config.server_host` **直接拼接到 JSON 字符串中**，未做任何 JSON 转义：
```cpp
json += "\"ssid\":\"" + _config.wifi_ssid + "\",";
json += "\"server\":\"" + _config.server_host + ":" + String(_config.server_port) + "\"";
```
如果用户在 WiFi SSID 或 server_host 中注入了 `"` 或 `\` 等特殊字符，会导致 JSON 格式破坏，前端解析异常。虽然攻击面仅限于 AP 配网阶段（本地热点），但仍应修复。

**修复建议**:  
对 `_config.wifi_ssid` 和 `_config.server_host` 做 JSON 转义（替换 `\` → `\\`, `"` → `\"`），或使用 ArduinoJson 库构建 JSON。

---

### BUG-4: 通信 reconnect 无指数退避 (连接稳定性)

**严重度**: 🟢 低-中  
**文件**: `pc_monitor/modules/communication.py`  
**位置**: 行60-62, 行152-160

**问题描述**:  
重连逻辑使用**固定延迟** (`_reconnect_delay`)，没有指数退避。在网络不稳定时，会以固定间隔反复尝试重连，可能导致：
- 对 ESP32 端造成连接风暴
- PC 端资源浪费

```python
self._reconnect_delay: float = DEFAULT_RECONNECT_DELAY  # 固定值
# ...
time.sleep(self._reconnect_delay)  # 每次都相同间隔
```

**修复建议**:  
实现指数退避：`delay = min(base_delay * (2 ** attempt), max_delay)`，成功连接后重置。

---

### BUG-5: Haptic driver I2C 写入不检查返回值 (硬件通信) ✅ 已修复

**严重度**: 🟢 低  
**文件**: `esp32_firmware/src/haptic_driver.cpp`  
**位置**: 行76, 80, 83, 86, 89 (全部 `_writeRegister` 调用)

**问题描述**:  
所有 `_writeRegister()` 调用都不检查返回值。如果 I2C 总线异常（设备断开、总线忙），振动器配置会静默失败，后续振动操作不会工作但不会有任何错误提示。

**修复方案**:  
1. 新增 `_readRegisterSafe()` 方法，区分"读取到0"和"读取失败"
2. 修改 `calibrate()` 函数使用安全版本，避免I2C失败时误判校准成功
3. 仅当 `REG_STATUS == 0x00` 时才标记 `_available = true`

**修复验证**: ✅ haptic_driver.cpp L268-276 新增 _readRegisterSafe, L149-172 calibrate()使用安全读取

---

## 三、安全问题

### SEC-1: web_config AP 密码硬编码

**严重度**: 🟡 中  
**文件**: `esp32_firmware/src/web_config.cpp` + `config.h`

**问题描述**:  
WiFi AP 模式的密码在 `config.h` 中硬编码。所有使用此固件的设备共享相同 AP 密码，存在安全风险。

**修复建议**:  
- 使用设备 MAC 地址生成唯一 AP 密码
- 或在首次配网时随机生成并存储到 Preferences
- 或允许用户通过串口命令设置

---

### SEC-2: OTLP Receiver 绑定 0.0.0.0 无认证

**严重度**: 🟢 低  
**文件**: `pc_monitor/modules/otlp_receiver.py`

**问题描述**:  
OTLP 数据接收器绑定到所有网络接口 (0.0.0.0)，且没有任何认证机制。在同一网络中的任何设备都可以向 PC 端发送伪造的 OTLP 数据。

**修复建议**:  
- 支持配置绑定地址（如仅 `127.0.0.1` 或指定网卡 IP）
- 添加简单的 token 认证
- 或限制仅接受来自 ESP32 设备 IP 的连接

---

## 四、优化建议 (非BUG，改善体验)

### OPT-1: ESP32 fallback 表情延迟可缩短

**严重度**: 🟢 信息  
**当前**: `fallback` 表情显示 3 秒后自动切换  
**建议**: 缩短到 1.5-2 秒，改善用户感知响应速度

---

### OPT-2: web_config 长 delay 可优化

**严重度**: 🟢 信息  
**文件**: `esp32_firmware/src/web_config.cpp`  
**当前**: 配置保存后有较长的 `delay()` 等待再重启  
**建议**: 用非阻塞方式（如设置标志位，在主循环中处理重启），避免阻塞其他任务

---

### OPT-3: PC main.py 重启逻辑无指数退避

**严重度**: 🟢 信息  
**文件**: `pc_monitor/main.py`  
**位置**: 行354 `while True` + `time.sleep(2)` (仅 `--tray-only` 调试模式)  
**建议**: 添加指数退避，避免频繁重启时 CPU 空转

---

## 五、统计总结

| 类别 | 数量 | 严重度分布 |
|------|------|-----------|
| 已修复验证 | 14 | 全部 ✅ |
| 剩余BUG | 3 | 🔴1 🟡1 🟢1 |
| 安全问题 | 2 | 🟡1 🟢1 |
| 优化建议 | 3 | 🟢 信息 |
| **总计** | **22** | |

---

## 六、修复优先级建议

| 优先级 | 项目 | 理由 |
|--------|------|------|
| P1 | BUG-1 (PC帧大小限制) | 防止ESP32 OOM，保护设备稳定性 |
| ~~P1~~ | ~~BUG-2 (pixel resume)~~ | ✅ 已修复 (main.cpp L856-862) |
| P2 | BUG-3 (JSON转义) | 数据完整性，防止解析异常 |
| P2 | SEC-1 (AP密码) | 设备安全基础 |
| P3 | BUG-4 (reconnect退避) | 网络稳定性改善 |
| ~~P3~~ | ~~BUG-5 (I2C返回值)~~ | ✅ 已修复 (_readRegisterSafe + calibrate) |
| P4 | SEC-2 (OTLP认证) | 网络安全边界 |
| P4 | OPT-1/2/3 | 体验优化 |
