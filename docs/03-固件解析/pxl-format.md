# PXL 像素格式规范

> PXL（PiXeL）是一种专为 ESP32 桌面宠物设计的紧凑二进制像素文件格式。
> 支持单帧图案与多帧动画，采用 RGB565 色彩空间，可直接映射到 LCD 显示缓冲区，
> 并提供 RLE 压缩与 Delta 差分帧编码以显著降低存储与传输开销。

---

## 一、文件头结构

PXL 文件以 16 字节的固定头部开始，所有多字节字段均采用 **little-endian** 字节序。

```
偏移量    字节数    类型      字段名            说明
──────────────────────────────────────────────────────────────
0x00      3         char[3]   magic             魔数 "PXL" (0x50, 0x58, 0x4C)
0x03      1         uint8     version           格式版本号，当前为 0x01
0x04      2         uint16    width             图像宽度（像素）
0x06      2         uint16    height            图像高度（像素）
0x08      2         uint16    frame_count       帧数（1 = 静态图，>1 = 动画）
0x0A      2         uint16    frame_interval    帧间隔（毫秒），0 表示使用默认值 200ms
0x0C      2         uint16    flags             标志位（详见下表）
0x0E      2         uint16    reserved          保留字段，应填 0x0000
```

### 标志位（flags）定义

| 位   | 名称         | 说明                                           |
|------|-------------|------------------------------------------------|
| bit0 | `PXL_FLAG_LOOP`  | 循环播放：1 = 循环，0 = 播放一次后停止           |
| bit1 | `PXL_FLAG_RLE`   | RLE 压缩：1 = 帧数据已使用 RLE 编码，0 = 原始数据 |
| bit2 | `PXL_FLAG_DELTA` | Delta 差分帧编码：1 = 使用差分编码（与 RLE 互斥）  |
| bit3-15 | -           | 保留，应填 0                                    |

对应的 C++ 常量定义：

```cpp
#define PXL_FLAG_LOOP     0x0001
#define PXL_FLAG_RLE      0x0002
#define PXL_FLAG_DELTA    0x0004
```

### C++ 结构体定义

```cpp
#pragma pack(push, 1)
struct PxlFileHeader {
    char     magic[3];        // "PXL"
    uint8_t  version;         // 1
    uint16_t width;           // 图像宽度
    uint16_t height;          // 图像高度
    uint16_t frame_count;     // 帧数
    uint16_t frame_interval;  // 帧间隔(ms)
    uint16_t flags;           // 标志位
    uint16_t reserved;        // 保留
};
#pragma pack(pop)
```

> `#pragma pack(push, 1)` 确保结构体无对齐填充，严格占满 16 字节。

---

## 二、像素数据格式

### RGB565 编码

每个像素占 16 位（2 字节），采用 RGB565 格式：

```
位布局：RRRRRGGGGGGBBBBB

  Bit 15-11 : Red   （5 位，取值范围 0-31）
  Bit 10-5  : Green （6 位，取值范围 0-63）
  Bit  4-0  : Blue  （5 位，取值范围 0-31）
```

### RGB888 到 RGB565 转换

```python
# RGB888 → RGB565
R5 = R8 >> 3
G6 = G8 >> 2
B5 = B8 >> 3
pixel = (R5 << 11) | (G6 << 5) | B5

# RGB565 → RGB888（反向还原）
R8 = (pixel >> 11) << 3
G8 = ((pixel >> 5) & 0x3F) << 3
B8 = (pixel & 0x1F) << 3
```

> **精度损失说明**：RGB888 到 RGB565 的转换为有损压缩。R 和 B 通道丢失低 3 位，
> G 通道丢失低 2 位。对于像素艺术风格的桌面宠物图案，肉眼几乎无法察觉差异。

### 像素排列顺序

像素按**行优先**（Row-Major）排列，从左到右、从上到下扫描：

```
像素在文件中的字节顺序：

  pixel(0,0) | pixel(1,0) | ... | pixel(W-1,0) |   ← 第 0 行
  pixel(0,1) | pixel(1,1) | ... | pixel(W-1,1) |   ← 第 1 行
  ...
  pixel(0,H-1) | ...              | pixel(W-1,H-1)  ← 第 H-1 行
```

---

## 三、RLE 压缩编码

当 `flags` 的 bit1 置位（`PXL_FLAG_RLE = 0x0002`）时，帧数据采用 RLE（Run-Length Encoding）
游程编码压缩。解压后的数据等价于原始 RGB565 像素流。

### 编码格式

压缩数据由一系列 `[flag_byte][data]` 单元组成：

```
┌──────────────────────────────────────────────────────────┐
│ flag_byte (1 byte)  │  data (变长)                       │
└──────────────────────────────────────────────────────────┘
```

**flag_byte 含义：**

| 条件              | 含义                     | data 长度            |
|-------------------|--------------------------|----------------------|
| `flag_byte >= 0x80`（bit7=1） | **Run 段**：连续相同像素  | 2 字节（重复像素值，big-endian） |
| `flag_byte < 0x80`（bit7=0）  | **Literal 段**：各不相同像素 | `flag_byte × 2` 字节（原始像素数据） |

- **Run 长度** = `flag_byte & 0x7F`，取值范围 1-127
- **Literal 长度** = `flag_byte`，取值范围 1-127

### 解压伪代码

```
while output_pos < total_pixels:
    flag = read_byte()
    if flag & 0x80:                         // Run 段
        count = flag & 0x7F
        pixel = read_uint16_big_endian()
        repeat count times:
            output(pixel)
    else:                                   // Literal 段
        count = flag
        copy (count * 2) bytes directly from input to output
```

### 压缩效果

| 场景           | 典型压缩比        |
|---------------|-------------------|
| 纯色背景       | 约 20:1           |
| 像素艺术图案    | 约 2:1 ~ 5:1     |
| 复杂渐变图像    | 约 1.2:1 ~ 2:1   |

---

## 四、Delta 差分帧编码

当 `flags` 的 bit2 置位（`PXL_FLAG_DELTA = 0x0004`）时，采用帧间差分编码。
**第 0 帧为完整帧**，后续帧（第 1 帧起）仅记录相对于前一帧的变化像素。

### 操作码定义

| 操作码        | 值    | 格式                        | 说明                            |
|--------------|-------|----------------------------|---------------------------------|
| `COPY`       | 0x00  | `0x00, N`                  | 跳过 N 个未变化像素              |
| `REPEAT`     | 0x01  | `0x01, N, pixel_lo, pixel_hi` | N 个连续变化像素（同一新值）      |
| `LITERAL`    | >=0x02 | `N, pixel_0, pixel_1, ..., pixel_{N-1}` | N 个各自不同的变化像素 |

- **COPY**：后续 1 字节为跳过数量，像素数据继承前一帧，不产生额外输出。
- **REPEAT**：后续 1 字节为重复数量，再接 2 字节像素值（little-endian），所有像素填入同一颜色。
- **LITERAL**：操作码本身即为像素数量（`opcode >= 0x02`），后续接 `N × 2` 字节各不相同的像素值。

### 编码策略

```
对于每帧的每个像素位置：
  如果 curr_pixel == prev_pixel:
      累积为 COPY 段
  如果 curr_pixel != prev_pixel 且后续连续多个像素相同新值:
      编码为 REPEAT 段
  如果 curr_pixel != prev_pixel 且各像素值不同:
      编码为 LITERAL 段
```

### 压缩效果

对于典型的桌面宠物动画（只有局部区域在帧间变化），Delta 编码可实现 **60%-90%** 的大小缩减。
例如一个 8 帧的 32x32 动画，原始大小约 16 KB，Delta 编码后可降至 2-6 KB。

---

## 五、JSON 传输格式

PXL 数据通过 TCP 发送到 ESP32 时，使用 JSON 编码。根据文件大小分为两种传输模式。

### 分块传输（标准方式）

大文件拆分为多个 1024 字节的 chunk 分包传输：

```json
{
  "type": "pixel_data",
  "data": {
    "packet_index": 0,
    "total_packets": 8,
    "chunk_base64": "<base64 编码的分块数据>"
  },
  "ts": 1234567890
}
```

**字段说明：**

| 字段             | 类型   | 说明                                |
|-----------------|--------|-------------------------------------|
| `packet_index`  | int    | 当前包序号（从 0 开始）              |
| `total_packets` | int    | 总包数                              |
| `chunk_base64`  | string | base64 编码的分块二进制数据           |

### 接收端拼包逻辑

1. 分配 `width × height × frame_count × 2` 字节的缓冲区
2. 按 `packet_index` 顺序接收，将 `chunk_base64` 解码后写入对应偏移位置
3. 收到所有包后组装为完整的 PXL 文件数据
4. 解析文件头，切换到像素显示模式

### 控制命令

传输完成后，通过控制命令切换显示模式：

```json
{
  "type": "pixel_cmd",
  "data": {
    "command": "switch_mode",
    "mode": "pixel"
  },
  "ts": 1234567890
}
```

---

## 六、文件大小计算

### 原始数据（无压缩）

```
file_size = 16 + frame_count × width × height × 2
```

**常见尺寸示例：**

| 分辨率    | 帧数 | 原始大小  | 用途           |
|----------|------|----------|---------------|
| 32 × 32  | 1    | 2,064 B  | 静态图标       |
| 32 × 32  | 4    | 8,208 B  | 简单动画       |
| 32 × 32  | 8    | 16,400 B | 多帧动画       |
| 64 × 64  | 4    | 32,784 B | 高清动画       |
| 64 × 64  | 8    | 65,552 B | 高清多帧动画   |

### RLE 压缩后

压缩后大小取决于像素内容的重复程度，通常为原始大小的 **20%-50%**。

### Delta 编码后

Delta 编码后大小取决于帧间变化幅度，通常为原始大小的 **10%-40%**。
帧间变化越小，压缩率越高。

---

## 七、编解码参考

### Python 编码器

文件路径：`pixel_tool/pxl_encoder.py`

提供两个核心编码函数：

```python
def image_to_pxl(image_path: str, output_path: str, size=(32, 32)) -> bytes:
    """将单张图片编码为 PXL 文件（单帧）"""

def gif_to_pxl(gif_path: str, output_path: str, size=(32, 32),
               interval: int = 200, delta: bool = True) -> bytes:
    """将 GIF 动画编码为 PXL 文件（多帧，支持 Delta 编码）"""
```

RLE 压缩核心函数：

```python
def rle_compress(rgb565_data: bytes) -> bytes:
    """对 RGB565 像素流进行 RLE 压缩"""
```

Delta 差分帧压缩器：

```python
class DeltaCompressor:
    @staticmethod
    def encode(prev_rgb565: bytes, curr_rgb565: bytes) -> bytes:
        """生成差分帧：仅编码 prev → curr 的变化像素"""

    @staticmethod
    def decode(prev_rgb565: bytes, delta_data: bytes, pixel_count: int) -> bytes:
        """从差分帧还原完整帧：prev + delta → curr"""
```

### C++ 解码器

文件路径：`esp32_firmware/src/pixel_player.h` / `pixel_player.cpp`

核心类 `PixelPlayer` 提供完整的加载与播放接口：

```cpp
class PixelPlayer {
public:
    bool loadFromBuffer(const uint8_t* data, size_t len);  // 从内存加载 PXL 数据
    void play();                                            // 开始播放
    void pause();                                           // 暂停
    void stop();                                            // 停止
    bool update();                                          // 主循环中调用，返回是否需要重绘
    uint16_t* getFrameBuffer() const;                       // 获取当前帧 RGB565 数据指针
    uint16_t* getCurrentFrame();                            // 获取当前帧数据

private:
    bool loadFrameData(const uint8_t* data, size_t len);   // 解析帧数据
    bool rleDecompress(const uint8_t* compressed, size_t compLen,
                       uint16_t* output, size_t pixelCount); // RLE 解压
    bool deltaDecompress(const uint8_t* deltaData, size_t deltaLen,
                         const uint16_t* prevFrame,
                         uint16_t* output, size_t pixelCount); // Delta 解压
};
```

### 关键常量

```cpp
#define PXL_HEADER_SIZE   16      // 文件头大小
#define PXL_MAX_FRAMES    64      // 最大帧数
#define PXL_FLAG_LOOP     0x0001  // 循环播放标志
#define PXL_FLAG_RLE      0x0002  // RLE 压缩标志
#define PXL_FLAG_DELTA    0x0004  // Delta 差分标志
```

---

## 附录：格式版本历史

| 版本  | 变更说明                                    |
|------|---------------------------------------------|
| v1.0 | 初始版本：RGB565 + RLE 压缩 + 循环播放       |
| v1.0+| 新增 Delta 差分帧编码（flags bit2）           |

> ESP32 端应检查 `version` 字段，遇到不支持的版本应忽略并报告错误。
> `reserved` 字段和 `flags` 高位保留用于未来扩展，当前应填 0。
