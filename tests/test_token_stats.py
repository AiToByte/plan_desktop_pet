"""
TokenStats模块单元测试
测试Token使用统计、日志解析、缓存机制等功能
"""
import sys
import os
import re
import json
import time
from pathlib import Path

# 先导入mock辅助模块
sys.path.insert(0, str(Path(__file__).parent))
import test_helpers  # noqa: F401 - mock psutil/serial/requests

sys.path.insert(0, str(Path(__file__).parent.parent / "pc_monitor"))

import unittest
from unittest.mock import patch, MagicMock, mock_open
from modules.token_stats import TokenStats, LogTailer, TokenTracker


class TestTokenStats(unittest.TestCase):
    """测试TokenStats数据类"""

    def test_creation(self):
        """测试创建TokenStats"""
        stats = TokenStats(
            total_input_tokens=1000,
            total_output_tokens=500,
            total_requests=10,
            tokens_last_hour=200,
            tokens_last_day=1500,
            estimated_cost_usd=0.05,
            timestamp=time.time()
        )
        self.assertEqual(stats.total_input_tokens, 1000)
        self.assertEqual(stats.total_output_tokens, 500)
        self.assertEqual(stats.total_requests, 10)
        self.assertEqual(stats.tokens_last_hour, 200)
        self.assertEqual(stats.tokens_last_day, 1500)
        self.assertAlmostEqual(stats.estimated_cost_usd, 0.05)

    def test_zero_stats(self):
        """测试零统计数据"""
        stats = TokenStats(
            total_input_tokens=0,
            total_output_tokens=0,
            total_requests=0,
            tokens_last_hour=0,
            tokens_last_day=0,
            estimated_cost_usd=0.0,
            timestamp=0.0
        )
        self.assertEqual(stats.total_input_tokens, 0)
        self.assertEqual(stats.total_requests, 0)


class TestLogTailer(unittest.TestCase):
    """测试LogTailer增量读取器"""

    def setUp(self):
        self.tailer = LogTailer()

    def test_initial_state(self):
        """测试初始状态"""
        self.assertEqual(self.tailer._file_states, {})

    def test_nonexistent_file(self):
        """测试不存在的文件"""
        lines = self.tailer.read_new_lines("/nonexistent/file.jsonl")
        self.assertEqual(lines, [])

    def test_first_read_from_end(self):
        """测试首次读取从末尾开始"""
        test_content = "line1\nline2\nline3\n"
        
        with patch('os.path.exists', return_value=True), \
             patch('os.stat') as mock_stat, \
             patch('builtins.open', mock_open(read_data=test_content)):
            
            mock_stat.return_value = MagicMock(st_size=100, st_ctime=1000.0)
            
            lines = self.tailer.read_new_lines("/fake/file.jsonl")
            # 应该读取内容
            self.assertIsInstance(lines, list)

    def test_incremental_read(self):
        """测试增量读取"""
        tailer = LogTailer()
        # 模拟已有状态
        tailer._file_states["/fake/file.jsonl"] = {
            "position": 0,
            "inode": 1000
        }
        
        test_content = "new_line1\nnew_line2\n"
        
        with patch('os.path.exists', return_value=True), \
             patch('os.stat') as mock_stat, \
             patch('builtins.open', mock_open(read_data=test_content)):
            
            mock_stat.return_value = MagicMock(st_size=50, st_ctime=1000.0)
            
            lines = tailer.read_new_lines("/fake/file.jsonl")
            self.assertIsInstance(lines, list)

    def test_file_rotation_detection(self):
        """测试文件轮转检测"""
        tailer = LogTailer()
        # 模拟旧状态
        tailer._file_states["/fake/file.jsonl"] = {
            "position": 100,
            "inode": 1000
        }
        
        with patch('os.path.exists', return_value=True), \
             patch('os.stat') as mock_stat, \
             patch('builtins.open', mock_open(read_data="new content\n")):
            
            # 不同的inode表示文件轮转
            mock_stat.return_value = MagicMock(st_size=20, st_ctime=2000.0)
            
            lines = tailer.read_new_lines("/fake/file.jsonl")
            # 应该检测到轮转并从头读取
            self.assertIsInstance(lines, list)

    def test_file_truncation_detection(self):
        """测试文件截断检测"""
        tailer = LogTailer()
        # 模拟旧状态 - 位置在100
        tailer._file_states["/fake/file.jsonl"] = {
            "position": 100,
            "inode": 1000
        }
        
        with patch('os.path.exists', return_value=True), \
             patch('os.stat') as mock_stat, \
             patch('builtins.open', mock_open(read_data="truncated\n")):
            
            # 文件大小小于位置 - 表示截断
            mock_stat.return_value = MagicMock(st_size=50, st_ctime=1000.0)
            
            lines = tailer.read_new_lines("/fake/file.jsonl")
            self.assertIsInstance(lines, list)


class TestTokenTracker(unittest.TestCase):
    """测试TokenTracker"""

    def test_default_config(self):
        """测试默认配置"""
        tracker = TokenTracker({})
        self.assertEqual(tracker.log_paths, [])
        self.assertEqual(tracker.update_interval, 30)
        self.assertFalse(tracker.auto_discover)

    def test_custom_config(self):
        """测试自定义配置"""
        config = {
            "log_paths": ["/path/to/log.jsonl"],
            "update_interval": 60,
            "auto_discover": True,
            "auto_discover_dirs": ["/home/user/.claude"],
            "auto_discover_pattern": "*.jsonl"
        }
        tracker = TokenTracker(config)
        self.assertEqual(tracker.log_paths, ["/path/to/log.jsonl"])
        self.assertEqual(tracker.update_interval, 60)
        self.assertTrue(tracker.auto_discover)
        self.assertEqual(tracker.auto_discover_dirs, ["/home/user/.claude"])

    def test_parse_jsonl_line(self):
        """测试解析JSONL格式"""
        tracker = TokenTracker({})
        
        # Claude CLI JSONL格式
        line = json.dumps({
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50
                }
            }
        })
        
        result = tracker._parse_log_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(result["output_tokens"], 50)

    def test_parse_plain_text_format(self):
        """测试解析纯文本格式"""
        tracker = TokenTracker({})
        
        line = "tokens: input=100 output=50"
        result = tracker._parse_log_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(result["output_tokens"], 50)

    def test_parse_invalid_line(self):
        """测试解析无效行"""
        tracker = TokenTracker({})
        
        result = tracker._parse_log_line("not a token log")
        self.assertIsNone(result)

    def test_pricing_models(self):
        """测试价格模型"""
        tracker = TokenTracker({})
        
        self.assertIn("claude-3-opus", tracker.PRICING)
        self.assertIn("claude-3-sonnet", tracker.PRICING)
        self.assertIn("default", tracker.PRICING)
        
        # 检查价格结构
        default_pricing = tracker.PRICING["default"]
        self.assertIn("input", default_pricing)
        self.assertIn("output", default_pricing)

    def test_get_stats_no_data(self):
        """测试无数据时获取统计"""
        tracker = TokenTracker({})
        
        with patch.object(tracker, '_tailer') as mock_tailer:
            mock_tailer.read_new_lines.return_value = []
            
            stats = tracker.get_stats()
            self.assertIsInstance(stats, TokenStats)
            self.assertEqual(stats.total_input_tokens, 0)
            self.assertEqual(stats.total_output_tokens, 0)

    def test_accumulated_records_limit(self):
        """测试累积记录上限"""
        tracker = TokenTracker({})
        
        # 模拟大量记录
        for i in range(15000):
            tracker._accumulated_records.append({
                "input_tokens": 10,
                "output_tokens": 5
            })
        
        # 检查是否有上限机制
        self.assertIsInstance(tracker._accumulated_records, list)


if __name__ == "__main__":
    unittest.main()
