# Pixel Tool - 桌面宠物自定义像素工具

将图片/GIF转换为 .pxl 二进制像素文件，并通过WiFi推送到ESP32桌面宠物显示。

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 转换图片为 .pxl 文件

```bash
# 单张图片（静态像素）
python pixel_tool.py convert heart.png -o heart.pxl

# GIF动画（多帧动画）
python pixel_tool.py convert dance.gif -o dance.pxl

# 雪碧图（一行N帧，指定帧数）
python pixel_tool.py convert sprite.png --frames 4 -o sprite.pxl
```

### 2. 查看 .pxl 文件信息

```bash
python pixel_tool.py info heart.pxl
```

输出示例：
```
=== PXL File Info ===
  Size:    32x32
  Frames:  1
  Interval: 200 ms
  Loop:    Yes
  File:    2064 bytes
```

### 3. 发送到ESP32

```bash
# 发送.pxl文件并自动播放
python pixel_tool.py send heart.pxl 192.168.1.100

# 指定端口
python pixel_tool.py send dance.pxl 192.168.1.100 -p 19876
```

### 4. 控制命令

```bash
# 播放（已加载的像素文件）
python pixel_tool.py cmd play 192.168.1.100

# 停止（返回正常表情）
python pixel_tool.py cmd stop 192.168.1.100

# 暂停/恢复
python pixel_tool.py cmd pause 192.168.1.100
python pixel_tool.py cmd resume 192.168.1.100
```

## PXL 文件格式

- 分辨率：32×32 像素
- 颜色：RGB565 (16bit)
- 文件头：16字节 (PXL magic + version + 宽高 + 帧数 + 帧间隔 + 标志)
- 像素数据：行优先排列，每帧 32×32×2 = 2048 字节
- 最大支持：64帧动画，单文件约128KB

## 示例文件

`examples/` 目录下包含：
- `heart.pxl` - 红色心形
- `smile.pxl` - 笑脸
- `rainbow.pxl` - 彩虹条纹

## 编程接口

```python
from pxl_encoder import image_to_pxl, gif_to_pxl
from pxl_sender import send_pxl_to_esp32, send_pixel_command

# 转换
image_to_pxl("my_image.png", "output.pxl")
gif_to_pxl("animation.gif", "output.pxl")

# 发送
send_pxl_to_esp32("output.pxl", "192.168.1.100", 19876)

# 控制
send_pixel_command("192.168.1.100", 19876, "play")
send_pixel_command("192.168.1.100", 19876, "stop")
```
