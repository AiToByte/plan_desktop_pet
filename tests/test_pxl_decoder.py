"""
PXL解码器单元测试
"""
import struct
import unittest
import tempfile

from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pixel_tool"))

from pxl_decoder import (
    read_pxl_header,
    rle_decompress,
    pxl_to_frames,
    PXL_MAGIC,
    PXL_HEADER_SIZE,
    PXL_FLAG_LOOP,
    PXL_FLAG_RLE,
)


class TestReadPxlHeader(unittest.TestCase):
    """测试PXL文件头读取"""

    def _make_header(self, width=32, height=32, frames=1, interval=200, flags=0):
        """创建测试用文件头"""
        header = bytearray(PXL_HEADER_SIZE)
        header[0:3] = PXL_MAGIC
        header[3] = 1  # version
        struct.pack_into('<H', header, 4, width)
        struct.pack_into('<H', header, 6, height)
        struct.pack_into('<H', header, 8, frames)
        struct.pack_into('<H', header, 10, interval)
        struct.pack_into('<H', header, 12, flags)
        return bytes(header)

    def test_valid_header(self):
        """有效文件头解析"""
        header = self._make_header(64, 48, 5, 100, 0x0003)
        result = read_pxl_header(header)
        assert result['version'] == 1
        assert result['width'] == 64
        assert result['height'] == 48
        assert result['frame_count'] == 5
        assert result['frame_interval'] == 100
        assert result['flags'] == 0x0003

    def test_too_small_data(self):
        """数据太小应抛出异常"""
        with self.assertRaises(ValueError) as cm:
            read_pxl_header(b'\x00' * 10)
        self.assertIn("数据太小", str(cm.exception))

    def test_invalid_magic(self):
        """无效magic应抛出异常"""
        bad_data = b'BAD!' + b'\x00' * 12
        with self.assertRaises(ValueError) as cm:
            read_pxl_header(bad_data)
        self.assertIn("无效的PXL", str(cm.exception))

    def test_exact_header_size(self):
        """恰好16字节应正常解析"""
        header = self._make_header()
        result = read_pxl_header(header)
        assert result['width'] == 32

    def test_header_with_extra_data(self):
        """超过16字节时只解析头部"""
        header = self._make_header() + b'\x00' * 100
        result = read_pxl_header(header)
        assert result['width'] == 32


class TestRleDecompress(unittest.TestCase):
    """测试RLE解压"""

    def test_run_encoding(self):
        """测试run编码解压"""
        # 构造run: flag=0x80|3, pixel=0xFFFF (big-endian)
        compressed = bytes([0x83, 0xFF, 0xFF])
        result = rle_decompress(compressed, 3)
        assert len(result) == 6  # 3像素 * 2字节
        # 每个像素应该是0xFFFF (little-endian)
        for i in range(3):
            pixel = struct.unpack_from('<H', result, i * 2)[0]
            assert pixel == 0xFFFF

    def test_literal_encoding(self):
        """测试literal编码解压"""
        # 构造literal: flag=2, 后接2个像素(4字节)
        pixel1 = struct.pack('<H', 0x1234)
        pixel2 = struct.pack('<H', 0x5678)
        compressed = bytes([2]) + pixel1 + pixel2
        result = rle_decompress(compressed, 2)
        assert len(result) == 4
        assert struct.unpack_from('<H', result, 0)[0] == 0x1234
        assert struct.unpack_from('<H', result, 2)[0] == 0x5678

    def test_empty_compressed(self):
        """空压缩数据"""
        result = rle_decompress(b'', 0)
        assert len(result) == 0

    def test_mixed_encoding(self):
        """混合编码: run + literal"""
        # run: 2个0xABCD像素
        run = bytes([0x82, 0xAB, 0xCD])
        # literal: 1个0x1234像素
        literal = bytes([1]) + struct.pack('<H', 0x1234)
        compressed = run + literal
        result = rle_decompress(compressed, 3)
        assert len(result) == 6
        assert struct.unpack_from('<H', result, 0)[0] == 0xABCD
        assert struct.unpack_from('<H', result, 2)[0] == 0xABCD
        assert struct.unpack_from('<H', result, 4)[0] == 0x1234



if __name__ == "__main__":
    unittest.main()
