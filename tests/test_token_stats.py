"""
Token统计模块测试
覆盖: TokenStats, LogTailer, TokenTracker
重点: 增量读取、文件轮转检测、JSONL解析、缓存TTL、费用计算
"""
import json
import os
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, call

import pytest

from modules.token_stats import (
    TokenStats,
    LogTailer,
    TokenTracker,
    STATS_CACHE_TTL,
    HOUR_SECONDS,
    DAY_SECONDS,
    RECORD_RETENTION_HOURS,
    MAX_STATS_HISTORY,
    MAX_ACCUMULATED_RECORDS,
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_jsonl_lines():
    """Claude CLI JSONL格式日志行"""
    return [
        json.dumps({"message": {"usage": {"input_tokens": 100, "output_tokens": 50}}}),
        json.dumps({"message": {"usage": {"input_tokens": 200, "output_tokens": 80}}}),
        json.dumps({"message": {"no_usage": True}}),  # 无usage字段
        "not json at all",  # 无效行
        json.dumps({"message": {"usage": {"input_tokens": 500, "output_tokens": 200}}}),
    ]


@pytest.fixture
def tmp_log_file(tmp_path):
    """创建临时日志文件"""
    log_file = tmp_path / "test.jsonl"
    return str(log_file)


@pytest.fixture
def tracker_config(tmp_path):
    """TokenTracker基础配置"""
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    return {
        "log_paths": [log_dir],
        "update_interval": 10,
        "auto_discover": False,
    }


@pytest.fixture
def tracker(tracker_config):
    """TokenTracker实例（禁用缓存文件）"""
    with patch("modules.token_stats.os.path.exists", return_value=False):
        return TokenTracker(tracker_config)


# ── TestTokenStats ────────────────────────────────────────

class TestTokenStats:
    def test_construction(self):
        """TokenStats基本构造"""
        stats = TokenStats(
            total_input_tokens=1000,
            total_output_tokens=500,
            total_requests=10,
            tokens_last_hour=200,
            tokens_last_day=800,
            estimated_cost_usd=0.05,
            timestamp=time.time(),
        )
        assert stats.total_input_tokens == 1000
        assert stats.total_output_tokens == 500
        assert stats.total_requests == 10
        assert stats.tokens_last_hour == 200
        assert stats.tokens_last_day == 800
        assert stats.estimated_cost_usd == 0.05
        assert stats.timestamp > 0

    def test_dataclass_equality(self):
        """dataclass相等性"""
        now = time.time()
        s1 = TokenStats(100, 50, 5, 20, 80, 0.01, now)
        s2 = TokenStats(100, 50, 5, 20, 80, 0.01, now)
        assert s1 == s2

    def test_zero_usage(self):
        """零使用量统计"""
        stats = TokenStats(0, 0, 0, 0, 0, 0.0, time.time())
        assert stats.total_input_tokens == 0
        assert stats.estimated_cost_usd == 0.0


# ── TestLogTailer ─────────────────────────────────────────

class TestLogTailer:
    def test_read_new_lines_first_read(self, tmp_path):
        """首次读取：从文件末尾前10KB开始"""
        log_file = tmp_path / "test.log"
        # 写入一些数据
        content = "line1\nline2\nline3\n"
        log_file.write_text(content)
        
        tailer = LogTailer()
        lines = tailer.read_new_lines(str(log_file))
        
        # 首次读取应该读到内容（文件小于10KB，从头开始）
        assert len(lines) == 3
        assert lines[0] == "line1"
        assert lines[-1] == "line3"

    def test_read_new_lines_incremental(self, tmp_path):
        """增量读取：只读取新增内容"""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\n")
        
        tailer = LogTailer()
        # 第一次读取
        lines1 = tailer.read_new_lines(str(log_file))
        assert len(lines1) == 2
        
        # 追加内容
        with open(log_file, 'a') as f:
            f.write("line3\nline4\n")
        
        # 第二次读取应只返回新增行
        lines2 = tailer.read_new_lines(str(log_file))
        assert len(lines2) == 2
        assert lines2[0] == "line3"
        assert lines2[1] == "line4"

    def test_read_no_new_content(self, tmp_path):
        """无新内容时返回空列表"""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\n")
        
        tailer = LogTailer()
        tailer.read_new_lines(str(log_file))
        
        # 再次读取无新内容
        lines = tailer.read_new_lines(str(log_file))
        assert lines == []

    def test_read_nonexistent_file(self):
        """读取不存在的文件返回空列表"""
        tailer = LogTailer()
        lines = tailer.read_new_lines("/nonexistent/file.log")
        assert lines == []

    def test_file_truncation_detection(self, tmp_path):
        """文件被截断时重新从头读取"""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\nline3\n")
        
        tailer = LogTailer()
        tailer.read_new_lines(str(log_file))
        
        # 截断文件（模拟文件被清空重写）
        log_file.write_text("new_line1\n")
        
        lines = tailer.read_new_lines(str(log_file))
        assert len(lines) == 1
        assert lines[0] == "new_line1"

    def test_empty_lines_skipped(self, tmp_path):
        """空行被跳过"""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\n\n\nline2\n\n")
        
        tailer = LogTailer()
        lines = tailer.read_new_lines(str(log_file))
        assert lines == ["line1", "line2"]

    def test_file_rotation_detection(self, tmp_path):
        """文件轮转检测（inode变化模拟）"""
        log_file = tmp_path / "test.log"
        log_file.write_text("old_content\n")
        
        tailer = LogTailer()
        tailer.read_new_lines(str(log_file))
        
        # 模拟inode变化（修改ctime）- 通过修改文件状态
        # 直接篡改内部状态模拟inode变化
        file_path = str(log_file)
        old_inode = tailer._file_states[file_path]["inode"]
        tailer._file_states[file_path]["inode"] = old_inode + 1
        
        # 追加内容并读取
        log_file.write_text("rotated_content\n")
        lines = tailer.read_new_lines(str(log_file))
        # 轮转后从头读取
        assert len(lines) >= 1

    def test_first_read_large_file(self, tmp_path):
        """大文件首次读取从末尾10KB开始"""
        log_file = tmp_path / "big.log"
        # 写入超过10KB的数据
        big_content = "x" * 50 + "\n"  # 每行51字节
        with open(log_file, 'w') as f:
            for i in range(300):  # ~15KB
                f.write(f"line_{i:04d}_" + "x" * 35 + "\n")
        
        tailer = LogTailer()
        lines = tailer.read_new_lines(str(log_file))
        
        # 不应读取全部300行，只从10KB偏移处开始
        assert len(lines) < 300
        assert len(lines) > 0


# ── TestParseLogLine ──────────────────────────────────────

class TestParseLogLine:
    def test_parse_jsonl_format(self, tracker):
        """JSONL格式解析"""
        line = json.dumps({"message": {"usage": {"input_tokens": 100, "output_tokens": 50}}})
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

    def test_parse_jsonl_zero_tokens(self, tracker):
        """JSONL零token"""
        line = json.dumps({"message": {"usage": {"input_tokens": 0, "output_tokens": 0}}})
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 0

    def test_parse_jsonl_missing_usage(self, tracker):
        """JSONL无usage字段返回None"""
        line = json.dumps({"message": {"content": "hello"}})
        result = tracker._parse_log_line(line)
        assert result is None

    def test_parse_regex_format(self, tracker):
        """纯文本正则格式解析"""
        line = "tokens: input=1000 output=500"
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 500

    def test_parse_regex_prompt_completion(self, tracker):
        """prompt/completion格式"""
        line = "prompt_tokens=2000 completion_tokens=800"
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 2000
        assert result["output_tokens"] == 800

    def test_parse_regex_input_output(self, tracker):
        """input_tokens/output_tokens格式"""
        line = "input_tokens=300 some text output_tokens=150"
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 300
        assert result["output_tokens"] == 150

    def test_parse_invalid_line(self, tracker):
        """无效行返回None"""
        assert tracker._parse_log_line("") is None
        assert tracker._parse_log_line("random text") is None
        assert tracker._parse_log_line('{"no": "usage"}') is None

    def test_parse_jsonl_partial_usage(self, tracker):
        """JSONL只有input_tokens"""
        line = json.dumps({"message": {"usage": {"input_tokens": 100}}})
        result = tracker._parse_log_line(line)
        assert result is not None
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 0


# ── TestGetStats ──────────────────────────────────────────

class TestGetStats:
    def test_get_stats_empty(self, tracker):
        """无日志数据时返回零统计"""
        stats = tracker.get_stats()
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.total_requests == 0

    def test_get_stats_from_log(self, tracker, tmp_path):
        """从日志文件读取统计"""
        # 写入测试日志到tracker的log_paths
        log_dir = tracker.log_paths[0]
        log_file = os.path.join(log_dir, "test.jsonl")
        lines = [
            json.dumps({"message": {"usage": {"input_tokens": 100, "output_tokens": 50}}}),
            json.dumps({"message": {"usage": {"input_tokens": 200, "output_tokens": 80}}}),
        ]
        with open(log_file, 'w') as f:
            f.write("\n".join(lines) + "\n")
        
        stats = tracker.get_stats()
        assert stats.total_input_tokens == 300
        assert stats.total_output_tokens == 130
        assert stats.total_requests == 2

    def test_cache_ttl_returns_cached(self, tracker, tmp_path):
        """10秒内返回缓存结果"""
        log_dir = tracker.log_paths[0]
        log_file = os.path.join(log_dir, "test.jsonl")
        with open(log_file, 'w') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 100, "output_tokens": 50}}}) + "\n")
        
        stats1 = tracker.get_stats()
        assert stats1.total_input_tokens == 100
        
        # 追加更多数据
        with open(log_file, 'a') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 500, "output_tokens": 200}}}) + "\n")
        
        # 仍在缓存期内，应返回旧数据
        stats2 = tracker.get_stats()
        assert stats2.total_input_tokens == 100  # 缓存值

    def test_cache_expired_reloads(self, tracker, tmp_path):
        """缓存过期后重新加载"""
        log_dir = tracker.log_paths[0]
        log_file = os.path.join(log_dir, "test.jsonl")
        with open(log_file, 'w') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 100, "output_tokens": 50}}}) + "\n")
        
        tracker.get_stats()
        
        # 模拟缓存过期
        tracker._last_scan_time = time.time() - STATS_CACHE_TTL - 1
        
        # 追加数据
        with open(log_file, 'a') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 500, "output_tokens": 200}}}) + "\n")
        
        stats = tracker.get_stats()
        # 缓存过期后应读到新增数据（LogTailer增量）
        assert stats.total_input_tokens == 600
        assert stats.total_output_tokens == 250

    def test_cost_calculation(self, tracker, tmp_path):
        """费用计算使用default定价"""
        log_dir = tracker.log_paths[0]
        log_file = os.path.join(log_dir, "test.jsonl")
        with open(log_file, 'w') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}}) + "\n")
        
        stats = tracker.get_stats()
        # default pricing: input=3.0, output=15.0 per 1M tokens
        expected_cost = (1_000_000 * 3.0 + 1_000_000 * 15.0) / 1_000_000
        assert abs(stats.estimated_cost_usd - expected_cost) < 0.01

    def test_stats_history_limited(self, tracker, tmp_path):
        """stats_history限制在MAX_STATS_HISTORY条"""
        log_dir = tracker.log_paths[0]
        log_file = os.path.join(log_dir, "test.jsonl")
        with open(log_file, 'w') as f:
            f.write(json.dumps({"message": {"usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
        
        # 多次调用get_stats（每次过期缓存）
        for _ in range(MAX_STATS_HISTORY + 10):
            tracker._last_scan_time = 0  # 强制刷新
            tracker.get_stats()
        
        assert len(tracker._stats_history) <= MAX_STATS_HISTORY


# ── TestDiscoverLogFiles ──────────────────────────────────

class TestDiscoverLogFiles:
    def test_disabled_returns_empty(self, tracker):
        """auto_discover=False时返回空"""
        result = tracker._discover_log_files()
        assert result == []

    def test_discover_finds_jsonl(self, tmp_path):
        """自动发现JSONL文件"""
        log_dir = tmp_path / "discover"
        log_dir.mkdir()
        (log_dir / "session1.jsonl").write_text("{}")
        (log_dir / "session2.jsonl").write_text("{}")
        (log_dir / "ignore.log").write_text("text")
        
        config = {
            "log_paths": [],
            "auto_discover": True,
            "auto_discover_dirs": [str(log_dir)],
            "auto_discover_pattern": "*.jsonl",
        }
        with patch("modules.token_stats.os.path.exists", return_value=False):
            t = TokenTracker(config)
        
        files = t._discover_log_files()
        assert len(files) == 2
        assert all(f.endswith(".jsonl") for f in files)

    def test_discover_caches_results(self, tmp_path):
        """自动发现结果缓存60秒"""
        log_dir = tmp_path / "discover"
        log_dir.mkdir()
        (log_dir / "test.jsonl").write_text("{}")
        
        config = {
            "log_paths": [],
            "auto_discover": True,
            "auto_discover_dirs": [str(log_dir)],
        }
        with patch("modules.token_stats.os.path.exists", return_value=False):
            t = TokenTracker(config)
        
        files1 = t._discover_log_files()
        # 添加新文件
        (log_dir / "test2.jsonl").write_text("{}")
        
        # 缓存期内不会发现新文件
        files2 = t._discover_log_files()
        assert len(files2) == len(files1)

    def test_discover_limits_to_3(self, tmp_path):
        """最多保留3个最新文件"""
        log_dir = tmp_path / "discover"
        log_dir.mkdir()
        for i in range(5):
            f = log_dir / f"session{i}.jsonl"
            f.write_text("{}")
            # 确保不同修改时间
            os.utime(str(f), (i * 100, i * 100))
        
        config = {
            "log_paths": [],
            "auto_discover": True,
            "auto_discover_dirs": [str(log_dir)],
        }
        with patch("modules.token_stats.os.path.exists", return_value=False):
            t = TokenTracker(config)
        
        files = t._discover_log_files()
        assert len(files) == 3


# ── TestScanLogFiles ──────────────────────────────────────

class TestScanLogFiles:
    def test_scan_reads_log_directory(self, tracker, tmp_path):
        """扫描目录下所有日志文件"""
        log_dir = tracker.log_paths[0]
        for i in range(3):
            f = os.path.join(log_dir, f"test{i}.jsonl")
            with open(f, 'w') as fh:
                fh.write(json.dumps({"message": {"usage": {"input_tokens": 10 * i, "output_tokens": 5 * i}}}) + "\n")
        
        records = tracker._scan_log_files()
        assert len(records) == 3

    def test_scan_skips_nonexistent_paths(self):
        """不存在的log_path被跳过"""
        config = {"log_paths": ["/nonexistent/path"], "auto_discover": False}
        with patch("modules.token_stats.os.path.exists", return_value=False):
            t = TokenTracker(config)
        records = t._scan_log_files()
        assert records == []

    def test_accumulated_records_window(self, tracker):
        """累积记录按时间窗口清理"""
        now = time.time()
        # 手动注入旧记录
        tracker._accumulated_records = [
            {"input_tokens": 100, "output_tokens": 50, "timestamp": now - RECORD_RETENTION_HOURS - 1},
            {"input_tokens": 200, "output_tokens": 80, "timestamp": now},
        ]
        
        # 触发扫描（无实际文件，只清理旧记录）
        records = tracker._scan_log_files()
        # 旧记录应被清理
        assert len(records) == 1
        assert records[0]["input_tokens"] == 200


# ── TestPricing ───────────────────────────────────────────

class TestPricing:
    def test_pricing_models_exist(self):
        """定价模型完整"""
        assert "claude-3-opus" in TokenTracker.PRICING
        assert "claude-3-sonnet" in TokenTracker.PRICING
        assert "claude-3-haiku" in TokenTracker.PRICING
        assert "default" in TokenTracker.PRICING

    def test_pricing_structure(self):
        """每个定价模型有input/output"""
        for model, prices in TokenTracker.PRICING.items():
            assert "input" in prices, f"{model} missing 'input'"
            assert "output" in prices, f"{model} missing 'output'"
            assert prices["input"] > 0, f"{model} input price must be positive"
            assert prices["output"] > 0, f"{model} output price must be positive"
