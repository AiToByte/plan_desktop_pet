# OTA 固件升级机制

> 本文档描述桌面宠物 ESP32 设备的 OTA（Over-The-Air）无线固件升级实现，涵盖原理、Web 界面、固件验证、分区表和失败恢复策略。
> 源码参考: `web_config.cpp` (OTA 部分)

---

## 一、OTA 原理

### 什么是 OTA

OTA（Over-The-Air）是一种通过无线网络远程更新设备固件的技术，无需物理连接 USB 线缆。ESP32-S3 内置硬件支持双 OTA 分区切换，确保升级失败时可回滚到上一版本。

### ESP32 OTA 分区架构

```
┌─────────────────────────────────────────────────┐
│                  ESP32-S3 Flash                  │
├──────────────┬──────────────┬───────────────────┤
│  Factory     │  OTA_0       │  OTA_1            │
│  Partition   │  (当前运行)   │  (OTA目标)         │
├──────────────┼──────────────┼───────────────────┤
│  出厂固件     │  应用固件A    │  应用固件B          │
│  (永不覆盖)   │  ←ota_0→    │  ←ota_1→          │
└──────────────┴──────────────┴───────────────────┘
                           │
                     OTA 标记切换
                           │
                           ▼
              ┌────────────────────────┐
              │  ota_data 分区          │
              │  记录下次启动的目标分区   │
              └────────────────────────┘
```

### 双分区切换机制

1. 设备运行在 `ota_0` 分区
2. OTA 升级将新固件写入 `ota_1` 分区
3. 写入成功后，`esp_ota_set_boot_partition()` 将启动目标切换到 `ota_1`
4. 重启后从 `ota_1` 启动
5. 如果 `ota_1` 运行正常，调用 `esp_ota_mark_app_valid_cancel_rollback()` 确认
6. 如果 `ota_1` 启动失败，硬件自动回滚到 `ota_0`

---

## 二、Web Config OTA 实现

### OTA 路由

```cpp
// web_config.cpp - startAPMode()
_server->on("/ota", HTTP_GET, [this]() { handleOTA(); });           // OTA 页面
_server->on("/update", HTTP_POST, [this]() { handleOTAUpload(); },  // 固件上传
            [this]() { /* multipart handler */ });
_server->on("/rollback", HTTP_POST, [this]() { handleOTARollback(); }); // 手动回滚
```

### OTA 页面功能

OTA 升级页面提供以下功能:

```
┌─────────────────────────────────────┐
│         📦 固件升级                   │
│                                     │
│  选择 .bin 固件文件进行OTA无线升级     │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  📁 点击选择或拖拽固件文件    │    │
│  │  支持 .bin 格式              │    │
│  └─────────────────────────────┘    │
│                                     │
│  文件名: firmware.bin (256.3 KB)    │
│                                     │
│  ████████████████████░░░░░  78%     │
│                                     │
│  [🚀 开始升级]                       │
│  [← 返回配置页]                       │
│                                     │
│  ✅ 固件升级成功！设备即将重启...      │
└─────────────────────────────────────┘
```

### 页面特性

- **拖拽上传**: 支持拖拽 .bin 文件到上传区域
- **文件验证**: 前端检查文件扩展名是否为 `.bin`
- **进度条**: XMLHttpRequest 实时上传进度显示
- **文件信息**: 显示文件名和大小
- **状态反馈**: 成功/失败状态提示

### 固件上传处理

```cpp
// web_config.cpp - handleOTAUpload()
void WebConfig::handleOTAUpload() {
    HTTPUpload& upload = _server->upload();

    if (upload.status == UPLOAD_FILE_START) {
        // 1. 挂起渲染任务，释放 Core 1 的 SPI 总线 + CPU
        extern TaskHandle_t g_renderTaskHandle;
        if (g_renderTaskHandle) {
            vTaskSuspend(g_renderTaskHandle);
        }

        // 2. 记录当前运行分区（用于回滚）
        _otaPrevPartition = esp_ota_get_running_partition();

        // 3. 开始 OTA 更新
        if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
            Update.printError(Serial);
            // 失败时恢复渲染任务
            if (g_renderTaskHandle) {
                vTaskResume(g_renderTaskHandle);
            }
        }
    }
    else if (upload.status == UPLOAD_FILE_WRITE) {
        // 写入固件数据
        if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
            Update.printError(Serial);
        }
    }
    else if (upload.status == UPLOAD_FILE_END) {
        // 恢复渲染任务（无论成功失败都恢复）
        extern TaskHandle_t g_renderTaskHandle;
        if (g_renderTaskHandle) {
            vTaskResume(g_renderTaskHandle);
        }

        if (Update.end(true)) {
            // 标记镜像有效，取消回滚
            esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
        } else {
            // 更新失败，设置回滚到之前的分区
            if (_otaPrevPartition) {
                esp_ota_set_boot_partition(_otaPrevPartition);
            }
        }
    }
}
```

### 关键设计决策

| 决策 | 原因 |
|------|------|
| OTA 时挂起渲染任务 | 释放 Core 1 的 SPI 总线，避免与 Flash 写入冲突 |
| 使用 `UPDATE_SIZE_UNKNOWN` | 固件大小在上传完成前未知 |
| 成功后调用 `mark_app_valid` | 取消回滚标记，确认新固件有效 |
| 失败时调用 `set_boot_partition` | 手动设置回滚分区，确保重启后使用旧固件 |
| 无论成功失败都恢复渲染任务 | 防止渲染任务被永久挂起 |

---

## 三、固件验证与回滚

### 自动验证机制

ESP32 的 OTA 系统内置应用镜像验证:

```
┌─────────────────────────────────────────────────────────┐
│                    OTA 验证流程                           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. Update.begin()                                      │
│     ├── 检查目标分区是否可写                              │
│     └── 初始化 OTA 状态                                  │
│                                                         │
│  2. Update.write()                                      │
│     ├── 逐块写入固件数据                                 │
│     └── 校验每块 CRC                                     │
│                                                         │
│  3. Update.end(true)                                    │
│     ├── 验证完整固件的 SHA-256                            │
│     ├── 检查固件魔数 (Magic Byte)                        │
│     ├── 验证段表完整性                                    │
│     └── 写入 OTA 数据分区                                │
│                                                         │
│  4. esp_ota_mark_app_valid_cancel_rollback()            │
│     └── 确认镜像有效，取消待回滚状态                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 回滚策略

```
┌─────────────────────────────────────────────────────────┐
│                    回滚场景                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  场景1: OTA 写入失败                                     │
│  ├── Update.end() 返回 false                             │
│  ├── 调用 esp_ota_set_boot_partition(旧分区)              │
│  └── 重启后从旧分区启动                                   │
│                                                         │
│  场景2: OTA 写入成功但固件有问题                           │
│  ├── 新固件启动后未调用 mark_app_valid                     │
│  ├── ESP32 硬件自动回滚到旧分区                           │
│  └── 旧分区恢复运行                                       │
│                                                         │
│  场景3: 手动回滚 (Web 接口)                               │
│  ├── POST /rollback                                     │
│  ├── 调用 esp_ota_get_last_invalid_partition()           │
│  ├── 设置启动分区为上一个无效分区                          │
│  └── 重启后从旧分区启动                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 手动回滚接口

```cpp
// web_config.cpp - handleOTARollback()
void WebConfig::handleOTARollback() {
    const esp_partition_t* prev = esp_ota_get_last_invalid_partition();
    if (prev) {
        esp_ota_set_boot_partition(prev);
        _server->send(200, "text/plain", "回滚成功，设备即将重启...");
        delay(1000);
        ESP.restart();
    } else {
        _server->send(400, "text/plain", "没有可回滚的分区");
    }
}
```

---

## 四、分区表说明

### 默认分区表

ESP32-S3 使用以下分区布局:

```
# Name,     Type,  SubType,  Offset,   Size
nvs,        data,  nvs,      0x9000,   0x5000    # NVS 配置存储 (20KB)
otadata,    data,  ota,      0xe000,   0x2000    # OTA 数据分区 (8KB)
ota_0,      app,   ota_0,    0x10000,  0x200000  # 应用分区 0 (2MB)
ota_1,      app,   ota_1,    0x210000, 0x200000  # 应用分区 1 (2MB)
spiffs,     data,  spiffs,   0x410000, 0x1F0000  # SPIFFS 文件系统
```

### 各分区用途

| 分区 | 类型 | 大小 | 用途 |
|------|------|------|------|
| `nvs` | data/nvs | 20KB | 存储 WiFi 配置、服务器地址等键值对 |
| `otadata` | data/ota | 8KB | 记录当前活动的 OTA 分区编号 |
| `ota_0` | app/ota_0 | 2MB | 应用固件分区 A |
| `ota_1` | app/ota_1 | 2MB | 应用固件分区 B |
| `spiffs` | data/spiffs | ~2MB | 像素动画资源、字体等文件 |

### NVS 命名空间

```
pet_config:
  ├── ssid    (String)  WiFi SSID
  ├── pass    (String)  WiFi 密码
  ├── host    (String)  服务器 IP
  ├── port    (Int)     服务器端口
  └── valid   (Bool)    配置有效标志
```

---

## 五、升级流程步骤

### 完整升级流程

```
┌─────────────────────────────────────────────────────────┐
│                    OTA 升级完整流程                        │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 1. 进入配网模式          │
              │    连接设备热点          │
              │    DeskPet-Config       │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 2. 打开浏览器            │
              │    访问 192.168.4.1     │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 3. 点击 "固件升级(OTA)"  │
              │    进入 /ota 页面        │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 4. 选择 .bin 固件文件    │
              │    拖拽或点击选择        │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 5. 点击 "开始升级"       │
              │    等待上传完成          │
              │    进度条显示 0-100%     │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 6. 上传完成              │
              │    设备自动重启          │
              │    页面显示 "升级成功"    │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ 7. 设备重启              │
              │    从新固件分区启动       │
              │    验证新固件有效         │
              │    取消回滚标记          │
              └────────────────────────┘
```

### 编译固件

```bash
# 使用 PlatformIO 编译
cd esp32_firmware
pio run

# 固件文件位置
# .pio/build/esp32s3/firmware.bin
```

### 注意事项

- 固件文件必须是 `.bin` 格式
- 固件大小不能超过 OTA 分区大小 (2MB)
- 升级过程中不要断开电源或关闭浏览器
- 升级完成后设备会自动重启，无需手动操作

---

## 六、失败恢复策略

### 失败场景与对策

| 场景 | 现象 | 恢复方式 |
|------|------|----------|
| 上传中断 | 进度条停止，页面无响应 | 设备超时重启，自动回滚到旧固件 |
| 固件写入错误 | 页面显示 "升级失败，已回滚" | 自动回滚，设备重启后使用旧固件 |
| 固件校验失败 | Update.end() 返回 false | 自动回滚到旧分区 |
| 新固件启动崩溃 | 设备反复重启 | ESP32 硬件自动回滚到旧分区 |
| 电源中断 | 设备意外断电 | 重启后从旧分区启动（OTA 未完成） |
| 浏览器关闭 | 上传未完成 | 设备侧 Update 未 end，重启后旧固件 |

### 恢复流程图

```
OTA 升级失败?
├── 上传阶段失败
│   ├── Update.begin() 失败 → 恢复渲染任务，旧固件继续运行
│   ├── Update.write() 失败 → 标记错误，继续接收后续数据
│   └── 上传中断 → 设备超时重启，OTA 未完成，旧固件启动
│
├── 验证阶段失败
│   ├── Update.end() 返回 false → 调用 set_boot_partition(旧分区)
│   └── SHA-256 校验失败 → 回滚到旧分区
│
├── 启动阶段失败
│   ├── 新固件崩溃 → ESP32 硬件自动回滚
│   ├── 未调用 mark_app_valid → 超时后自动回滚
│   └── 看门狗超时 → 自动重启并回滚
│
└── 手动恢复
    ├── Web 页面 POST /rollback → 手动回滚
    └── 串口烧录 → USB 直接恢复
```

### 代码级保护

```cpp
// 保护1: OTA 时挂起渲染任务
if (g_renderTaskHandle) {
    vTaskSuspend(g_renderTaskHandle);
}

// 保护2: 记录当前分区用于回滚
_otaPrevPartition = esp_ota_get_running_partition();

// 保护3: 失败时手动设置回滚分区
if (!Update.end(true)) {
    if (_otaPrevPartition) {
        esp_ota_set_boot_partition(_otaPrevPartition);
    }
}

// 保护4: 成功后确认镜像有效
esp_ota_mark_app_valid_cancel_rollback();

// 保护5: 无论成功失败都恢复渲染任务
if (g_renderTaskHandle) {
    vTaskResume(g_renderTaskHandle);
}
```

### 最坏情况恢复

如果所有 OTA 恢复机制都失败（极罕见），可通过 USB 串口直接烧录:

```bash
# 使用 esptool 直接烧录
esptool.py --chip esp32s3 --port COM3 --baud 460800 \
    write_flash 0x10000 firmware.bin
```

这将覆盖当前活动分区，设备重启后即可恢复正常。
