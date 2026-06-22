"""
PXL 像素编码器
将图片/GIF 转换为 .pxl 二进制像素文件
"""
import struct
import numpy as np
from pathlib import Path
from PIL import Image

PXL_MAGIC = b'PXL'
PXL_VERSION = 1
PXL_FLAG_RLE = 0x0002  # flags bit1: RLE压缩
DEFAULT_SIZE = (32, 32)
DEFAULT_INTERVAL = 200  # ms

# RLE压缩参数
RLE_MAX_COUNT = 127      # 单次run/literal最大长度
RLE_MIN_RUN = 3          # 最小run长度(短于此用literal)
RGB565_BYTES = 2         # 每像素字节数
PXL_HEADER_BYTES = 16    # PXL文件头大小


def rgb888_to_rgb565(r, g, b):
    """RGB888 -> RGB565"""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def image_to_rgb565_data(img: Image.Image) -> bytes:
    """将PIL图像转换为RGB565字节数据（numpy向量化，比纯Python循环快10-50倍）"""
    img = img.convert('RGB')
    arr = np.array(img, dtype=np.uint8)  # shape: (H, W, 3)
    if arr.ndim == 2:
        # 1x1 或单行极端情况，PIL可能返回2D数组
        arr = arr.reshape(1, 1, 3) if arr.size == 3 else arr.reshape(arr.shape[0], 1, 3)
    r = arr[:, :, 0].astype(np.uint16)
    g = arr[:, :, 1].astype(np.uint16)
    b = arr[:, :, 2].astype(np.uint16)
    rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return rgb565.astype(np.uint16).tobytes()


def rle_compress(rgb565_data: bytes) -> bytes:
    """RLE压缩RGB565数据流
    格式: [flag_byte][data]
    - bit7=1: run长度=(flag & 0x7F), 后接2字节重复像素(big-endian)
    - bit7=0: literal长度=flag, 后接 flag*2 字节原始像素
    """
    result = bytearray()
    pos = 0
    total = len(rgb565_data) // 2  # 总像素数

    while pos < total:
        # 检查是否有连续重复像素(至少2个)
        run_len = 1
        if pos + 1 < total:
            pixel0 = struct.unpack_from('<H', rgb565_data, pos * 2)[0]
            while pos + run_len < total and run_len < RLE_MAX_COUNT:
                pixel_n = struct.unpack_from('<H', rgb565_data, (pos + run_len) * 2)[0]
                if pixel_n != pixel0:
                    break
                run_len += 1

        if run_len >= RLE_MIN_RUN:
            # 写入run: flag=0x80|count, pixel(big-endian)
            result.append(0x80 | run_len)
            result.extend(struct.pack('>H', pixel0))
            pos += run_len
        else:
            # 收集literal序列
            lit_start = pos
            while pos < total and (pos - lit_start) < RLE_MAX_COUNT:
                # 检查是否接下来出现3+连续重复
                if pos + 2 < total:
                    p = struct.unpack_from('<H', rgb565_data, pos * 2)[0]
                    if (struct.unpack_from('<H', rgb565_data, (pos+1) * 2)[0] == p and
                        struct.unpack_from('<H', rgb565_data, (pos+2) * 2)[0] == p):
                        break
                pos += 1
            lit_count = pos - lit_start
            if lit_count > 0:
                result.append(lit_count)
                for i in range(lit_count):
                    result.extend(struct.pack('<H', struct.unpack_from('<H', rgb565_data, (lit_start + i) * 2)[0]))

    return bytes(result)


def create_pxl_header(width: int, height: int, frame_count: int,
                      frame_interval: int = DEFAULT_INTERVAL, flags: int = 1) -> bytes:
    """创建PXL文件头（16字节）"""
    header = bytearray(16)
    header[0:3] = PXL_MAGIC
    header[3] = PXL_VERSION
    struct.pack_into('<H', header, 4, width)
    struct.pack_into('<H', header, 6, height)
    struct.pack_into('<H', header, 8, frame_count)
    struct.pack_into('<H', header, 10, frame_interval)
    struct.pack_into('<H', header, 12, flags)
    struct.pack_into('<H', header, 14, 0)  # reserved
    return bytes(header)


def image_to_pxl(image_path: str, output_path: str = None, size: tuple = DEFAULT_SIZE,
                 interval: int = DEFAULT_INTERVAL, loop: bool = True) -> str:
    """将单张图片转换为.pxl文件"""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")
    if output_path is None:
        output_path = image_path.with_suffix('.pxl')

    img = Image.open(image_path)
    img = img.resize(size, Image.LANCZOS)

    header = create_pxl_header(size[0], size[1], 1, interval, flags=1 if loop else 0)
    pixel_data = image_to_rgb565_data(img)

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(pixel_data)

    print(f"[OK] 生成: {output_path} ({size[0]}x{size[1]}, 1帧, {len(header)+len(pixel_data)} bytes)")
    return str(output_path)


def gif_to_pxl(gif_path: str, output_path: str = None, size: tuple = DEFAULT_SIZE,
               max_frames: int = 16, loop: bool = True, progress_cb=None) -> str:
    """将GIF动画转换为.pxl多帧文件（支持progress_cb(current, total)回调）"""
    gif_path = Path(gif_path)
    if not gif_path.exists():
        raise FileNotFoundError(f"GIF不存在: {gif_path}")
    if output_path is None:
        output_path = gif_path.with_suffix('.pxl')

    gif = Image.open(gif_path)
    frames = []
    try:
        while len(frames) < max_frames:
            frame = gif.copy().convert('RGBA')
            bg = Image.new('RGBA', frame.size, (255, 255, 255, 255))
            bg.paste(frame, mask=frame.split()[3] if frame.mode == 'RGBA' else None)
            frames.append(bg.resize(size, Image.LANCZOS).convert('RGB'))
            gif.seek(gif.tell() + 1)
    except EOFError:
        pass

    if not frames:
        raise ValueError(f"GIF无有效帧: {gif_path}")

    try:
        duration = gif.info.get('duration', 100)
        interval = max(50, duration)
    except (KeyError, AttributeError):
        interval = DEFAULT_INTERVAL

    header = create_pxl_header(size[0], size[1], len(frames), interval, flags=1 if loop else 0)
    pixel_frames = []
    for i, f in enumerate(frames):
        pixel_frames.append(image_to_rgb565_data(f))
        if progress_cb:
            progress_cb(i + 1, len(frames))
    pixel_data = b''.join(pixel_frames)

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(pixel_data)

    file_size = len(header) + len(pixel_data)
    print(f"[OK] 生成: {output_path} ({size[0]}x{size[1]}, {len(frames)}帧, {interval}ms, {file_size} bytes)")
    return str(output_path)


def png_to_pxl_frames(png_path: str, output_path: str = None, size: tuple = DEFAULT_SIZE,
                      interval: int = DEFAULT_INTERVAL, progress_cb=None) -> str:
    """将PNG雪碧图（水平排列的帧序列）转换为.pxl文件（支持progress_cb回调）"""
    png_path = Path(png_path)
    if not png_path.exists():
        raise FileNotFoundError(f"图片不存在: {png_path}")
    if output_path is None:
        output_path = png_path.with_suffix('.pxl')

    img = Image.open(png_path).convert('RGB')
    w, h = img.size
    if w <= h:
        return image_to_pxl(str(png_path), output_path, size, interval)

    frame_w = h
    frame_count = w // frame_w
    if frame_count == 0:
        return image_to_pxl(str(png_path), output_path, size, interval)

    frames = []
    for i in range(frame_count):
        box = (i * frame_w, 0, (i + 1) * frame_w, h)
        frame = img.crop(box).resize(size, Image.LANCZOS)
        frames.append(frame)

    header = create_pxl_header(size[0], size[1], len(frames), interval, flags=1)
    pixel_frames = []
    for i, f in enumerate(frames):
        pixel_frames.append(image_to_rgb565_data(f))
        if progress_cb:
            progress_cb(i + 1, len(frames))
    pixel_data = b''.join(pixel_frames)

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(pixel_data)

    file_size = len(header) + len(pixel_data)
    print(f"[OK] 生成: {output_path} ({size[0]}x{size[1]}, {len(frames)}帧, {file_size} bytes)")
    return str(output_path)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python pxl_encoder.py <image|gif> [output.pxl]")
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None
    if src.lower().endswith('.gif'):
        gif_to_pxl(src, dst)
    else:
        image_to_pxl(src, dst)
