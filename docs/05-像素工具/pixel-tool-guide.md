# 像素工具使用指南

本文档详细介绍桌面宠物项目中像素工具（Pixel Tool）的安装、使用和内部实现原理。该工具负责将图片和 GIF 动画转换为 ESP32 可识别的 `.pxl` 二进制像素格式，并通过 WiFi 推送到设备屏幕显示。

---

## 一、安装与依赖

### 1.1 环境要求

- Python 3.8 或更高版本
- 操作系统：Windows / macOS / Linux

### 1.2 安装依赖

进入 `pixel_tool/` 目录，执行以下命令安装所需依赖：

```bash
cd pixel_tool
pip install -r requirements.txt
```

核心依赖说明：

| 依赖库 | 版本要求 | 用途 |
|--------|----------|------|
| Pillow | >= 9.0 | 图片读取、缩放、格式转换 |
| numpy | >= 1.20 | RGB888 到 RGB565 的向量化批量转换 |

> **提示**：numpy 用于加速像素格式转换，相比纯 Python 循环可提升 10-50 倍性能。

### 1.3 目录结构

```
pixel_tool/
├── pixel_tool.py      # CLI 主入口（子命令分发）
├── pxl_encoder.py     # PXL 编码器（图片→pxl、RLE、Delta）
├── pxl_sender.py      # PXL 发送器（TCP 分块传输到 ESP32）
├── requirements.txt   # Python 依赖清单
├── README.md          # 快速说明文档
└── examples/          # 示例文件
    ├── heart.png / heart.pxl
    ├── smile.png / smile.pxl
    └── rainbow.png / rainbow.pxl
```

---

## 二、CLI 子命令详解

像素工具通过 `python pixel_tool.py <子命令>` 的方式调用，共有四个子命令：`convert`、`send`、`info`、`cmd`。

### 2.1 convert -- 图片转 PXL

将静态图片（PNG/JPG/BMP/WebP）或 GIF 动画转换为 `.pxl` 二进制文件。

**基本语法**：

```bash
python pixel_tool.py convert <输入文件> [选项]
```

**参数说明**：

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `input` | -- | (必填) | 输入图片或 GIF 的文件路径 |
| `-o, --output` | -- | 同名 .pxl | 输出 `.pxl` 文件路径 |
| `-W, --width` | -- | 32 | 目标宽度（像素） |
| `-H, --height` | -- | 32 | 目标高度（像素） |
| `-i, --interval` | -- | 200 | 帧间隔（毫秒） |
| `--max-frames` | -- | 16 | GIF 最大提取帧数 |
| `--no-loop` | -- | (循环) | 禁用循环播放 |
| `--sprite` | -- | (关闭) | 启用雪碧图模式（水平排列的帧序列） |

**使用示例**：

```bash
# 转换静态图片（默认 32x32，输出 heart.pxl）
python pixel_tool.py convert heart.png

# 转换 GIF 动画，指定输出路径
python pixel_tool.py convert dance.gif -o dance.pxl

# 转换 GIF，限制最大 8 帧，帧间隔 150ms
python pixel_tool.py convert cat.gif --max-frames 8 -i 150 -o cat.pxl

# 雪碧图模式：将水平排列的帧序列拆分为多帧动画
python pixel_tool.py convert spritesheet.png --sprite -o walk.pxl

# 自定义尺寸（非 32x32）
python pixel_tool.py convert icon.png -W 16 -H 16 -o icon.pxl

# 静态图，不循环
python pixel_tool.py convert logo.png --no-loop -o logo.pxl
```

**格式支持**：

- 静态图片：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.webp`
- 动画：`.gif`（自动提取帧序列）
- 雪碧图：任意图片格式 + `--sprite` 标志

**转换流程**：

1. 读取源文件，使用 Pillow 打开
2. 按目标尺寸缩放（LANCZOS 高质量算法）
3. 转换为 RGB888 像素格式
4. 通过 numpy 向量化转换为 RGB565（16bit）
5. 多帧动画自动启用 Delta 差分编码
6. 写入 PXL 文件头 + 像素数据

**进度显示**：转换多帧动画时会显示进度条：

```
[████████████░░░░░░░░░░░░░░░░░░] 40% (8/20帧)
```

### 2.2 send -- 发送到设备

将 `.pxl` 文件通过 TCP 推送到 ESP32 桌面宠物设备。

**基本语法**：

```bash
python pixel_tool.py send <pxl文件> <ESP32地址> [选项]
```

**参数说明**：

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `file` | -- | (必填) | `.pxl` 文件路径 |
| `host` | -- | (必填) | ESP32 设备的 IP 地址 |
| `-p, --port` | -- | 19876 | TCP 端口号 |
| `-t, --timeout` | -- | 10.0 | 连接超时（秒） |
| `--no-switch` | -- | (自动切换) | 发送后不自动切换到像素模式 |

**使用示例**：

```bash
# 发送到设备（自动切换到像素模式播放）
python pixel_tool.py send heart.pxl 192.168.1.100

# 指定端口
python pixel_tool.py send dance.pxl 192.168.1.100 -p 19876

# 设置较长超时（适合大文件）
python pixel_tool.py send big_animation.pxl 192.168.1.100 -t 30

# 仅发送数据，不自动切换模式
python pixel_tool.py send heart.pxl 192.168.1.100 --no-switch
```

**发送流程**：

1. 解析 `.pxl` 文件头部信息
2. 将像素数据按 1024 字节分块
3. 每块编码为 Base64 字符串
4. 封装为 JSON 消息，通过 TCP 逐包发送
5. 包间延迟 50ms，防止 ESP32 缓冲区溢出
6. 发送完成后自动发送 `play` 命令切换到像素模式

**输出示例**：

```
[PACK] 准备发送: heart.pxl
   尺寸: 32x32
   帧数: 1, 间隔: 200ms
   总数据: 2048 bytes, 分 2 包
[CONN] 连接 192.168.1.100:19876...
   [SEND] 包 1/2 (50%)
   [SEND] 包 2/2 (100%)
   [CMD] 已发送切换到像素模式命令
[OK] 发送完成!
```

### 2.3 info -- 查看 PXL 文件信息

读取并解析 `.pxl` 文件的头部信息，显示格式详情。

**基本语法**：

```bash
python pixel_tool.py info <pxl文件>
```

**使用示例**：

```bash
python pixel_tool.py info heart.pxl
```

**输出示例**：

```
[INFO] PXL 文件信息: heart.pxl
   格式版本: 1
   尺寸:     32x32
   帧数:     1 (静态)
   帧间隔:   200ms
   循环播放: 是
   压缩模式: 无（原始RGB565）
   原始像素: 2048 bytes
   文件大小: 2064 bytes
   [OK] 文件格式正确
```

**动画文件输出示例**：

```
[INFO] PXL 文件信息: dance.pxl
   格式版本: 1
   尺寸:     32x32
   帧数:     12 (动画)
   帧间隔:   100ms
   循环播放: 是
   压缩模式: Delta差分帧
   原始像素: 24576 bytes
   文件大小: 8234 bytes
   压缩率:   33.5% (8234/24576)
```

### 2.4 cmd -- 发送控制命令

向 ESP32 设备发送播放控制命令，无需发送文件即可远程操控。

**基本语法**：

```bash
python pixel_tool.py cmd <命令> <ESP32地址> [选项]
```

**可用命令**：

| 命令 | 说明 |
|------|------|
| `play` | 播放已加载的像素动画 |
| `pause` | 暂停当前播放 |
| `stop` | 停止播放，返回正常表情模式 |
| `switch_mode` | 切换显示模式（需配合 `-m` 参数） |

**参数说明**：

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `command` | -- | (必填) | 控制命令 |
| `host` | -- | (必填) | ESP32 设备 IP 地址 |
| `-p, --port` | -- | 19876 | TCP 端口号 |
| `-m, --mode` | -- | -- | 目标模式（仅 `switch_mode` 时需要）：`normal` 或 `pixel` |

**使用示例**：

```bash
# 播放已加载的像素动画
python pixel_tool.py cmd play 192.168.1.100

# 暂停播放
python pixel_tool.py cmd pause 192.168.1.100

# 停止并返回正常模式
python pixel_tool.py cmd stop 192.168.1.100

# 切换到像素模式
python pixel_tool.py cmd switch_mode 192.168.1.100 -m pixel

# 切换回正常模式
python pixel_tool.py cmd switch_mode 192.168.1.100 -m normal
```

---

## 三、编码器实现

### 3.1 颜色格式转换：RGB888 -> RGB565

ESP32 屏幕使用 RGB565（16bit）颜色格式。转换公式如下：

```
RGB565 = (R >> 3) << 11 | (G >> 2) << 5 | (B >> 3)
```

其中 R 取高 5 位、G 取高 6 位、B 取高 5 位，共 16bit。

实现中使用 numpy 向量化操作批量处理整张图片，避免逐像素 Python 循环，性能提升显著：

```python
def image_to_rgb565_data(img: Image.Image) -> bytes:
    arr = np.array(img.convert('RGB'), dtype=np.uint8)
    r = arr[:, :, 0].astype(np.uint16)
    g = arr[:, :, 1].astype(np.uint16)
    b = arr[:, :, 2].astype(np.uint16)
    rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return rgb565.astype(np.uint16).tobytes()
```

### 3.2 RLE 压缩（帧内压缩）

RLE（Run-Length Encoding）压缩适用于大面积纯色的静态图片。

**编码格式**：

- `bit7 = 1`（Run 模式）：`flag_byte = 0x80 | count`，后跟 2 字节重复像素值（big-endian）。count 范围 1-127，当连续 3 个以上相同像素时使用。
- `bit7 = 0`（Literal 模式）：`flag_byte = count`，后跟 `count * 2` 字节原始像素数据。用于无重复的像素序列。

**压缩参数**：

| 参数 | 值 | 说明 |
|------|-----|------|
| `RLE_MAX_COUNT` | 127 | 单次 run/literal 最大长度 |
| `RLE_MIN_RUN` | 3 | 最小 run 长度（短于此用 literal） |

**编码流程**：

1. 扫描像素流，检测连续重复像素
2. 若重复长度 >= 3，写入 run 编码
3. 否则收集为 literal 序列写入
4. literal 中若检测到后续 3+ 重复，提前结束 literal 并切换为 run

### 3.3 Delta 差分帧压缩（帧间压缩）

Delta 编码用于动画的后续帧，仅记录与前一帧的差异，通常可降低 60-90% 的数据量。

**三种操作码**：

| 操作码 | 值 | 格式 | 说明 |
|--------|-----|------|------|
| `COPY` | 0x00 | `[0x00][count]` | 像素未变化，跳过 count 个像素 |
| `REPEAT` | 0x01 | `[0x01][count][pixel_lo][pixel_hi]` | count 个连续变化像素，值相同 |
| `LITERAL` | N (2-127) | `[N][px0_lo][px0_hi]...[pxN-1_lo][pxN-1_hi]` | N 个变化像素，值各不同 |

**编码流程**：

1. 逐像素对比前一帧和当前帧
2. 未变化像素归为 COPY run
3. 变化像素中，连续相同值归为 REPEAT
4. 其余不同值归为 LITERAL
5. 单个变化像素使用 REPEAT(run=1) 编码（与 ESP32 解码协议匹配）

**解码流程**（`DeltaCompressor.decode`）：

1. 初始化结果为前一帧的副本
2. 按操作码逐段更新：
   - COPY：跳过（结果中已从前帧复制）
   - REPEAT：将新像素值写入连续位置
   - LITERAL：依次写入各像素的新值

### 3.4 PXL 文件格式

**文件头**（16 字节）：

| 偏移 | 长度 | 字段 | 说明 |
|------|------|------|------|
| 0 | 3 | magic | 魔数 `PXL`（0x50 0x58 0x4C） |
| 3 | 1 | version | 格式版本号（当前为 1） |
| 4 | 2 | width | 图像宽度（小端序） |
| 6 | 2 | height | 图像高度（小端序） |
| 8 | 2 | frame_count | 帧数（小端序） |
| 10 | 2 | frame_interval | 帧间隔毫秒（小端序） |
| 12 | 2 | flags | 标志位（小端序） |
| 14 | 2 | reserved | 保留字段 |

**flags 标志位**：

| 位 | 值 | 说明 |
|----|-----|------|
| bit0 | 0x0001 | 循环播放 |
| bit1 | 0x0002 | RLE 压缩 |
| bit2 | 0x0004 | Delta 差分帧编码（与 RLE 互斥） |

**像素数据**：

- 第一帧始终为完整的 RGB565 数据（每像素 2 字节）
- 后续帧使用 Delta 编码时为差分数据
- 单帧大小：`width * height * 2` 字节（未压缩时）

---

## 四、解码器实现

PXL 文件的解码通过 `DeltaCompressor.decode()` 方法实现，该方法用于从差分帧还原完整帧。

### 4.1 解码流程

```
输入: 前一帧 (prev_rgb565) + 差分数据 (delta_data)
输出: 当前帧 (curr_rgb565)

1. 初始化结果缓冲区 = 前一帧的副本
2. 遍历 delta_data 中的操作码:
   - COPY(0x00): 读取 count, 像素位置前进 count (结果中已是前帧值,无需修改)
   - REPEAT(0x01): 读取 count + 2字节像素值, 写入 count 次
   - LITERAL(N): 读取 N 组像素值, 依次写入
3. 返回还原后的完整帧数据
```

### 4.2 首帧处理

首帧不使用差分编码，直接存储完整的 RGB565 数据。解码时无需额外处理，直接读取即可。

### 4.3 多帧解码顺序

```
帧0: 直接读取完整 RGB565 数据
帧1: decode(帧0, delta_data_1) → 完整帧1
帧2: decode(帧1, delta_data_2) → 完整帧2
...
帧N: decode(帧N-1, delta_data_N) → 完整帧N
```

每帧解码依赖前一帧的结果，因此必须按顺序解码。

---

## 五、发送协议

### 5.1 传输方式

使用 TCP 长连接，将 PXL 像素数据分块后以 JSON 格式发送到 ESP32。

### 5.2 分块参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `CHUNK_PIXEL_BYTES` | 1024 | 每块像素数据字节数 |
| `CHUNK_SEND_DELAY` | 50ms | 包间延迟 |
| `SEND_TIMEOUT` | 10s | 发送超时 |
| `CMD_TIMEOUT` | 5s | 命令超时 |

### 5.3 消息格式

**数据包**（`type: pixel_data`）：

```json
{
  "type": "pixel_data",
  "data": {
    "format": "pxl_chunk",
    "width": 32,
    "height": 32,
    "frame_count": 1,
    "frame_interval": 200,
    "flags": 1,
    "packet_index": 0,
    "total_packets": 2,
    "offset": 0,
    "total_size": 2048,
    "chunk_base64": "AAD/...=="
  },
  "ts": 1719200000
}
```

**控制命令**（`type: pixel_cmd`）：

```json
{
  "type": "pixel_cmd",
  "data": {
    "command": "play",
    "mode": "pixel"
  },
  "ts": 1719200000
}
```

### 5.4 发送流程

```
PC (pixel_tool)                    ESP32
     |                                |
     |--- TCP 连接 (port 19876) ----->|
     |                                |
     |--- pixel_data chunk 0 -------->|
     |<--------- ACK -----------------|
     |--- pixel_data chunk 1 -------->|
     |<--------- ACK -----------------|
     |           ...                  |
     |--- pixel_data chunk N -------->|
     |                                |
     |--- pixel_cmd (play, pixel) --->|  (自动切换模式)
     |                                |
     |--- TCP 断开 ------------------>|
```

### 5.5 编程接口

除了 CLI 方式，也可以在 Python 代码中直接调用：

```python
from pxl_encoder import image_to_pxl, gif_to_pxl, png_to_pxl_frames
from pxl_sender import send_pxl_to_esp32, send_pixel_command

# 图片转 PXL
image_to_pxl("heart.png", "heart.pxl", size=(32, 32), interval=200)

# GIF 转 PXL（最大 16 帧）
gif_to_pxl("dance.gif", "dance.pxl", max_frames=16, loop=True)

# 雪碧图转 PXL
png_to_pxl_frames("spritesheet.png", "walk.pxl", interval=150)

# 发送到 ESP32
send_pxl_to_esp32("heart.pxl", "192.168.1.100", port=19876)

# 发送控制命令
send_pixel_command("192.168.1.100", 19876, "play")
send_pixel_command("192.168.1.100", 19876, "stop")
send_pixel_command("192.168.1.100", 19876, "switch_mode", mode="pixel")
```

---

## 六、常见问题

### Q: 发送时提示"连接被拒绝"？

确认 ESP32 已开机并连接到同一局域网，且 IP 地址正确。可通过串口监视器查看 ESP32 的 IP。

### Q: 转换后的 PXL 文件很大？

对于动画 GIF，建议使用 `--max-frames` 限制帧数。Delta 编码会自动压缩后续帧，通常可减少 60-90% 的数据量。可通过 `info` 子命令查看压缩率。

### Q: 画面颜色失真？

RGB565 格式的颜色精度低于 RGB888（R/B 各 5 位、G 6 位），在渐变色区域可能出现色带。这是 16bit 色深的固有限制。

### Q: 如何确认设备支持的分辨率？

默认分辨率 32x32，与 ESP32 桌面宠物的屏幕尺寸匹配。使用其他分辨率前请确认硬件支持。
