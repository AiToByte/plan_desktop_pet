"""
PXL编码器单元测试
"""
import struct
import unittest
import tempfile

from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pixel_tool"))

from pxl_encoder import (
    rgb888_to_rgb565,
    image_to_rgb565_data,
    rle_compress,
    create_pxl_header,
    PXL_MAGIC,
    PXL_VERSION,
    PXL_FLAG_RLE,
)


class TestRgb888ToRgb565(unittest.TestCase):
    """测试RGB888到RGB565转换"""

    def test_white(self):
        """白色(255,255,255) -> 0xFFFF"""
        assert rgb888_to_rgb565(255, 255, 255) == 0xFFFF

    def test_black(self):
        """黑色(0,0,0) -> 0x0000"""
        assert rgb888_to_rgb565(0, 0, 0) == 0x0000

    def test_red(self):
        """纯红(255,0,0) -> 0xF800"""
        assert rgb888_to_rgb565(255, 0, 0) == 0xF800

    def test_green(self):
        """纯绿(0,255,0) -> 0x07E0"""
        assert rgb888_to_rgb565(0, 255, 0) == 0x07E0

    def test_blue(self):
        """纯蓝(0,0,255) -> 0x001F"""
        assert rgb888_to_rgb565(0, 0, 255) == 0x001F

    def test_mid_gray(self):
        """中间灰(128,128,128)"""
        result = rgb888_to_rgb565(128, 128, 128)
        # 验证各通道大致正确
        r5 = (result >> 11) & 0x1F
        g6 = (result >> 5) & 0x3F
        b5 = result & 0x1F
        assert abs(r5 - 16) <= 1  # 128>>3 = 16
        assert abs(g6 - 32) <= 1  # 128>>2 = 32
        assert abs(b5 - 16) <= 1  # 128>>3 = 16


class TestImageToRgb565Data(unittest.TestCase):
    """测试图像转RGB565数据"""

    def test_1x1_white_image(self):
        """1x1白色图像"""
        img = MagicMock()
        img.convert.return_value = img
        img.size = (1, 1)
        pixels = {(0, 0): (255, 255, 255)}
        img.load.return_value = pixels

        data = image_to_rgb565_data(img)
        assert len(data) == 2  # 1像素 * 2字节
        pixel = struct.unpack('<H', data)[0]
        assert pixel == 0xFFFF

    def test_2x2_image_size(self):
        """2x2图像应该产生8字节"""
        img = MagicMock()
        img.convert.return_value = img
        img.size = (2, 2)
        pixels = {
            (0, 0): (255, 0, 0),
            (1, 0): (0, 255, 0),
            (0, 1): (0, 0, 255),
            (1, 1): (0, 0, 0),
        }
        img.load.return_value = pixels

        data = image_to_rgb565_data(img)
        assert len(data) == 8  # 4像素 * 2字节


class TestRleCompress(unittest.TestCase):
    """测试RLE压缩"""

    def test_all_same_pixels(self):
        """所有像素相同时应压缩"""
        # 4个相同的白色像素
        pixel = struct.pack('<H', 0xFFFF)
        data = pixel * 4
        compressed = rle_compress(data)
        # 应该是: flag=0x80|4, pixel(2 bytes) = 3字节
        assert len(compressed) < len(data)

    def test_all_different_pixels(self):
        """所有像素不同时应保持原样"""
        pixels = [
            struct.pack('<H', 0x0000),
            struct.pack('<H', 0x0001),
            struct.pack('<H', 0x0002),
            struct.pack('<H', 0x0003),
        ]
        data = b''.join(pixels)
        compressed = rle_compress(data)
        # literal模式: flag(1) + 4*2像素 = 9字节
        assert len(compressed) == 9

    def test_mixed_pattern(self):
        """混合模式：重复+不重复"""
        # 3个相同 + 2个不同
        same_pixel = struct.pack('<H', 0xABCD)
        diff_pixel1 = struct.pack('<H', 0x1234)
        diff_pixel2 = struct.pack('<H', 0x5678)
        data = same_pixel * 3 + diff_pixel1 + diff_pixel2
        compressed = rle_compress(data)
        # 应包含run和literal
        assert len(compressed) > 0

    def test_empty_input(self):
        """空输入"""
        compressed = rle_compress(b'')
        assert compressed == b''

    def test_single_pixel(self):
        """单个像素"""
        pixel = struct.pack('<H', 0x1234)
        compressed = rle_compress(pixel)
        # literal: flag(1) + pixel(2) = 3字节
        assert len(compressed) == 3


class TestCreatePxlHeader(unittest.TestCase):
    """测试PXL文件头创建"""

    def test_header_size(self):
        """文件头应为16字节"""
        header = create_pxl_header(32, 32, 1, 200)
        assert len(header) == 16

    def test_header_magic(self):
        """文件头应以PXL开头"""
        header = create_pxl_header(32, 32, 1, 200)
        assert header[0:3] == PXL_MAGIC

    def test_header_version(self):
        """版本号应正确"""
        header = create_pxl_header(32, 32, 1, 200)
        assert header[3] == PXL_VERSION

    def test_header_dimensions(self):
        """尺寸应正确编码"""
        header = create_pxl_header(64, 48, 1, 200)
        width = struct.unpack_from('<H', header, 4)[0]
        height = struct.unpack_from('<H', header, 6)[0]
        assert width == 64
        assert height == 48

    def test_header_frame_count(self):
        """帧数应正确编码"""
        header = create_pxl_header(32, 32, 5, 100)
        frame_count = struct.unpack_from('<H', header, 8)[0]
        assert frame_count == 5

    def test_header_interval(self):
        """帧间隔应正确编码"""
        header = create_pxl_header(32, 32, 1, 500)
        interval = struct.unpack_from('<H', header, 10)[0]
        assert interval == 500

    def test_header_flags_none(self):
        """无标志时flags=0"""
        header = create_pxl_header(32, 32, 1, 200, flags=0)
        flags = struct.unpack_from('<H', header, 12)[0]
        assert flags == 0

    def test_header_flags_loop(self):
        """循环标志"""
        header = create_pxl_header(32, 32, 1, 200, flags=1)
        flags = struct.unpack_from('<H', header, 12)[0]
        assert flags & 0x0001

    def test_header_flags_rle(self):
        """RLE压缩标志"""
        header = create_pxl_header(32, 32, 1, 200, flags=PXL_FLAG_RLE)
        flags = struct.unpack_from('<H', header, 12)[0]
        assert flags & PXL_FLAG_RLE
