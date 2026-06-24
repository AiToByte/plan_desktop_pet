# 设备配网全流程

> 本文档详细描述桌面宠物 ESP32 设备的配网机制，涵盖所有配网方式的优先级链、实现细节和 PC 端配合流程。
> 源码参考: `wifi_manager.cpp`, `ble_config.cpp`, `web_config.cpp`, `communication.py`

---

## 一、配网优先级链

设备上电后，WiFi 连接采用**逐级降级**策略，优先使用已保存的配置，失败后依次尝试各种自动发现和手动配网方式。

```
┌─────────────────────────────────────────────────────────────────┐
│                    设备上电 / 重启                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  方式1: Flash Preferences │
              │  读取 NVS 已保存配置       │
              │  命名空间: pet_config      │
              └────────────┬───────────┘
                           │
                    有配置且连接成功?
                    ┌──────┴──────┐
                    │ YES         │ NO
                    ▼             ▼
              ┌──────────┐   ┌────────────────────────┐
              │ 连接成功!  │   │ 方式2: mDNS 自动发现     │
              │ 启动mDNS  │   │ 查询 _deskpet._tcp.local│
              │ 进入正常   │   └────────────┬───────────┘
              │ 运行模式   │                │
              └──────────┘          发现服务器?
                                   ┌──────┴──────┐
                                   │ YES         │ NO
                                   ▼             ▼
                             保存到Flash    ┌────────────────────────┐
                             重试连接       │ 方式3: UDP 广播发现      │
                                           │ 端口 19877               │
                                           │ 等待 DESKTOP_PET_SERVER  │
                                           └────────────┬───────────┘
                                                        │
                                                  发现服务器?
                                                  ┌──────┴──────┐
                                                  │ YES         │ NO
                                                  ▼             ▼
                                            保存到Flash    ┌──────────────────────┐
                                            重试连接       │ 方式4: BLE 配网        │
                                                          │ NimBLE, 120秒超时       │
                                                          │ Service UUID: 0x1820    │
                                                          └────────────┬───────────┘
                                                                       │
                                                                 BLE配网成功?
                                                                 ┌──────┴──────┐
                                                                 │ YES         │ NO / 超时
                                                                 ▼             ▼
                                                           保存到Flash    ┌──────────────────────┐
                                                           重试连接       │ 方式5: Web AP 配网     │
                                                                         │ 热点: DeskPet-Config   │
                                                                         │ Captive Portal         │
                                                                         │ 永久等待直到配置成功     │
                                                                         └──────────────────────┘
```

---

## 二、方式1: Flash Preferences

**最快路径** — 直接从 NVS 读取已保存的 WiFi 和服务器配置。

### 存储结构

```
命名空间: "pet_config"
┌──────────────┬──────────┬─────────────────────────┐
│ Key          │ 类型     │ 说明                     │
├──────────────┼──────────┼─────────────────────────┤
│ ssid         │ String   │ WiFi SSID               │
│ pass         │ String   │ WiFi 密码               │
│ host         │ String   │ 服务器 IP 地址           │
│ port         │ Int      │ 服务器端口 (默认 19876)  │
│ valid        │ Bool     │ 配置是否有效             │
└──────────────┴──────────┴─────────────────────────┘
```

### 连接流程

```cpp
// web_config.cpp - connectFromSaved()
bool WebConfig::connectFromSaved() {
    // 1. 检查 valid 标志
    if (!_config.valid) return false;

    // 2. 设置 STA 模式并连接
    WiFi.mode(WIFI_STA);
    WiFi.begin(_config.wifi_ssid.c_str(), _config.wifi_password.c_str());

    // 3. 等待连接，超时退出
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT) return false;
        delay(500);
    }
    return true;
}
```

### 关键细节

- NVS 使用 ESP32 Preferences 库，数据存储在 Flash 的 NVS 分区
- `pet_config` 命名空间在 `WebConfig::begin()` 时打开
- mDNS 和 UDP 发现模块也使用相同的命名空间和 Key 写入，确保一致性
- 配置重置通过 `Preferences::clear()` 清除整个命名空间

---

## 三、方式2: mDNS 自动发现

**局域网零配置发现** — 通过 mDNS 协议查询同一网络中的 PC 监控服务。

### 发现流程

```cpp
// wifi_manager.cpp - _tryMDNSDiscovery()
bool WiFiManager::_tryMDNSDiscovery() {
    // 1. 查询 mDNS 服务
    int n = MDNS.queryService("deskpet", "tcp");

    // 2. 取第一个结果
    String ip = MDNS.IP(0).toString();
    int port = MDNS.port(0);

    // 3. 保存到 Flash
    Preferences prefs;
    prefs.begin("pet_config", false);
    prefs.putString("host", ip);
    prefs.putInt("port", port);
    prefs.putBool("valid", true);
    prefs.end();

    return true;
}
```

### 服务注册

PC 端启动时注册 mDNS 服务:

```python
# communication.py
MDNS_HOSTNAME = "deskpet.local"
# 注册服务: _deskpet._tcp.local.
```

ESP32 端连接成功后也注册自身:

```cpp
// wifi_manager.cpp - _startMDNS()
MDNS.begin("deskpet");
MDNS.addService("deskpet", "tcp", server_port);
```

### mDNS 服务类型

```
服务名: _deskpet._tcp.local.
协议:   TCP
端口:   19876 (PC 监控程序默认端口)
```

### 前置条件

- 设备必须已经连接到 WiFi（需要 SSID 和密码已配置）
- PC 端必须已启动并注册了 mDNS 服务
- 设备和 PC 在同一局域网段

---

## 四、方式3: UDP 广播发现

**无需 mDNS 依赖** — PC 端周期性广播自身地址，设备监听并自动保存。

### 广播协议

```
端口: 19877
格式: DESKTOP_PET_SERVER:<IP>:<PORT>
示例: DESKTOP_PET_SERVER:192.168.1.100:19876
```

### PC 端广播实现

```python
# communication.py
DEFAULT_UDP_BROADCAST_PORT = 19877
DEFAULT_UDP_BROADCAST_INTERVAL = 5  # 每 5 秒广播一次
```

### 设备端监听实现

```cpp
// wifi_manager.cpp - tryUDPDiscovery()
bool WiFiManager::tryUDPDiscovery(unsigned long timeoutMs) {
    WiFiUDP udp;
    udp.begin(19877);  // 监听广播端口

    unsigned long start = millis();
    char buf[128];

    while (millis() - start < timeoutMs) {
        int packetSize = udp.parsePacket();
        if (packetSize > 0 && packetSize < sizeof(buf)) {
            int len = udp.read(buf, sizeof(buf) - 1);
            buf[len] = '\0';

            String msg = String(buf);
            if (msg.startsWith("DESKTOP_PET_SERVER:")) {
                // 解析 IP 和端口
                String payload = msg.substring(19);
                int colonIdx = payload.indexOf(':');
                String ip = payload.substring(0, colonIdx);
                int port = payload.substring(colonIdx + 1).toInt();

                // 保存到 Flash
                Preferences prefs;
                prefs.begin("pet_config", false);
                prefs.putString("host", ip);
                prefs.putInt("port", port);
                prefs.putBool("valid", true);
                prefs.end();

                return true;
            }
        }
        delay(10);
    }
    return false;
}
```

### 超时配置

- 默认超时: 使用 `timeoutMs` 参数（由 `connect()` 调用时传入）
- 轮询间隔: 10ms
- PC 广播间隔: 5 秒

### 优势

- 不依赖 mDNS 协议栈
- 跨子网可达（如果路由器转发广播）
- 实现简单，PC 端只需 UDP 发送

---

## 五、方式4: BLE 配网

**无 WiFi 环境下的配网方案** — 通过蓝牙低功耗将 WiFi 凭据写入设备。

### BLE 服务定义

```
Service UUID:  0x1820 (自定义配网服务)
┌──────────────┬──────────┬──────────┬──────────────────────┐
│ Characteristic│ UUID     │ 属性     │ 说明                  │
├──────────────┼──────────┼──────────┼──────────────────────┤
│ SSID         │ 0x2A69   │ 读/写    │ WiFi 名称 (最大32字节) │
│ Password     │ 0x2A6A   │ 写       │ WiFi 密码 (最大64字节) │
│ Resource URL │ 0x2A6B   │ 读/写    │ 资源URL (最大128字节)  │
│ Status       │ 0x2A6C   │ 读/通知  │ 配网状态反馈           │
└──────────────┴──────────┴──────────┴──────────────────────┘
```

### 状态机

```
BLE_CONFIG_IDLE (空闲)
       │
       ▼
BLE_CONFIG_ADVERTISING (广播中) ←──────────┐
       │                                    │
       ▼                                    │ (客户端断连且仍在配网)
BLE_CONFIG_CONNECTED (已连接)                │
       │                                    │
       ▼                                    │
BLE_CONFIG_CREDENTIALS (凭据就绪) ──────────┘
       │
       ▼
    WiFi 连接尝试
```

### 配网流程

```
┌──────────┐                    ┌──────────┐
│  手机APP  │                    │  ESP32   │
└────┬─────┘                    └────┬─────┘
     │  1. 扫描BLE广播               │
     │  (Service 0x1820)             │
     │ ◄────────────────────────────│ 开始广播(120s超时)
     │                               │
     │  2. 连接                       │
     │ ─────────────────────────────►│ onConnect()
     │                               │ 状态→CONNECTED
     │                               │
     │  3. 写入SSID (0x2A69)         │
     │ ─────────────────────────────►│ 保存到 _credentials.ssid
     │                               │
     │  4. 写入密码 (0x2A6A)         │
     │ ─────────────────────────────►│ 标记 _hasNewCredentials=true
     │                               │ 状态→CREDENTIALS
     │                               │
     │  5. (可选) 写入URL (0x2A6B)   │
     │ ─────────────────────────────►│ 保存到 _credentials.resourceUrl
     │                               │
     │  6. 读取状态 (0x2A6C)         │
     │ ◄────────────────────────────│ 通知: CREDENTIALS
     │                               │
     │                               │ 7. 尝试WiFi连接
     │                               │    成功→保存到Flash
     │                               │    失败→等待重试
```

### 关键实现细节

```cpp
// ble_config.cpp
BleConfigManager::BleConfigManager()
    : _advTimeout(300) {}  // 默认广播超时300秒

// 密码写入回调 - 收到密码后自动标记凭据就绪
void BleConfigPassCallbacks::onWrite(NimBLECharacteristic* pChar) {
    _mgr._credentials.password = pChar->getValue().c_str();
    if (_mgr._credentials.ssid.length() > 0) {
        _mgr._hasNewCredentials = true;
        _mgr.setState(BLE_CONFIG_CREDENTIALS);
    }
}
```

### 配网超时

- BLE 广播超时: 120 秒（由 `connect()` 传入）
- 超时后自动降级到 Web AP 配网模式
- 发射功率: `ESP_PWR_LVL_P6`（增强功率，扩大覆盖范围）

---

## 六、方式5: Web AP 配网

**最终兜底方案** — 设备创建 WiFi 热点，用户通过浏览器配置。

### 热点参数

```
SSID:     DeskPet-Config
密码:     12345678
IP 地址:  192.168.4.1
端口:     80
超时:     CONFIG_TIMEOUT (配置页面超时后自动重启)
```

### Web 路由

```
┌────────────┬──────────┬────────────────────────────────┐
│ 路径       │ 方法     │ 功能                            │
├────────────┼──────────┼────────────────────────────────┤
│ /          │ GET      │ 配置页面 (响应式HTML表单)        │
│ /save      │ POST     │ 保存配置 (WiFi+服务器地址)       │
│ /reset     │ GET      │ 重置配置 (清空NVS)              │
│ /status    │ GET      │ 返回JSON状态                    │
│ /ota       │ GET      │ OTA升级页面                     │
│ /update    │ POST     │ 上传固件 (multipart/form-data)  │
│ /rollback  │ POST     │ 回滚到上一版本                   │
└────────────┴──────────┴────────────────────────────────┘
```

### 配置页面功能

```
┌─────────────────────────────────────┐
│         🤖 桌面宠物配网              │
│                                     │
│  📶 WiFi名称:  [________________]   │
│  🔑 WiFi密码:  [________________]   │
│     (开放网络可留空)                  │
│  ─────────────────────────────────  │
│  🖥️ 服务器地址: [________________]   │
│  🔌 服务器端口: [19876]             │
│     (默认端口19876，一般无需修改)     │
│                                     │
│  [✅ 保存并连接]                     │
│  [📦 固件升级(OTA)]                  │
│  ─────────────────────────────────  │
│  [🔄 重置配置]                       │
│                                     │
│  配置将保存到设备，重启后自动连接      │
└─────────────────────────────────────┘
```

### 输入验证

```cpp
// web_config.cpp - handleSave()
void WebConfig::handleSave() {
    String ssid = _server->arg("ssid");
    String password = _server->arg("password");
    String serverHost = _server->arg("server_host");
    String serverPort = _server->arg("server_port");

    // 验证: SSID 不能为空
    if (ssid.length() == 0) {
        _server->send(400, "text/html", getErrorPageHTML("WiFi名称不能为空"));
        return;
    }
    // 验证: 服务器地址不能为空
    if (serverHost.length() == 0) {
        _server->send(400, "text/html", getErrorPageHTML("服务器地址不能为空"));
        return;
    }
    // 端口验证: 1-65535，无效值使用默认端口
    int port = serverPort.toInt();
    if (port <= 0 || port > 65535) {
        port = SERVER_PORT;
    }

    // 保存到 Flash 并重启
    saveToFlash(ssid, password, serverHost, port);
    _server->send(200, "text/html", getSuccessPageHTML());
    delay(3000);
    ESP.restart();
}
```

### 配置重置

```cpp
// web_config.cpp - handleReset()
void WebConfig::handleReset() {
    resetConfig();           // 清空 NVS
    _server->send(200, "text/html", getSuccessPageHTML());
    delay(3000);
    ESP.restart();           // 重启后进入配网流程
}
```

### Captive Portal 机制

当用户连接热点后，手机/电脑会自动弹出配置页面（部分设备需要手动打开浏览器访问 `192.168.4.1`）。ESP32 Web 服务器运行在 AP 模式下，所有 HTTP 请求都会被响应。

---

## 七、PC 端配合配置

### 自动发现服务

PC 端监控程序启动后，自动运行两个发现服务:

1. **mDNS 服务注册** — 局域网内设备可通过 `_deskpet._tcp.local.` 发现 PC
2. **UDP 广播** — 每 5 秒向端口 19877 广播服务器地址

### 发现消息格式

```
协议: UDP
端口: 19877
格式: DESKTOP_PET_SERVER:<IP>:<PORT>
示例: DESKTOP_PET_SERVER:192.168.1.100:19876
```

### 配置流程 (PC 视角)

```
┌─────────────────────────────────────────────────────────┐
│                    PC 监控程序启动                         │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 1. 启动 TCP 服务器       │
              │    监听端口 19876        │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 2. 注册 mDNS 服务        │
              │    _deskpet._tcp.local  │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 3. 启动 UDP 广播线程     │
              │    端口 19877, 5秒间隔   │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 4. 等待设备连接          │
              │    TCP 握手 + 帧协议     │
              └────────────────────────┘
```

### 设备连接握手

设备连接成功后发送握手消息:

```json
{
    "type": "handshake",
    "device": "esp32s3",
    "version": "2.0.0"
}
```

PC 端收到后进入正常数据交换模式。

---

## 八、配网方式对比

| 特性 | Flash | mDNS | UDP | BLE | Web AP |
|------|-------|------|-----|-----|--------|
| 速度 | 即时 | 1-3 秒 | 1-5 秒 | 30-120 秒 | 2-5 分钟 |
| 需要已配 WiFi | 是 | 是 | 是 | 否 | 否 |
| 需要 PC 在线 | 否 | 是 | 是 | 否 | 否 |
| 需要手机 APP | 否 | 否 | 否 | 是 | 否 |
| 需要浏览器 | 否 | 否 | 否 | 否 | 是 |
| 用户交互 | 无 | 无 | 无 | 手机操作 | 浏览器操作 |
| 适用场景 | 日常启动 | 首次配网 | 首次配网 | 无路由器 | 最终兜底 |

---

## 九、故障排查

### 配网失败排查流程

```
设备无法连接?
├── Flash 有配置但连接失败?
│   ├── WiFi SSID/密码是否正确?
│   ├── 路由器是否在线?
│   └── 信号强度是否足够?
│
├── mDNS 发现失败?
│   ├── PC 端是否已启动?
│   ├── 是否在同一网段?
│   └── 防火墙是否阻止 mDNS (5353/udp)?
│
├── UDP 发现失败?
│   ├── PC 端 UDP 广播是否开启?
│   ├── 端口 19877 是否被占用?
│   └── 路由器是否转发广播?
│
├── BLE 配网失败?
│   ├── 手机是否支持 BLE 4.0+?
│   ├── NimBLE 库是否编译启用?
│   └── 120 秒超时是否足够?
│
└── Web AP 配网失败?
    ├── 热点是否可见 (DeskPet-Config)?
    ├── 密码是否正确 (12345678)?
    └── 浏览器是否访问 192.168.4.1?
```

### 日志关键字

```
WiFi Manager:
  "Saved config failed"     → Flash 配置连接失败，尝试自动发现
  "mDNS discovery OK"       → mDNS 发现成功
  "UDP Discovery: 发现服务器" → UDP 发现成功
  "BLE timeout/failed"      → BLE 配网超时，降级到 AP 模式
  "Web配网模式已启动"        → 进入 AP 配网模式

Web Config:
  "Config saved to Flash"   → 配置已保存
  "Config reset"            → 配置已重置
  "No saved config in Flash" → Flash 中无有效配置

BLE Config:
  "SSID received"           → BLE 收到 SSID
  "Credentials complete!"   → BLE 凭据就绪
  "Advertising timeout"     → BLE 广播超时
```
