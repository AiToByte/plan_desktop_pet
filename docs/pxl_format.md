# PXL 像素文件格式规范 v1.0

## 概述

PXL（PiXeL）是一种紧凑的二进制像素文件格式，专为ESP32桌面宠物设计。
支持单帧图案和多帧动画，使用RGB565色彩空间，直接映射到LCD显示缓冲。

## 文件结构

```
┌─────────────────────────────────────┐
│           文件头 (16 bytes)          │
├─────────────────────────────────────┤
│           帧数据 (N × frame_size)    │
│  ┌─────────────────────────────────┐│
│  │  帧 0: width × height × 2 bytes ││
│  ├─────────────────────────────────┤│
│  │  帧 1: width × height × 2 bytes ││
│  ├─────────────────────────────────┤│
│  │  ...                            ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

## 文件头格式（16字节）

| Offset | Size | Type   | Field          | Description                    |
|--------|------|--------|----------------|--------------------------------|
| 0      | 3    | char   | magic          | 魔数 "PXL" (0x50, 0x58, 0x4C) |
| 3      | 1    | uint8  | version        | 格式版本 (0x01)                |
| 4      | 2    | uint16 | width          | 图像宽度 (little-endian)       |
| 6      | 2    | uint16 | height         | 图像高度 (little-endian)       |
| 8      | 2    | uint16 | frame_count    | 帧数 (1=静态, >1=动画)        |
| 10     | 2    | uint16 | frame_interval | 帧间隔 (毫秒, little-endian)  |
| 12     | 2    | uint16 | flags          | 标志位 (见下表)                |
| 14     | 2    | uint16 | reserved       | 保留字段 (0x0000)              |

### 标志位 (flags)

| Bit | Name    | Description              |
|-----|---------|--------------------------|
| 0   | LOOP    | 循环播放 (1=循环, 0=单次)|
| 1   | RLE     | RLE压缩 (1=压缩, 0=原始)|
| 2-15| -       | 保留                     |

### RLE压缩格式 (flags bit1 = 1)

当 bit1=1 时，帧数据为RLE压缩格式。ESP32解压后等价于原始RGB565数据。

**压缩规则**：对原始RGB565像素流进行游程编码：
```
[原始像素] → [flag_byte][data]
```
- `flag_byte >= 0x80`（bit7=1）：表示run长度 = flag_byte & 0x7F，紧接2字节为重复像素值（big-endian RGB565）
- `flag_byte < 0x80`（bit7=0）：表示literal长度 = flag_byte，紧接 flag_byte × 2 字节为原始像素数据
- run长度范围: 1~127, literal长度范围: 1~127

**解压伪代码**：
```
while output_pos < total_pixels:
    flag = read_byte()
    if flag & 0x80:
        count = flag & 0x7F
        pixel = read_uint16_be()
        repeat count times: output(pixel)
    else:
        count = flag
        copy count * 2 bytes directly
```

**压缩率**：纯色背景可达 ~20:1，像素艺术通常 2:1~5:1。

## 帧数据格式

每帧包含 `width × height` 个像素，每个像素2字节（RGB565格式）。

### 像素排列

```
像素顺序：行优先（Row-Major），从左到右，从上到下

┌─────────────────────┐
│ (0,0) (1,0) ... (W-1,0)   ← 第0行
│ (0,1) (1,1) ... (W-1,1)   ← 第1行
│ ...                        │
│ (0,H-1) ...     (W-1,H-1) │ ← 第H-1行
└─────────────────────┘

文件中的字节顺序：
[frame_data] = pixel(0,0) | pixel(1,0) | ... | pixel(W-1,0) | pixel(0,1) | ...
```

### RGB565 编码

每个像素为16位（2字节），little-endian存储：

```
位布局：RRRRRGGGGGGBBBBB
  - Bit 15-11: Red   (5位, 0-31)
  - Bit 10-5:  Green (6位, 0-63)
  - Bit 4-0:   Blue  (5位, 0-31)

转换公式 (RGB888 → RGB565):
  R5 = R8 >> 3
  G6 = G8 >> 2
  B5 = B8 >> 3
  pixel = (R5 << 11) | (G6 << 5) | B5

转换公式 (RGB565 → RGB888):
  R8 = (pixel >> 11) << 3
  G6 = ((pixel >> 5) & 0x3F) << 2
  B5 = (pixel & 0x1F) << 3
```

## 文件大小计算

```
file_size = 16 + frame_count × width × height × 2

示例：
  32×32, 1帧 (静态图): 16 + 1 × 32 × 32 × 2 = 2,064 bytes
  32×32, 4帧 (动画):   16 + 4 × 32 × 32 × 2 = 8,208 bytes
  32×32, 8帧 (动画):   16 + 8 × 32 × 32 × 2 = 16,400 bytes
  64×64, 4帧 (高清):   16 + 4 × 64 × 64 × 2 = 32,784 bytes
```

## JSON 传输格式

PXL文件通过TCP传输到ESP32时，使用JSON编码。

### 单帧传输（小文件 ≤4KB）

```json
{
  "type": "pixel_data",
  "data": {
    "format": "pxl",
    "width": 32,
    "height": 32,
    "frame_count": 4,
    "frame_interval": 200,
    "flags": 1,
    "pixels_base64": "<base64编码的帧数据>"
  },
  "ts": 1234567890
}
```

### 分包传输（大文件 >4KB）

大文件拆分为多个包，每包含部分帧数据：

```json
{
  "type": "pixel_data",
  "data": {
    "format": "pxl_chunk",
    "width": 32,
    "height": 32,
    "frame_count": 4,
    "frame_interval": 200,
    "flags": 1,
    "packet_index": 0,
    "total_packets": 2,
    "offset": 0,
    "chunk_base64": "<base64编码的分块数据>"
  },
  "ts": 1234567890
}
```

接收端拼包逻辑：
1. 分配 `width × height × frame_count × 2` 字节的缓冲区
2. 按 packet_index 顺序接收，将 chunk_base64 解码后写入 offset 位置
3. 收到所有包后组装完整像素数据

### 控制命令

```json
{
  "type": "pixel_cmd",
  "data": {
    "command": "play|pause|stop|switch_mode",
    "mode": "normal|pixel"
  },
  "ts": 1234567890
}
```

## 使用示例

### Python 创建PXL文件

```python
import struct
from PIL import Image

def image_to_pxl(image_path, output_path, size=(32, 32)):
    img = Image.open(image_path).convert('RGB').resize(size)
    pixels = img.load()
    
    with open(output_path, 'wb') as f:
        # 写文件头
        f.write(b'PXL')           # magic
        f.write(struct.pack('B', 1))   # version
        f.write(struct.pack('<HH', size[0], size[1]))  # width, height
        f.write(struct.pack('<H', 1))  # frame_count
        f.write(struct.pack('<H', 200))  # frame_interval
        f.write(struct.pack('<H', 1))  # flags (loop)
        f.write(struct.pack('<H', 0))  # reserved
        
        # 写像素数据
        for y in range(size[1]):
            for x in range(size[0]):
                r, g, b = pixels[x, y]
                rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                f.write(struct.pack('<H', rgb565))
```

### C++ 读取PXL数据

```cpp
struct PxlHeader {
    char magic[3];        // "PXL"
    uint8_t version;      // 1
    uint16_t width;       // 图像宽度
    uint16_t height;      // 图像高度
    uint16_t frame_count; // 帧数
    uint16_t frame_interval; // 帧间隔
    uint16_t flags;       // 标志位
    uint16_t reserved;    // 保留
} __attribute__((packed)); // 确保无对齐填充，总16字节

// 验证PXL文件
bool validate_pxl(const uint8_t* data, size_t len) {
    if (len < 16) return false;
    const PxlHeader* header = (const PxlHeader*)data;
    if (memcmp(header->magic, "PXL", 3) != 0) return false;
    if (header->version != 1) return false;
    
    size_t expected = 16 + header->frame_count * header->width * header->height * 2;
    return len >= expected;
}
```

## 兼容性说明

- 版本1.0是初始版本，保留了reserved字段和flags高位用于未来扩展
- ESP32端应检查version字段，不支持的版本应忽略并报告错误
- flags中的LOOP位是最常用的控制位，其他位保留为0
- 帧间隔为0表示使用默认值（200ms）
