# 通信栈实现解析

本文档深入解析 ESP32 桌面宠物固件的通信栈架构，涵盖 TCP 帧协议状态机、非阻塞 I/O、自动重连、WiFi 管理及多种配网方案。

---

## 一、CommManager 类结构

`CommManager` 是整个通信栈的核心，封装了与 PC 服务端的 TCP 连接、帧协议解析和自动重连逻辑。

### 1.1 成员变量

```cpp
class CommManager {
private:
    WiFiClient _client;              // Arduino TCP 客户端
    bool _connected;                 // 连接状态标志
    String _lastData;                // 最近一次收到的完整 JSON
    bool _hasNewData;                // 新数据就绪标记（读后自动清除）
    unsigned long _lastReconnect;    // 上次重连时间戳
    unsigned long _lastReceiveTime;  // 最后收到数据的时间戳（用于离线检测）
    unsigned long _reconnectInterval;// 当前重连间隔（指数退避）
    uint8_t _reconnectFailCount;    // 连续失败计数
    String _serverHost;              // PC 服务端 IP
    int _serverPort;                 // PC 服务端端口

    // 批量读取缓冲区
    char _readBuf[CLIENT_READ_BUF_SIZE];  // 512 字节

    // 帧协议状态机
    FrameState _frameState;    // 当前状态
    String _lenBuffer;         // 累积 "LEN:" 前缀
    String _frameBuffer;       // 累积完整帧 payload
    int _expectedLen;          // 期望的 payload 字节数
};
```

### 1.2 公开接口

| 方法 | 说明 |
|------|------|
| `begin()` | 初始化缓冲区和状态机 |
| `setServer(host, port)` | 设置 PC 服务端地址 |
| `connect()` | 发起 TCP 连接，配置 Keep-Alive，发送握手 |
| `disconnect()` | 断开连接，重置状态机 |
| `reconnect()` | 指数退避重连（含 WiFi 硬重置保护） |
| `update()` | 主循环调用：非阻塞读取 + 状态机驱动 |
| `isConnected()` | 检查连接状态 |
| `hasNewData()` | 是否有新数据（读取后自动清除） |
| `getData()` | 获取最近一帧的 JSON 字符串 |
| `sendFramed(json)` | 发送带长度前缀的帧 |
| `sendHeartbeat()` | 发送心跳包 |
| `sendMessage(type, data)` | 发送业务消息 |

---

## 二、TCP 帧协议状态机

### 2.1 帧格式

采用**长度前缀帧协议**（v2），兼容旧版换行分隔格式（v1 legacy）：

```
新格式:  LEN:<length>\n<payload>
示例:    LEN:42\n{"type":"heartbeat","ts":12345}\n

旧格式:  <JSON>\n
示例:    {"type":"heartbeat","ts":12345}\n
```

### 2.2 四状态枚举

```cpp
enum FrameState {
    FRAME_IDLE,        // 空闲：等待新帧起始字节
    FRAME_READ_LEN,    // 读取长度头：累积 "LEN:NNNN\n"
    FRAME_READ_BODY,   // 读取帧体：按长度精确读取 payload
    FRAME_LEGACY_LINE  // 兼容模式：以换行符 \n 为分隔
};
```

### 2.3 状态转换图

```
                     收到 'L'
    FRAME_IDLE ──────────────────────► FRAME_READ_LEN
        │                                    │
        │ 收到 '{'                           │ 收到 '\n' 且 header 合法
        ▼                                    ▼
    FRAME_LEGACY_LINE               FRAME_READ_BODY
        │                                    │
        │ 收到 '\n'                          │ 累积字节 >= expectedLen
        ▼                                    ▼
    processData() ◄─────────────────── processData()
        │                                    │
        └──────────► FRAME_IDLE ◄────────────┘
```

### 2.4 状态机核心代码

**FRAME_IDLE -- 帧起始检测：**

```cpp
case FRAME_IDLE:
    if (c == 'L') {
        _lenBuffer = "L";           // 开始累积长度头
        _frameState = FRAME_READ_LEN;
    } else if (c == '{') {
        _frameBuffer = "{";         // 旧格式：整行 JSON
        _frameState = FRAME_LEGACY_LINE;
    }
    // 其他字符（空白、噪声）直接丢弃
    break;
```

**FRAME_READ_LEN -- 解析长度头：**

```cpp
case FRAME_READ_LEN:
    if (c == '\n') {
        // 期望格式: "LEN:NNNN"
        if (_lenBuffer.startsWith("LEN:")) {
            _expectedLen = atoi(_lenBuffer.substring(4).c_str());
            // 安全检查: 0 < len <= 256KB（ESP32-S3 有 320KB PSRAM）
            if (_expectedLen > 0 && _expectedLen <= 256 * 1024) {
                _frameBuffer.reserve(_expectedLen);
                _frameState = FRAME_READ_BODY;
            } else {
                _frameState = FRAME_IDLE;  // 非法长度，丢弃
            }
        } else {
            _frameState = FRAME_IDLE;      // 非法头，丢弃
        }
        _lenBuffer = "";
    } else {
        _lenBuffer += c;
        if (_lenBuffer.length() > 16) {    // 防超长 header 攻击
            _frameState = FRAME_IDLE;
            _lenBuffer = "";
        }
    }
    break;
```

**FRAME_READ_BODY -- 读取帧体：**

```cpp
case FRAME_READ_BODY:
    _frameBuffer += c;
    if ((int)_frameBuffer.length() >= _expectedLen) {
        processData(_frameBuffer);         // 完整帧 → 处理
        _frameBuffer = "";
        _frameState = FRAME_IDLE;
    }
    // 防 OOM: 帧体超过 128KB 强制丢弃
    if ((int)_frameBuffer.length() > 128 * 1024) {
        _frameBuffer = "";
        _frameState = FRAME_IDLE;
    }
    break;
```

**FRAME_LEGACY_LINE -- 兼容旧格式：**

```cpp
case FRAME_LEGACY_LINE:
    if (c == '\n') {
        processData(_frameBuffer);
        _frameBuffer = "";
        _frameState = FRAME_IDLE;
    } else {
        _frameBuffer += c;
        if (_frameBuffer.length() > 32 * 1024) {  // 旧格式 32KB 上限
            _frameBuffer = "";
            _frameState = FRAME_IDLE;
        }
    }
    break;
```

---

## 三、非阻塞读取

### 3.1 read() vs readBytes()

`WiFiClient` 提供两种读取方式：

| 方法 | 行为 | 阻塞 |
|------|------|------|
| `read(buf, len)` | 仅读取当前 `available()` 的字节 | 不阻塞 |
| `readBytes(buf, len)` | 等待凑满 `len` 字节或超时 | 阻塞 |

固件**全部使用 `read()`**，避免阻塞主循环导致看门狗复位。

### 3.2 批量读取流程

```cpp
while (_client.connected() && _client.available()) {
    // 一次最多读取 512 字节（CLIENT_READ_BUF_SIZE）
    size_t bytesRead = _client.read(
        (uint8_t*)_readBuf,
        min((int)CLIENT_READ_BUF_SIZE, _client.available())
    );

    for (size_t i = 0; i < bytesRead; i++) {
        char c = _readBuf[i];
        // 逐字节送入状态机...
    }
}
```

### 3.3 帧体批量写入优化

在 `FRAME_READ_BODY` 状态下，避免逐字节 `String` 追加（产生大量堆分配），改为从 `_readBuf` 直接批量拷贝：

```cpp
if (_frameState == FRAME_READ_BODY && i < bytesRead) {
    int remaining = _expectedLen - (int)_frameBuffer.length();
    int available = (int)(bytesRead - i);
    int toCopy = min(remaining, available);

    if (toCopy > 0) {
        _frameBuffer.concat(&_readBuf[i], toCopy);  // 批量追加
        i += toCopy - 1;  // 跳过已拷贝字节（for 循环会 i++）
    }
}
```

此优化将 10KB 帧的处理从约 10000 次 `String::operator+=` 降低到约 20 次 `concat`，显著减少堆碎片。

---

## 四、TCP Keep-Alive

### 4.1 配置参数

TCP 连接建立后立即配置 Keep-Alive，用于检测以下死连接场景：

- 路由器 NAT 表超时清除
- PC 服务端进程崩溃（未发送 FIN）
- 网线被拔或 WiFi 断开但未触发 FIN

```cpp
int fd = _client.fd();          // 获取底层 socket fd
int enable = 1;
setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &enable, sizeof(enable));

int idle = 60;                  // 空闲 60 秒后开始探测
setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));

int intvl = 10;                 // 每 10 秒探测一次
setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));

int cnt = 3;                    // 连续 3 次无响应判定断开
setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof(cnt));
```

### 4.2 参数说明

| 参数 | 值 | 含义 |
|------|-----|------|
| `SO_KEEPALIVE` | 1 | 启用 TCP 层保活 |
| `TCP_KEEPIDLE` | 60s | 连接空闲 60 秒后发送第一个探测包 |
| `TCP_KEEPINTVL` | 10s | 两次探测之间的间隔 |
| `TCP_KEEPCNT` | 3 | 连续 3 次探测无响应则关闭连接 |

### 4.3 断连检测时间

最坏情况下（最后一个数据包发送后立即断网），检测延迟为：

```
60s + 10s x 3 = 90 秒
```

实际场景中，固件还有 `update()` 中的 `_client.connected()` 检查，能在几秒内发现正常断连。Keep-Alive 主要覆盖"静默断连"场景。

---

## 五、重连机制

### 5.1 指数退避策略

```cpp
void CommManager::reconnect() {
    unsigned long now = millis();
    if (now - _lastReconnect < _reconnectInterval) {
        return;  // 未到退避时间，跳过
    }
    _lastReconnect = now;
    _reconnectFailCount++;

    disconnect();  // 先断开旧连接，防止 socket 泄漏

    // 连续失败 10 次 → WiFi 硬重置
    if (_reconnectFailCount >= 10) {
        WiFi.disconnect(true);
        delay(200);
        WiFi.begin();
        _reconnectFailCount = 0;
        _reconnectInterval = RECONNECT_INTERVAL;
        return;
    }

    connect();

    // 指数退避：interval = min(interval * 2, 60000)
    _reconnectInterval = min(_reconnectInterval * 2, (unsigned long)60000);
}
```

### 5.2 退避时间表

| 失败次数 | 间隔 | 累计等待 |
|----------|------|----------|
| 1 | 5s | 5s |
| 2 | 10s | 15s |
| 3 | 20s | 35s |
| 4 | 40s | 75s |
| 5 | 60s (上限) | 135s |
| 6 | 60s | 195s |
| ... | ... | ... |
| 10 | WiFi 硬重置 | - |

### 5.3 WiFi 硬重置

连续失败 10 次后执行 `WiFi.disconnect(true)` + `WiFi.begin()`，解决以下问题：

- DHCP 租约过期导致的 IP 冲突
- AP 关联状态异常（ESP32 与路由器之间的关联丢失）
- 省电模式切换后的射频状态异常

### 5.4 边沿触发断连检测

在 `update()` 末尾检查连接状态，采用**边沿触发**（而非电平触发）：

```cpp
if (!_client.connected()) {
    LOG_E("Connection lost!");
    _connected = false;
    WiFi.setSleep(true);  // 断连后启用 WiFi 省电模式
}
```

连接成功时在 `connect()` 中重置 `_reconnectFailCount = 0` 和 `_reconnectInterval`，确保退避状态被清除。

---

## 六、WiFiManager

`WiFiManager` 负责 WiFi STA 连接和多种自动发现机制。

### 6.1 类结构

```cpp
class WiFiManager {
public:
    void begin();                              // 初始化 WiFi STA 模式
    bool connect();                            // 尝试连接（含自动发现链）
    bool tryUDPDiscovery(unsigned long timeoutMs = 15000);  // UDP 广播发现
    void startConfigMode();                    // 启动 AP 配网模式
    void handleConfig();                       // 处理配网 Web 请求
    bool isConfiguring();                      // 是否正在配网
    bool isConnected();                        // WiFi 是否已连接
    String getIP();                            // 获取本机 IP
    String getServerHost();                    // 获取保存的服务端 IP
    int getServerPort();                       // 获取保存的服务端端口

private:
    WebConfig _webConfig;    // Web 配网模块
    bool _connected;
    unsigned long _lastAttempt;
    bool _configMode;

    void _startMDNS();
    bool _tryMDNSDiscovery();
};
```

### 6.2 mDNS 服务发现

ESP32 通过 mDNS 查询 `_deskpet._tcp.local.` 服务，自动获取 PC 服务端的 IP 和端口：

```cpp
bool WiFiManager::_tryMDNSDiscovery() {
    int n = MDNS.queryService("deskpet", "tcp");
    if (n == 0) return false;

    String ip = MDNS.IP(0).toString();
    int port = MDNS.port(0);

    // 保存到 Preferences
    Preferences prefs;
    prefs.begin("pet_config", false);
    prefs.putString("host", ip);
    prefs.putInt("port", port);
    prefs.putBool("valid", true);
    prefs.end();

    return true;
}
```

PC 端需运行 mDNS 服务，注册 `_deskpet._tcp` 服务类型。

### 6.3 UDP 广播发现

监听 UDP 端口 19877，等待 PC 服务端广播发现消息：

```cpp
bool WiFiManager::tryUDPDiscovery(unsigned long timeoutMs) {
    WiFiUDP udp;
    udp.begin(19877);

    while (millis() - start < timeoutMs) {
        int packetSize = udp.parsePacket();
        if (packetSize > 0) {
            // 格式: "DESKTOP_PET_SERVER:IP:PORT"
            String msg = String(buf);
            if (msg.startsWith("DESKTOP_PET_SERVER:")) {
                // 解析 IP 和端口，保存到 Preferences
                prefs.putString("host", ip);
                prefs.putInt("port", port);
                return true;
            }
        }
        delay(10);
    }
    return false;
}
```

PC 端需定期向局域网广播 `DESKTOP_PET_SERVER:<IP>:<PORT>` 消息。

---

## 七、BLE 配网

### 7.1 BLE 服务定义

基于 NimBLE-Arduino 库实现，比原生 ESP32 BLE 库节省约 30% 内存：

| 项目 | 值 |
|------|-----|
| 服务 UUID | `0x1820`（自定义配网服务） |
| SSID 特征 | `0x2A69`（读/写） |
| 密码特征 | `0x2A6A`（写） |
| 资源 URL 特征 | `0x2A6B`（写） |
| 状态特征 | `0x2A6C`（读/通知） |

### 7.2 配网状态码

```cpp
enum BleConfigState : uint8_t {
    BLE_CONFIG_IDLE = 0,         // 空闲
    BLE_CONFIG_ADVERTISING,      // 正在广播
    BLE_CONFIG_CONNECTED,        // 手机/PC 已连接
    BLE_CONFIG_CREDENTIALS,      // 凭据已接收
    BLE_CONFIG_CONNECTING_WIFI,  // 正在连接 WiFi
    BLE_CONFIG_WIFI_CONNECTED,   // WiFi 连接成功
    BLE_CONFIG_WIFI_FAILED,      // WiFi 连接失败
    BLE_CONFIG_DONE              // 配网完成
};
```

### 7.3 配网流程

```
ESP32 上电
    │
    ▼
无保存配置 ──► BLE 广播 "DeskPet-Setup"
                    │
                    ▼
           手机/PC 连接 BLE
                    │
                    ▼
           写入 SSID (0x2A69)
           写入 Password (0x2A6A)
           写入 URL (0x2A6B, 可选)
                    │
                    ▼
           ESP32 尝试连接 WiFi
           通过 Status (0x2A6C) 通知结果
                    │
                    ▼
           成功 → 保存到 Preferences → 退出 BLE
           失败 → 通知手机，等待重试
```

### 7.4 回调机制

使用 NimBLE 回调类实现事件驱动：

```cpp
class BleConfigSsidCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar) override {
        _mgr._credentials.ssid = pChar->getValue().c_str();
    }
};

class BleConfigPassCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar) override {
        _mgr._credentials.password = pChar->getValue().c_str();
        // 收到密码且 SSID 已有值 → 标记凭据就绪
        if (_mgr._credentials.ssid.length() > 0) {
            _mgr._hasNewCredentials = true;
            _mgr.setState(BLE_CONFIG_CREDENTIALS);
        }
    }
};
```

### 7.5 广播超时与重连

BLE 广播默认超时 120 秒。若客户端断开连接，自动重新广播：

```cpp
void onDisconnect(NimBLEServer* pServer) override {
    if (_mgr.isConfiguring()) {
        _mgr.startAdvertising(_mgr._advTimeout);  // 重新广播
    }
}
```

---

## 八、Web AP 配网

### 8.1 Captive Portal 模式

当所有自动发现方式均失败时，ESP32 启动 SoftAP 热点，提供 Web 配网页面：

| 参数 | 值 |
|------|-----|
| AP SSID | `Pet-Setup` |
| AP 密码 | `pet`（启动时根据 MAC 生成唯一密码覆盖） |
| Web 端口 | 80 |
| 配网超时 | 120 秒 |

### 8.2 WebConfig 类接口

```cpp
class WebConfig {
public:
    bool begin();              // 初始化，检查 Flash 中的配置
    bool connectFromSaved();   // 用保存的配置连接 WiFi
    void startAPMode();        // 启动 AP 配网模式
    void handleClient();       // 处理 Web 请求（loop 中调用）
    StoredConfig getConfig();  // 获取存储的配置
    void resetConfig();        // 清除 Flash 中的配置
    String getAPIP();          // 获取 AP 的 IP 地址

private:
    void handleRoot();         // 配网首页
    void handleSave();         // 保存配置
    void handleReset();        // 重置配置
    void handleStatus();       // 状态查询
    void handleOTA();          // OTA 升级页面
    void handleOTAUpload();    // OTA 固件上传
    void handleOTARollback();  // OTA 回滚
    void saveToFlash(...);     // 写入 Preferences
    bool loadFromFlash();      // 从 Preferences 读取
};
```

### 8.3 存储结构

配置保存在 ESP32 NVS（Non-Volatile Storage）的 `pet_config` 命名空间下：

```cpp
struct StoredConfig {
    String wifi_ssid;       // WiFi SSID
    String wifi_password;   // WiFi 密码
    String server_host;     // PC 服务端 IP
    int    server_port;     // PC 服务端端口
    bool   valid;           // 配置是否有效
};
```

### 8.4 OTA 固件升级

Web 配网页面同时提供 OTA 固件上传功能，支持回滚：

- `handleOTA()` -- 展示上传表单
- `handleOTAUpload()` -- 接收并写入固件分区
- `handleOTARollback()` -- 回滚到上一个固件分区

---

## 九、配网优先级链

`WiFiManager::connect()` 实现了多级自动发现和配网降级链：

### 9.1 优先级顺序

```
┌─────────────────────────────────────────────────────────┐
│                    WiFiManager::connect()                │
│                                                         │
│  1. Preferences (Flash)                                 │
│     connectFromSaved() ──► 成功 → 返回 true             │
│         │                                               │
│         ▼ 失败                                          │
│  2. mDNS 发现                                           │
│     _deskpet._tcp.local. ──► 找到 → 保存 → 重试连接     │
│         │                                               │
│         ▼ 失败                                          │
│  3. UDP 广播发现                                        │
│     端口 19877, 超时 15s ──► 找到 → 保存 → 重试连接     │
│         │                                               │
│         ▼ 失败                                          │
│  4. BLE 配网 (120s 超时)                                │
│     手机写入凭据 ──► 成功 → 保存 → 重试连接             │
│         │                                               │
│         ▼ 失败/超时                                     │
│  5. Web AP 配网                                         │
│     热点 "Pet-Setup" ──► 用户手动配置                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 9.2 流程代码

```cpp
bool WiFiManager::connect() {
    // 1. 优先使用保存的配置
    if (_webConfig.connectFromSaved()) {
        _connected = true;
        _startMDNS();
        return true;
    }

    // 2. mDNS 发现
    if (_tryMDNSDiscovery()) {
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _startMDNS();
            return true;
        }
    }

    // 3. UDP 广播发现
    if (tryUDPDiscovery()) {
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _startMDNS();
            return true;
        }
    }

    // 4. BLE 配网
#ifdef BLE_PROVISIONING_ENABLED
    BLEProvisioner ble;
    if (ble.startProvisioning(120000)) {
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _startMDNS();
            return true;
        }
    }
#endif

    // 5. 降级到 AP 配网
    startConfigMode();
    return false;
}
```

### 9.3 各阶段耗时估算

| 阶段 | 预期耗时 | 最大耗时 |
|------|----------|----------|
| Preferences 读取 + WiFi 连接 | 3-5s | 10s (WIFI_TIMEOUT) |
| mDNS 查询 | 1-3s | 5s |
| UDP 广播监听 | 1-5s | 15s (timeout) |
| BLE 配网 | 30-60s (用户操作) | 120s (超时) |
| Web AP 配网 | 用户操作 | 无超时 |

### 9.4 设计要点

1. **Preferences 优先**：正常启动时零网络开销，直接从 Flash 读取上次成功的配置
2. **mDNS 快速**：同局域网内 1-3 秒即可发现，适合 PC 端先启动的场景
3. **UDP 兜底**：mDNS 依赖组播，部分路由器不转发；UDP 广播更可靠
4. **BLE 零配网**：首次使用无需任何网络信息，手机扫码即可配置
5. **Web AP 兜底**：BLE 不可用时的最终手段，用户通过浏览器手动配置
6. **配置持久化**：mDNS 和 UDP 发现的服务端地址自动保存到 Flash，下次启动直接使用

---

## 附录：关键常量定义

```cpp
// config.h
#define SERVER_PORT          19876   // PC 服务端默认端口
#define RECONNECT_INTERVAL   5000    // 初始重连间隔 (ms)
#define CLIENT_TCP_TIMEOUT   10      // TCP 连接超时 (秒)
#define CLIENT_READ_BUF_SIZE 512     // 批量读取缓冲区大小
#define AP_SSID              "Pet-Setup"
#define AP_PASSWORD          "pet"
#define CONFIG_PORT          80      // Web 配网端口
#define CONFIG_TIMEOUT       120000  // 配网超时 (ms)
#define WIFI_TIMEOUT         10000   // WiFi 连接超时 (ms)
```
