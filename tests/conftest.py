"""
pytest配置文件
提供基础fixture和测试工具
"""
import os
import sys
from pathlib import Path

# 添加项目路径到sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "pc_monitor"))
sys.path.insert(0, str(project_root / "pixel_tool"))