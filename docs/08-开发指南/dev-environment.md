# 开发环境搭建

本文档指导开发者从零搭建桌面电子宠物项目的完整开发环境，涵盖 ESP32 固件、Python PC 端和像素工具三个子系统。

---

## 一、ESP32 固件开发

### 1.1 硬件要求

| 项目 | 规格 |
|------|------|
| 开发板 | 微雪 ESP32-S3 1.54inch LCD (240x240, ST7789V) |
| USB 接口 | Type-C（用于烧录和串口调试） |
| 传感器（可选） | BH1750 环境光传感器、DRV2605L 触觉反馈驱动 |

### 1.2 安装 VSCode + PlatformIO

1. 安装 [VSCode](https://code.visualstudio.com/)
2. 在扩展市场搜索并安装 **PlatformIO IDE**
3. 打开项目目录 `esp32_firmware/`，PlatformIO 自动识别 `platformio.ini`

### 1.3 平台与依赖

项目使用 PlatformIO 构建，核心配置如下：

```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino

lib_deps =
    lovyan03/LovyanGFX@^1.1.8      # LCD 显示驱动
    bblanchon/ArduinoJson@^6.21.0   # JSON 解析
    ESPmDNS                         # mDNS 服务发现
    h2zero/NimBLE-Arduino@^1.4.0   # BLE 蓝牙配网

monitor_speed = 115200
upload_speed = 921600
```

PlatformIO 首次编译时会自动下载工具链和库依赖，无需手动操作。

### 1.4 USB 驱动

ESP32-S3 使用内置 USB-JTAG，Windows 10+ 通常免驱。如设备管理器中无法识别：

- 安装 [Zadig](https://zadig.akeo.ie/)，选择 WinUSB 驱动
- 或安装 [CP210x 驱动](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)（部分开发板使用 CP2102N）

### 1.5 编译与烧录

```bash
# 编译固件
pio run

# 烧录到开发板（USB 连接后自动识别端口）
pio run --target upload

# 打开串口监视器（波特率 115200）
pio device monitor
```

### 1.6 分区表与 PSRAM

项目使用 `huge_app.csv` 分区表和 QIO OPI PSRAM 模式：

```ini
board_build.partitions = huge_app.csv
board_build.filesystem = littlefs
board_build.arduino.memory_type = qio_opi
```

构建标志启用 PSRAM 和 USB CDC：

```ini
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -std=c++17
```

---

## 二、Python PC 端开发

### 2.1 环境要求

- **Python**: >= 3.9（推荐 3.11+）
- **操作系统**: Windows 10/11、macOS、Linux

### 2.2 创建虚拟环境

```bash
# 进入项目根目录
cd plan_desktop_pet

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

### 2.3 安装依赖

```bash
# 运行时依赖
pip install -r pc_monitor/requirements.txt

# 开发依赖（测试、lint、类型检查）
pip install -e ".[dev]"
```

运行时依赖列表：

| 包名 | 版本 | 用途 |
|------|------|------|
| psutil | >= 5.9.0 | 进程监控（CPU/内存采样） |
| requests | >= 2.28.0 | HTTP 请求（天气 API） |
| pyserial | >= 3.5 | 串口通信 |

开发依赖：

| 包名 | 版本 | 用途 |
|------|------|------|
| pytest | >= 7.0.0 | 测试框架 |
| ruff | >= 0.1.0 | Linter + Formatter |
| mypy | >= 1.0.0 | 静态类型检查 |

### 2.4 项目配置文件

`pyproject.toml` 定义了工具链配置：

```toml
[tool.ruff]
target-version = "py39"
line-length = 120

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP"]

[tool.mypy]
python_version = "3.9"
check_untyped_defs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

### 2.5 运行 PC 端程序

```bash
# 启动系统托盘监控程序
python pc_monitor/tray_app.py
```

---

## 三、像素工具开发

### 3.1 依赖安装

像素工具需要额外的图像处理库：

```bash
pip install Pillow>=9.0.0 numpy
```

如果已执行 `pip install -e ".[dev]"`，Pillow 已包含在运行时依赖中。

### 3.2 功能概览

像素工具位于 `pixel_tool/` 目录，包含三个核心模块：

| 模块 | 文件 | 功能 |
|------|------|------|
| 编码器 | `pxl_encoder.py` | 图片/GIF 转 .pxl 二进制文件 |
| 解码器 | `pxl_decoder.py` | .pxl 文件解码为图片/GIF |
| 发送器 | `pxl_sender.py` | 通过 TCP 将 .pxl 发送到 ESP32 |

### 3.3 命令行使用

```bash
# 编码：图片转 PXL
python pixel_tool/pxl_encoder.py input.png output.pxl

# 编码：GIF 转 PXL（自动差分帧压缩）
python pixel_tool/pxl_encoder.py input.gif output.pxl

# 解码：PXL 转图片
python pixel_tool/pxl_decoder.py input.pxl output.png

# 解码：PXL 转 GIF
python pixel_tool/pxl_decoder.py input.pxl output.gif

# 发送到 ESP32
python pixel_tool/pxl_sender.py output.pxl 192.168.1.100
```

---

## 四、代码风格与规范

### 4.1 Python 规范

- **格式化**: 使用 `ruff format`，行宽 120 字符
- **Lint**: 使用 `ruff check`，启用 E/W/F/I/N/UP 规则集
- **类型注解**: 公共函数必须添加类型注解，mypy `check_untyped_defs` 已启用
- **导入排序**: isort 规则由 ruff 管理，`modules` 和 `pixel_tool` 视为第一方包

```bash
# 格式化
ruff format pc_monitor/ pixel_tool/ tests/

# Lint 检查
ruff check pc_monitor/ pixel_tool/ tests/

# 类型检查
mypy pc_monitor/
```

### 4.2 C++ 规范（ESP32 固件）

- **标准**: C++17（由 `build_flags` 指定）
- **命名**: 类名 `PascalCase`，方法名 `camelCase`，常量 `UPPER_SNAKE_CASE`
- **头文件**: 使用 `#ifndef` include guard
- **内存管理**: PSRAM 分配使用 `ps_malloc`/`heap_caps_malloc`，需检查返回值

### 4.3 通用原则

- 函数保持简短（建议 < 50 行）
- 文件聚焦（建议 < 800 行）
- 避免深层嵌套（建议 < 4 层），使用提前返回
- 禁止硬编码密钥，使用环境变量或配置文件
- 错误显式处理，不静默吞掉异常

---

## 五、Git 工作流

### 5.1 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 稳定版本，随时可部署 |
| `feat/*` | 功能开发分支 |
| `fix/*` | Bug 修复分支 |
| `docs/*` | 文档更新分支 |

### 5.2 提交信息格式

遵循 Conventional Commits 规范：

```
<type>: <description>

<optional body>
```

类型说明：

| 类型 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变功能） |
| `docs` | 文档更新 |
| `test` | 测试相关 |
| `chore` | 构建/工具链变更 |
| `perf` | 性能优化 |
| `ci` | CI/CD 配置 |

示例：

```
feat(esp32): add night shift color temperature filter

Implement warm color matrix based on NTP time, smooth transition
during 20:00-06:00 window.
```

### 5.3 提交流程

```bash
# 1. 创建功能分支
git checkout -b feat/my-feature

# 2. 开发并提交
git add -A
git commit -m "feat(pc): add token usage trend chart"

# 3. 推送到远程
git push -u origin feat/my-feature

# 4. 在 GitHub 创建 Pull Request
```

---

## 附录：常见问题

### Q: PlatformIO 编译报错找不到 PSRAM

确认 `platformio.ini` 中包含 `-DBOARD_HAS_PSRAM` 构建标志，且开发板硬件确实配备 PSRAM。

### Q: Python 导入模块失败

确保已激活虚拟环境，且执行过 `pip install -e ".[dev]"`。`pyproject.toml` 中配置了 `sys.path` 自动包含 `pc_monitor/` 和 `pixel_tool/`。

### Q: 串口监视器无输出

检查 USB 线是否支持数据传输（非仅充电线），确认 `monitor_speed = 115200` 与固件中 `Serial.begin()` 参数一致。

### Q: Windows 上 pyserial 连接 COM 端口失败

确认设备管理器中端口号正确，关闭其他串口监视器程序（如 Arduino IDE 串口监视器），避免端口占用。
