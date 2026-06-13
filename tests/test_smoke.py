"""
Smoke tests - 基础导入和功能验证
确保项目模块可以正常导入
"""
import unittest
import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent


class TestProjectStructure(unittest.TestCase):
    """测试项目目录结构"""

    def test_project_structure(self):
        """测试项目目录结构"""
        self.assertTrue((PROJECT_ROOT / "pc_monitor").is_dir(), "pc_monitor目录不存在")
        self.assertTrue((PROJECT_ROOT / "pixel_tool").is_dir(), "pixel_tool目录不存在")
        self.assertTrue((PROJECT_ROOT / "tests").is_dir(), "tests目录不存在")
        self.assertTrue((PROJECT_ROOT / "pyproject.toml").is_file(), "pyproject.toml不存在")

    def test_pc_monitor_modules_exist(self):
        """测试pc_monitor模块文件存在"""
        modules_dir = PROJECT_ROOT / "pc_monitor" / "modules"
        self.assertTrue(modules_dir.is_dir())
        expected = ["agent_monitor.py", "weather.py", "communication.py", "token_stats.py", "otlp_receiver.py"]
        for mod in expected:
            self.assertTrue((modules_dir / mod).exists(), f"缺少模块: {mod}")

    def test_pixel_tool_files_exist(self):
        """测试pixel_tool文件存在"""
        pt_dir = PROJECT_ROOT / "pixel_tool"
        expected = ["pixel_tool.py", "pxl_encoder.py", "pxl_decoder.py", "pxl_sender.py"]
        for f in expected:
            self.assertTrue((pt_dir / f).exists(), f"缺少文件: {f}")


class TestBasicImports(unittest.TestCase):
    """测试基础模块导入"""

    def test_import_dataclasses(self):
        """测试dataclasses可用"""
        from dataclasses import dataclass
        self.assertIsNotNone(dataclass)

    def test_import_enum(self):
        """测试enum可用"""
        from enum import Enum
        self.assertIsNotNone(Enum)

    def test_import_struct(self):
        """测试struct可用"""
        import struct
        self.assertIsNotNone(struct)


if __name__ == "__main__":
    unittest.main()
