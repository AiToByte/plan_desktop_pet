"""
Token使用统计模块
解析日志文件，统计AI Agent的Token消耗
"""
import os
import re
import time
import json
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

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
        self.update_interval = config.get("update_interval", 30)
        self._stats_history = []
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
    
    def _save_cache(self):
        """保存统计数据到缓存"""
        try:
            with open("token_cache.json", 'w') as f:
                json.dump(self._stats_history[-1000:], f)  # 保留最近1000条
        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")
    
    def _parse_log_line(self, line: str) -> Optional[Dict]:
        """解析日志行，提取Token使用信息"""
        # 匹配常见的Token日志格式
        patterns = [
            # 格式: "tokens: input=1234 output=5678"
            r'tokens?:\s*input[=:]\s*(\d+)\s*output[=:]\s*(\d+)',
            # 格式: "prompt_tokens=1234, completion_tokens=5678"
            r'prompt_tokens?[=:]\s*(\d+).*?completion_tokens?[=:]\s*(\d+)',
            # 格式: "usage: {input_tokens: 1234, output_tokens: 5678}"
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
        """扫描日志文件，收集Token记录"""
        records = []
        
        for log_path in self.log_paths:
            if not os.path.exists(log_path):
                continue
                
            if os.path.isfile(log_path):
                files = [log_path]
            else:
                files = [
                    os.path.join(log_path, f) 
                    for f in os.listdir(log_path) 
                    if f.endswith(('.log', '.txt', '.json'))
                ]
            
            for file_path in files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            tokens = self._parse_log_line(line)
                            if tokens:
                                tokens["timestamp"] = os.path.getmtime(file_path)
                                records.append(tokens)
                except Exception as e:
                    logger.warning(f"读取文件失败 {file_path}: {e}")
        
        return records
    
    def get_stats(self) -> TokenStats:
        """获取Token统计（带缓存，避免频繁全量扫描）"""
        now = time.time()
        # 10秒内返回缓存
        if (self._cached_stats and 
            now - self._last_scan_time < 10 and 
            self._last_scan_time > 0):
            return self._cached_stats

        records = self._scan_log_files()
        self._last_scan_time = now
        now = time.time()
        
        total_input = sum(r["input_tokens"] for r in records)
        total_output = sum(r["output_tokens"] for r in records)
        total_requests = len(records)
        
        # 计算最近1小时和24小时的使用量
        hour_ago = now - 3600
        day_ago = now - 86400
        
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
        self._save_cache()
        
        self._cached_stats = stats
        return stats
