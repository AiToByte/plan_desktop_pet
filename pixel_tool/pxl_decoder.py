"""
PXL 像素解码器
将 .pxl 二进制像素文件解码为图片/GIF
支持 RLE 压缩格式
"""
import struct
from pathlib import Path
from PIL import Image

PXL_MAGIC = b'PXL'
PXL_HEADER_SIZE = 16
PXL_FLAG_LOOP = 0x0001
PXL_FLAG_RLE = 0x0002

# RLE参数(与encoder一致)
RLE_MAX_COUNT = 127
RGB565_BYTES = 2


def read_pxl_header(data: bytes) -> dict:
    """读取PXL文件头"""
    if len(data) < PXL_HEADER_SIZE:
        raise ValueError("数据太小，无法包含PXL文件头")
    if data[0:3] != PXL_MAGIC:
        raise ValueError(f"无效的PXL文件: magic={data[0:3]}")

    return {
        'version': data[3],
        'width': struct.unpack_from('<H', data, 4)[0],
        'height': struct.unpack_from('<H', data, 6)[0],
        'frame_count': struct.unpack_from('<H', data, 8)[0],
        'frame_interval': struct.unpack_from('<H', data, 10)[0],
        'flags': struct.unpack_from('<H', data, 12)[0],
    }


def rle_decompress(compressed: bytes, pixel_count: int) -> bytes:
    """RLE解压为原始RGB565数据
    Args:
        compressed: RLE压缩后的字节流
        pixel_count: 期望的像素总数
    Returns:
        解压后的RGB565字节流 (pixel_count * RGB565_BYTES bytes)
    """
    result = bytearray(pixel_count * RGB565_BYTES)
    src = 0
    dst = 0

    while dst < pixel_count * RGB565_BYTES and src < len(compressed):
        flag = compressed[src]
        src += 1

        if flag & 0x80:
            # Run: flag & 0x7F 次重复像素(big-endian)
            count = flag & RLE_MAX_COUNT
            pixel_be = (compressed[src] << 8) | compressed[src + 1]
            src += 2
            pixel_le = struct.pack('<H', pixel_be)
            for _ in range(count):
                result[dst] = pixel_le[0]
                result[dst + 1] = pixel_le[1]
                dst += 2
        else:
            # Literal: flag 个原始像素(little-endian直接复制)
            count = flag
            byte_count = count * 2
            result[dst:dst + byte_count] = compressed[src:src + byte_count]
            src += byte_count
            dst += byte_count

    return bytes(result[:pixel_count * RGB565_BYTES])


def pxl_to_frames(pxl_path: str) -> list:
    """将PXL文件解码为PIL图像帧列表
    Returns:
        list of PIL.Image.Image
    """
    pxl_path = Path(pxl_path)
    if not pxl_path.exists():
        raise FileNotFoundError(f"PXL文件不存在: {pxl_path}")

    data = pxl_path.read_bytes()
    header = read_pxl_header(data)
    w, h = header['width'], header['height']
    frame_count = header['frame_count']
    flags = header['flags']
    is_rle = flags & PXL_FLAG_RLE

    frame_size = w * h * 2  # 每帧字节数(解压后)
    frames = []

    pixel_data = data[PXL_HEADER_SIZE:]

    if is_rle:
        # RLE模式: 需要逐帧解压
        # 对于RLE压缩，帧边界通过解压到目标像素数来确定
        src_pos = 0
        for i in range(frame_count):
            frame_pixels = w * h
            decompressed = rle_decompress(pixel_data[src_pos:], frame_pixels)
            # 计算实际消耗的压缩字节数（通过重新扫描）
            consumed = _calc_rle_consumed(pixel_data[src_pos:], frame_pixels)
            src_pos += consumed
            frames.append(_rgb565_to_image(decompressed, w, h))
    else:
        # 原始模式: 直接切分
        for i in range(frame_count):
            offset = i * frame_size
            frame_data = pixel_data[offset:offset + frame_size]
            frames.append(_rgb565_to_image(frame_data, w, h))

    return frames


def _calc_rle_consumed(compressed: bytes, pixel_count: int) -> int:
    """计算解压pixel_count个像素需要消耗的压缩字节数"""
    src = 0
    dst = 0
    target = pixel_count * RGB565_BYTES

    while dst < target and src < len(compressed):
        flag = compressed[src]
        src += 1
        if flag & 0x80:
            count = flag & RLE_MAX_COUNT
            src += 2
            dst += count * 2
        else:
            count = flag
            src += count * 2
            dst += count * 2

    return src


def _rgb565_to_image(data: bytes, w: int, h: int) -> Image.Image:
    """将RGB565字节数据转换为PIL图像"""
    img = Image.new('RGB', (w, h))
    pixels = img.load()
    for y in range(h):
        for x in range(w):
            offset = (y * w + x) * 2
            pixel = struct.unpack_from('<H', data, offset)[0]
            r = ((pixel >> 11) & 0x1F) << 3
            g = ((pixel >> 5) & 0x3F) << 2
            b = (pixel & 0x1F) << 3
            pixels[x, y] = (r, g, b)
    return img


def pxl_to_png(pxl_path: str, output_path: str = None) -> str:
    """将PXL文件解码为PNG（静态图取第一帧，动画取第一帧）"""
    pxl_path = Path(pxl_path)
    frames = pxl_to_frames(str(pxl_path))
    if not frames:
        raise ValueError("无有效帧")

    if output_path is None:
        output_path = str(pxl_path.with_suffix('.png'))

    frames[0].save(output_path)
    print(f"[OK] 解码: {output_path}")
    return output_path


def pxl_to_gif(pxl_path: str, output_path: str = None) -> str:
    """将PXL动画文件解码为GIF"""
    pxl_path = Path(pxl_path)
    header = read_pxl_header(pxl_path.read_bytes())
    frames = pxl_to_frames(str(pxl_path))

    if output_path is None:
        output_path = str(pxl_path.with_suffix('.gif'))

    if len(frames) == 1:
        frames[0].save(output_path)
    else:
        interval = header['frame_interval']
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=interval,
            loop=0 if header['flags'] & PXL_FLAG_LOOP else 1
        )

    print(f"[OK] 解码: {output_path} ({len(frames)}帧)")
    return output_path


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python pxl_decoder.py <file.pxl> [output.png|output.gif]")
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None
    header = read_pxl_header(Path(src).read_bytes())
    if header['frame_count'] > 1:
        pxl_to_gif(src, dst)
    else:
        pxl_to_png(src, dst)
