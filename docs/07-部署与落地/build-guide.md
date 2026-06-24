# 固件编译指南

> **适用对象**：需要编译、烧录、调试 ESP32-S3 固件的开发者
>
> **前置条件**：已完成 [quick-start.md](./quick-start.md) 中的环境准备

---

## 一、开发环境安装

### 1.1 VS Code + PlatformIO IDE

1. 下载安装 [VS Code](https://code.visualstudio.com/)
2. 打开 VS Code，按 `Ctrl+Shift+X` 进入扩展商店
3. 搜索 `PlatformIO IDE`，点击安装
4. 等待 PlatformIO 核心自动下载安装（首次约 5 ~ 10 分钟）
5. 安装完成后重启 VS Code

### 1.2 Python 环境

PlatformIO 依赖 Python，确保系统已安装 Python 3.9+：

```bash
python --version
# Python 3.11.x
```

如果使用命令行方式编译，需单独安装 PlatformIO CLI：

```bash
pip install platformio
```

### 1.3 验证安装

```bash
pio --version
# 应输出 PlatformIO Core 版本号
```

---

## 二、platformio.ini 关键配置

项目的固件配置文件位于 `esp32_firmware/platformio.ini`，以下是每个关键字段的详细说明。

### 2.1 完整配置

```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino

lib_deps =
    lovyan03/LovyanGFX@^1.1.8
    bblanchon/ArduinoJson@^6.21.0
    ESPmDNS
    h2zero/NimBLE-Arduino@^1.4.0

monitor_speed = 115200
upload_speed = 921600

board_build.partitions = huge_app.csv
board_build.filesystem = littlefs
board_build.arduino.memory_type = qio_opi

build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -std=c++17
```

### 2.2 字段详解

#### 基础配置

| 字段 | 值 | 说明 |
|------|-----|------|
| `[env:esp32s3]` | 环境名 | PlatformIO 构建环境名称，可自定义 |
| `platform` | `espressif32` | ESP32 系列芯片的开发平台，PlatformIO 会自动下载对应的工具链 |
| `board` | `esp32-s3-devkitc-1` | 开发板型号，决定芯片型号、Flash 大小、引脚映射等预设 |
| `framework` | `arduino` | 使用 Arduino 框架（也可选 ESP-IDF，但本项目基于 Arduino） |

#### 库依赖 (`lib_deps`)

| 库名 | 版本 | 用途 |
|------|------|------|
| `lovyan03/LovyanGFX` | ^1.1.8 | LCD 显示驱动，支持 ST7789V，提供高性能绘图 API |
| `bblanchon/ArduinoJson` | ^6.21.0 | JSON 解析库，用于解析 PC 端发来的消息 |
| `ESPmDNS` | 内置 | mDNS 服务发现，ESP32 可通过 `deskpet.local` 域名找到 PC |
| `h2zero/NimBLE-Arduino` | ^1.4.0 | BLE 蓝牙库，用于 BLE 配网功能 |

> PlatformIO 会在首次编译时自动下载 `lib_deps` 中声明的库，无需手动安装。

#### 串口与烧录

| 字段 | 值 | 说明 |
|------|-----|------|
| `monitor_speed` | `115200` | 串口监视器波特率，与固件中 `Serial.begin()` 一致 |
| `upload_speed` | `921600` | 烧录波特率，越高烧录越快；如果烧录失败可降低到 `460800` |

#### 分区表与文件系统

| 字段 | 值 | 说明 |
|------|-----|------|
| `board_build.partitions` | `huge_app.csv` | 使用大 APP 分区表，详见[第五节](#五分区表选择) |
| `board_build.filesystem` | `littlefs` | 文件系统类型，用于存储图片资源等 |

#### PSRAM 配置

| 字段 | 值 | 说明 |
|------|-----|------|
| `board_build.arduino.memory_type` | `qio_opi` | PSRAM 模式：QIO（Quad I/O）+ OPI（Octal SPI），适用于 8MB PSRAM 模块 |

> 如果使用 4MB PSRAM 版本的模块，需改为 `qio_qio`。但强烈建议使用 8MB 版本，4MB 会导致动画帧缓存 OOM。

#### 构建标志 (`build_flags`)

| 标志 | 说明 |
|------|------|
| `-DBOARD_HAS_PSRAM` | 告知编译器板载有 PSRAM，启用 PSRAM 分配函数 |
| `-DARDUINO_USB_MODE=1` | 启用 USB CDC 模式（USB 串口） |
| `-DARDUINO_USB_CDC_ON_BOOT=1` | 开机时自动启用 USB 串口输出 |
| `-std=c++17` | 使用 C++17 标准编译，支持 `std::optional`、结构化绑定等特性 |

---

## 三、编译命令

### 3.1 编译固件

```bash
cd esp32_firmware
pio run
```

此命令仅编译，不烧录。编译产物位于 `.pio/build/esp32s3/firmware.elf`。

### 3.2 烧录固件

```bash
pio run -t upload
```

此命令编译并烧录到 ESP32-S3。烧录通过 USB CDC 自动进行，无需手动进入下载模式（除非烧录失败）。

### 3.3 串口监视

```bash
pio device monitor
```

打开串口监视器，波特率默认 115200。按 `Ctrl+C` 退出。

也可以在 VS Code 底部工具栏点击插头图标（Serial Monitor）打开。

### 3.4 烧录文件系统

```bash
pio run -t uploadfs
```

此命令将 `data/` 目录下的文件（如图片资源）烧录到 ESP32 的 LittleFS 文件系统分区中。

> **注意**：烧录文件系统和烧录固件是独立的操作。首次部署时两者都需要执行。

### 3.5 清理编译产物

```bash
pio run -t clean
```

清除 `.pio/build/` 目录下的编译缓存，下次编译将从头开始。

### 3.6 命令速查表

| 命令 | 作用 | VS Code 对应操作 |
|------|------|------------------|
| `pio run` | 编译固件 | 底部工具栏 Build（勾号图标） |
| `pio run -t upload` | 编译并烧录 | 底部工具栏 Upload（箭头图标） |
| `pio device monitor` | 串口监视 | 底部工具栏 Serial Monitor（插头图标） |
| `pio run -t uploadfs` | 烧录文件系统 | 无对应，需命令行执行 |
| `pio run -t clean` | 清理编译缓存 | PlatformIO 侧边栏 Clean |

---

## 四、编译错误排查

### 4.1 库相关错误

#### `Library not found` / `Could not find the library`

**原因**：`lib_deps` 中的库未正确下载。

**解决方案**：

```bash
# 清理并重新编译
pio run -t clean
pio run
```

如果仍然失败，手动删除库缓存后重试：

```bash
# 删除 PlatformIO 库缓存
rm -rf ~/.platformio/lib
# 或 Windows
rmdir /s /q %USERPROFILE%\.platformio\lib

pio run
```

#### `Multiple versions of library found`

**原因**：本地存在多个版本的同名库。

**解决方案**：检查 `~/.platformio/lib/` 目录，删除重复的库文件夹，只保留 `lib_deps` 中指定的版本。

### 4.2 PSRAM 相关错误

#### `PSRAM init failed` / `PSRAM not found`

**原因**：开发板没有 PSRAM，或 PSRAM 模式配置不正确。

**解决方案**：

1. 确认开发板型号为 **8MB PSRAM** 版本（购买时注意区分）
2. 检查 `platformio.ini` 中 `board_build.arduino.memory_type` 配置：
   - 8MB PSRAM（OPI 模式）：`qio_opi`（推荐）
   - 8MB PSRAM（QPI 模式）：`qio_qpi`
   - 4MB PSRAM：`qio_qio`
3. 检查 `build_flags` 中是否包含 `-DBOARD_HAS_PSRAM`

#### `heap_caps_malloc failed` / OOM 崩溃

**原因**：PSRAM 未启用或容量不足。

**解决方案**：

1. 确认 PSRAM 初始化成功（串口日志中应有 `PSRAM: 8388608 bytes`）
2. 检查动画帧大小是否超过 16KB 限制
3. 使用 `ESP.getFreeHeap()` 和 `ESP.getFreePsram()` 监控内存使用

### 4.3 分区相关错误

#### `Sketch is too large` / `partition table mismatch`

**原因**：固件体积超过了默认分区表的 APP 分区大小。

**解决方案**：确认 `board_build.partitions = huge_app.csv` 已设置。详见[第五节](#五分区表选择)。

#### `Filesystem image too large`

**原因**：`data/` 目录中的资源文件超过了 LittleFS 分区大小。

**解决方案**：

1. 检查 `data/` 目录总大小
2. 使用 `huge_app.csv` 分区表可获得更大的 APP 分区，但文件系统分区会较小
3. 压缩或减少 `data/` 目录中的资源文件

### 4.4 USB / 串口错误

#### `Could not open port` / `Permission denied`

**原因**：串口被其他程序占用（如串口监视器、另一个 PlatformIO 实例）。

**解决方案**：关闭所有占用串口的程序，然后重试。

#### `Failed to connect to ESP32`

**原因**：ESP32 未处于下载模式。

**解决方案**：

1. 按住开发板上的 **BOOT** 按键
2. 同时按一下 **RST** 按键
3. 松开 **BOOT** 按键
4. 此时 ESP32 进入下载模式，重新执行 `pio run -t upload`

### 4.5 编译器错误

#### `fatal error: xxx.h: No such file or directory`

**原因**：头文件路径不正确或库未正确安装。

**解决方案**：

1. 检查 `#include` 路径是否正确
2. 确认 `lib_deps` 中包含所需库
3. 执行 `pio run -t clean` 后重新编译

#### `undefined reference to 'xxx'`

**原因**：链接错误，函数声明存在但实现缺失。

**解决方案**：

1. 检查是否遗漏了源文件（`.cpp` 文件未加入编译）
2. 检查函数签名是否与声明一致
3. 确认 `build_flags` 中的宏定义正确

---

## 五、分区表选择

### 5.1 ESP32-S3 默认分区表

ESP32-S3 默认使用 `default.csv` 分区表，其布局大致为：

```
Name,   Type, SubType, Offset,  Size
nvs,    data, nvs,     0x9000,  0x5000  (20KB)
otadata,data, ota,     0xe000,  0x2000  (8KB)
app0,   app,  ota_0,   0x10000, 0x140000 (1280KB)
app1,   app,  ota_1,   0x150000,0x140000 (1280KB)
spiffs, data, spiffs,  0x290000,0x170000 (1472KB)
```

APP 分区只有约 1.25MB，对于本项目的固件（含 LovyanGFX 库）来说不够用。

### 5.2 huge_app.csv 分区表

本项目使用 `huge_app.csv` 分区表，其布局为：

```
Name,   Type, SubType, Offset,  Size
nvs,    data, nvs,     0x9000,  0x5000  (20KB)
otadata,data, ota,     0xe000,  0x2000  (8KB)
app0,   app,  ota_0,   0x10000, 0x300000 (3072KB / 3MB)
littlefs,data, spiffs,  0x310000,0xF0000 (960KB)
```

APP 分区扩大到 3MB，足以容纳本项目的完整固件。

### 5.3 为什么需要 huge_app

| 因素 | 说明 |
|------|------|
| LovyanGFX 库 | 该库功能丰富但体积较大，编译后约占 800KB ~ 1MB |
| ArduinoJson | JSON 解析库，约占 100KB |
| NimBLE-Arduino | BLE 协议栈，约占 200KB |
| 应用代码 | 本项目业务代码约占 500KB |
| **合计** | 约 1.6MB ~ 2MB，超过 default 分区的 1.25MB 限制 |

### 5.4 OTA 更新说明

`huge_app.csv` 只有一个 APP 分区（`app0`），不支持 A/B 分区 OTA。如需 OTA 功能，需自定义分区表，为两个 APP 分区各分配至少 1.5MB。

当前项目通过 Web 配置页面的 OTA 端点（`http://<esp32-ip>/update`）实现固件升级，使用单分区覆盖写入方式。

---

## 六、Release 与 Debug 配置

### 6.1 日志级别控制

固件中的日志通过 `DEBUG_SERIAL` 宏控制。在 `config.h` 中：

```cpp
#define DEBUG_SERIAL 1   // 1 = 启用串口日志（Debug 模式）
                         // 0 = 关闭串口日志（Release 模式）
```

### 6.2 Debug 配置（开发阶段）

```cpp
#define DEBUG_SERIAL 1
```

- 输出详细的运行日志到串口
- 包括 WiFi 连接状态、TCP 收发数据、内存使用情况等
- 便于调试和排查问题
- 会略微影响性能（串口输出有开销）

### 6.3 Release 配置（部署阶段）

```cpp
#define DEBUG_SERIAL 0
```

- 关闭所有串口日志输出
- 减少 CPU 开销，提升运行效率
- 适合长时间稳定运行的部署环境
- 如需排查问题，临时改为 1 即可

### 6.4 PlatformIO 构建环境分离

可以在 `platformio.ini` 中定义多个环境，方便切换：

```ini
; Debug 环境
[env:esp32s3_debug]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DDEBUG_SERIAL=1
    -std=c++17

; Release 环境
[env:esp32s3_release]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DDEBUG_SERIAL=0
    -std=c++17
```

编译时指定环境：

```bash
pio run -e esp32s3_debug    # Debug 版本
pio run -e esp32s3_release  # Release 版本
```

---

## 七、板型选择

### 7.1 推荐板型：ESP32-S3-DevKitC-1

本项目默认使用的板型是 `esp32-s3-devkitc-1`，对应微雪 ESP32-S3 1.54" LCD 开发板。

**选型理由**：

| 特性 | 说明 |
|------|------|
| 集成 LCD | 板载 1.54" 240x240 IPS LCD（ST7789V），无需额外接线 |
| 8MB PSRAM | 动画帧缓存需要大量内存，4MB 不够用 |
| 8MB Flash | 足够存放固件 + 文件系统资源 |
| USB-C | 直接通过 USB 烧录和供电，无需外部烧录器 |
| 价格 | 约 50 ~ 80 元，性价比高 |

### 7.2 其他兼容板型

如果无法购买微雪开发板，以下板型也可使用（需修改引脚配置）：

| 板型 | PSRAM | LCD | 需要修改 |
|------|-------|-----|----------|
| ESP32-S3-DevKitC-1（乐鑫官方） | 需选 8MB 版 | 无板载 LCD | 需外接 LCD，修改 `config.h` 引脚定义 |
| ESP32-S3-WROOM-1 模组 | 8MB 版可选 | 无板载 LCD | 需自行设计 PCB 或使用转接板 |
| 其他 ESP32-S3 开发板 | 确认有 8MB PSRAM | 看具体型号 | 需根据实际引脚修改 `config.h` |

### 7.3 更换板型的修改步骤

1. **修改 `platformio.ini`** 中的 `board` 字段：

```ini
board = 你的板型名称
```

可在 [PlatformIO 板型列表](https://docs.platformio.org/en/latest/boards/index.html) 中查找支持的板型。

2. **修改 `config.h`** 中的引脚定义：

```cpp
// LCD 引脚 - 根据实际接线修改
#define LCD_CS    你的CS引脚
#define LCD_RST   你的RST引脚
#define LCD_DC    你的DC引脚
#define LCD_MOSI  你的MOSI引脚
#define LCD_SCLK  你的SCLK引脚
#define LCD_BL    你的背光引脚

// I2C 引脚 - 如果接了 BH1750 / DRV2605L
#define BH1750_SDA_PIN  你的SDA引脚
#define BH1750_SCL_PIN  你的SCL引脚
```

3. **确认 PSRAM 配置**：

如果新板子的 PSRAM 模式不同，修改 `platformio.ini`：

```ini
board_build.arduino.memory_type = 适合你板子的模式
```

常见模式：
- `qio_opi`：QIO Flash + OPI PSRAM（8MB OPI 模式，推荐）
- `qio_qpi`：QIO Flash + QPI PSRAM
- `qio_qio`：QIO Flash + QIO PSRAM（4MB PSRAM）

4. **重新编译测试**：

```bash
pio run -t clean
pio run
pio run -t upload
```

### 7.4 不支持的板型

| 板型 | 不兼容原因 |
|------|------------|
| ESP32（非 S3） | 无 PSRAM 或 PSRAM 不同，USB CDC 不支持 |
| ESP32-C3 | 单核 RISC-V，性能不足，无 PSRAM |
| ESP32-S2 | 无 BLE，PSRAM 配置不同 |
| 4MB Flash 版本 | 空间不足以存放固件 + 文件系统 |

---

## 附录 A：常用 PlatformIO 命令

```bash
# 查看所有编译环境
pio project config

# 查看编译日志（详细模式）
pio run -v

# 只编译指定环境
pio run -e esp32s3

# 查看已连接的设备
pio device list

# 监视指定串口
pio device monitor --port COM3

# 更新 PlatformIO 核心
pio upgrade

# 更新所有库依赖
pio lib update
```

## 附录 B：编译产物说明

编译成功后，产物位于 `.pio/build/esp32s3/` 目录：

| 文件 | 说明 |
|------|------|
| `firmware.elf` | ELF 格式的完整固件（含调试信息） |
| `firmware.bin` | 纯二进制固件，用于 OTA 升级或手动烧录 |
| `bootloader.bin` | 引导程序 |
| `partitions.bin` | 分区表二进制 |
| `littlefs.bin` | 文件系统镜像（如有） |

手动烧录（使用 esptool）：

```bash
esptool.py --chip esp32s3 --port COM3 --baud 921600 \
  write_flash 0x0 bootloader.bin \
  0x8000 partitions.bin \
  0x10000 firmware.bin
```

---

> **文档版本**: v1.0
> **最后更新**: 2026-06-24
