"""
Token使用统计模块
解析日志文件，统计AI Agent的Token消耗
v2: LogTailer增量读取，避免全量扫描IO浪费
"""
import os
import re
import time
import json
import glob
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

# --- 常量 (token_stats) ---
DEFAULT_UPDATE_INTERVAL = 30          # 默认轮询间隔 (秒)
STATS_CACHE_TTL = 10                  # 统计缓存TTL (秒)
RECORD_RETENTION_HOURS = 86400        # 24小时 = 86400秒
HOUR_SECONDS = 3600                   # 1小时
DAY_SECONDS = 86400                   # 24小时
MAX_STATS_HISTORY = 1000              # stats_history 最大条数
MAX_ACCUMULATED_RECORDS = 10000       # 累计记录上限 (防内存泄漏)

logger = logging.getLogger(__name__)


@dataclass
class TokenStats:
    """Token统计数据"""
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    tokens_last_hour: int
    tokens_last_day: int
    estimated_cost_usd: float
    timestamp: float


class LogTailer:
    """增量日志读取器
    跟踪每个文件的读取位置，仅读取新增内容。
    支持文件轮转检测（inode变化或文件缩小）。
    """
    
    def __init__(self):
        # {file_path: {"position": int, "inode": int}}
        self._file_states: Dict[str, Dict] = {}
    
    def read_new_lines(self, file_path: str) -> List[str]:
        """读取文件新增行，跳过已读部分"""
        if not os.path.exists(file_path):
            return []
        
        stat = os.stat(file_path)
        current_size = stat.st_size
        # Windows无inode，用文件大小+修改时间模拟
        current_inode = int(stat.st_ctime * 1000)
        
        state = self._file_states.get(file_path)
        
        if state is None:
            # 首次读取：从末尾前10KB开始（避免冷启动全量扫描过久）
            start_pos = max(0, current_size - 10 * 1024)
            state = {"position": start_pos, "inode": current_inode}
            self._file_states[file_path] = state
        elif current_inode != state["inode"]:
            # 文件已轮转（inode变化），从头开始
            logger.info(f"文件轮转检测: {file_path}")
            state["position"] = 0
            state["inode"] = current_inode
        elif current_size < state["position"]:
            # 文件被截断
            logger.info(f"文件截断检测: {file_path}")
            state["position"] = 0
        
        if current_size <= state["position"]:
            return []
        
        lines = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(state["position"])
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
                state["position"] = f.tell()
            state["inode"] = current_inode
        except Exception as e:
            logger.warning(f"增量读取失败 {file_path}: {e}")
        
        return lines


class TokenTracker:
    """Token使用追踪器"""
    
    # 价格模型 (USD per 1M tokens)
    PRICING = {
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        "default": {"input": 3.0, "output": 15.0}
    }
    
    def __init__(self, config: dict):
        self.log_paths = config.get("log_paths", [])
        self.update_interval = config.get("update_interval", DEFAULT_UPDATE_INTERVAL)
        # JSONL自动发现配置
        self.auto_discover = config.get("auto_discover", False)
        self.auto_discover_dirs = config.get("auto_discover_dirs", [])
        self.auto_discover_pattern = config.get("auto_discover_pattern", "*.jsonl")
        self._stats_history = []
        self._cached_stats = None
        self._last_scan_time = 0
        self._tailer = LogTailer()
        # 累积的token记录（增量追加，不重复扫描）
        self._accumulated_records: List[Dict] = []
        # 自动发现的文件缓存
        self._discovered_files: List[str] = []
        self._discover_last_time: float = 0
        self._load_cache()
        
    def _load_cache(self):
        """加载缓存的统计数据"""
        cache_file = "token_cache.json"
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    self._stats_history = json.load(f)
            except Exception as e:
                logger.warning(f"加载缓存失败: {e}")
    
    def _discover_log_files(self) -> List[str]:
        """自动发现Claude CLI等AI工具的JSONL日志文件"""
        if not self.auto_discover:
            return []
        
        # 每60秒重新扫描一次，避免频繁IO
        now = time.time()
        if self._discovered_files and (now - self._discover_last_time) < 60:
            return self._discovered_files
        
        found = []
        for dir_pattern in self.auto_discover_dirs:
            expanded = os.path.expanduser(os.path.expandvars(dir_pattern))
            pattern = os.path.join(expanded, "**", self.auto_discover_pattern)
            matches = glob.glob(pattern, recursive=True)
            found.extend(matches)
        
        # 按修改时间降序，只保留最新的3个文件
        found.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
        self._discovered_files = found[:3]
        self._discover_last_time = now
        
        if self._discovered_files:
            logger.info(f"自动发现 {len(self._discovered_files)} 个JSONL文件")
        
        return self._discovered_files
    
    def _save_cache(self):
        """保存统计数据到缓存"""
        try:
            with open("token_cache.json", 'w') as f:
                json.dump(self._stats_history[-1000:], f)  # 保留最近1000条
        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")
    
    def _parse_log_line(self, line: str) -> Optional[Dict]:
        """解析日志行，提取Token使用信息（支持JSONL和纯文本）"""
        # 优先尝试JSONL格式（Claude CLI输出）
        try:
            obj = json.loads(line)
            msg = obj.get("message", {})
            usage = msg.get("usage", {})
            if usage and ("input_tokens" in usage or "output_tokens" in usage):
                return {
                    "input_tokens": int(usage.get("input_tokens", 0)),
                    "output_tokens": int(usage.get("output_tokens", 0))
                }
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass
        
        # fallback: 正则匹配纯文本格式
        patterns = [
            r'tokens?:\s*input[=:]\s*(\d+)\s*output[=:]\s*(\d+)',
            r'prompt_tokens?[=:]\s*(\d+).*?completion_tokens?[=:]\s*(\d+)',
            r'input_tokens[=:]\s*(\d+).*?output_tokens[=:]\s*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return {
                    "input_tokens": int(match.group(1)),
                    "output_tokens": int(match.group(2))
                }
        return None
    
    def _scan_log_files(self) -> list:
        """增量扫描日志文件，仅读取新增内容（v2: LogTailer + 自动发现）"""
        now = time.time()
        
        # 合并手动配置路径和自动发现的文件
        all_files = []
        for log_path in self.log_paths:
            if not os.path.exists(log_path):
                continue
            if os.path.isfile(log_path):
                all_files.append(log_path)
            else:
                all_files.extend(str(p) for p in Path(log_path).glob('*') 
                                 if p.suffix in ('.log', '.txt', '.json', '.jsonl'))
        
        # 追加自动发现的JSONL文件
        discovered = self._discover_log_files()
        for df in discovered:
            if df not in all_files:
                all_files.append(df)
        
        for file_path in all_files:
            new_lines = self._tailer.read_new_lines(file_path)
            for line in new_lines:
                tokens = self._parse_log_line(line)
                if tokens:
                    tokens["timestamp"] = now
                    self._accumulated_records.append(tokens)
        
        # 滑动窗口：仅保留最近24小时数据，防止长期运行内存泄漏
        cutoff_time = now - RECORD_RETENTION_HOURS
        self._accumulated_records = [
            r for r in self._accumulated_records if r.get("timestamp", 0) > cutoff_time
        ]
        
        return self._accumulated_records
    
    def get_stats(self) -> TokenStats:
        """获取Token统计（增量更新，避免全量IO扫描）"""
        now = time.time()
        # 10秒内返回缓存
        if (self._cached_stats and 
            now - self._last_scan_time < STATS_CACHE_TTL and 
            self._last_scan_time > 0):
            return self._cached_stats

        self._scan_log_files()
        self._last_scan_time = now
        records = self._accumulated_records
        
        total_input = sum(r["input_tokens"] for r in records)
        total_output = sum(r["output_tokens"] for r in records)
        total_requests = len(records)
        
        # 计算最近1小时和24小时的使用量
        hour_ago = now - HOUR_SECONDS
        day_ago = now - DAY_SECONDS
        
        tokens_hour = sum(
            r["input_tokens"] + r["output_tokens"] 
            for r in records if r.get("timestamp", 0) > hour_ago
        )
        tokens_day = sum(
            r["input_tokens"] + r["output_tokens"] 
            for r in records if r.get("timestamp", 0) > day_ago
        )
        
        # 估算费用 (使用Sonnet价格)
        pricing = self.PRICING["default"]
        cost = (total_input * pricing["input"] + total_output * pricing["output"]) / 1_000_000
        
        stats = TokenStats(
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_requests=total_requests,
            tokens_last_hour=tokens_hour,
            tokens_last_day=tokens_day,
            estimated_cost_usd=cost,
            timestamp=now
        )
        
        self._stats_history.append({
            "timestamp": now,
            "total_tokens": total_input + total_output,
            "requests": total_requests
        })
        self._stats_history = self._stats_history[-MAX_STATS_HISTORY:]  # 限制内存列表大小，防止长期运行内存泄漏
        self._save_cache()
        
        self._cached_stats = stats
        return stats
