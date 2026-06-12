"""
AI Agent状态监控模块
检测本地Agent进程状态（工作中/空闲/需授权）
v2: 增加JSONL文件监控，精确检测auth pending状态
"""
import psutil
import os
import glob
import json
import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent状态枚举"""
    IDLE = "idle"           # 空闲
    WORKING = "working"     # 工作中
    AUTHORIZING = "auth"    # 等待授权
    OFFLINE = "offline"     # 离线


@dataclass
class AgentState:
    """Agent状态数据"""
    status: AgentStatus
    process_name: str
    pid: Optional[int]
    cpu_percent: float
    memory_mb: float
    uptime_seconds: float
    timestamp: float


class AgentMonitor:
    """AI Agent进程监控器"""
    
    def __init__(self, config: dict):
        self.process_names = config.get("process_names", ["claudecode", "codex"])
        self.check_interval = config.get("check_interval", 2)
        self._running = False
        self._current_state = None
        self._cached_proc = None  # 缓存进程对象，避免cpu_percent永远返回0
        self._cpu_history = []
        self._idle_streak = 0
        # JSONL auth检测配置
        self._auth_jsonl_dirs = config.get("auth_jsonl_dirs", [
            os.path.expanduser("~/.claude/projects")
        ])
        self._auth_jsonl_max_lines = config.get("auth_jsonl_max_lines", 30)
        self._jsonl_auth_detected = False
        
    def _find_agent_process(self) -> Optional[psutil.Process]:
        """查找Agent进程"""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_name = proc.info['name'].lower()
                cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                
                for target in self.process_names:
                    if target in proc_name or target in cmdline:
                        return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None
    
    def _analyze_cpu_pattern(self, proc: psutil.Process) -> AgentStatus:
        """通过CPU使用模式判断Agent状态（非阻塞）"""
        try:
            # 非阻塞调用：首次返回0，后续返回自上次调用以来的CPU%
            cpu_percent = proc.cpu_percent(interval=0)
            now = time.time()

            # 维护滑动窗口（最近5个采样点）
            self._cpu_history.append(cpu_percent)
            if len(self._cpu_history) > 5:
                self._cpu_history.pop(0)

            avg_cpu = sum(self._cpu_history) / len(self._cpu_history)

            if avg_cpu > 30:
                self._idle_streak = 0
                return AgentStatus.WORKING
            elif avg_cpu > 3:
                self._idle_streak = 0
                return AgentStatus.AUTHORIZING  # 低CPU=等待输入/授权
            else:
                self._idle_streak += 1
                # 连续6次低CPU（~12秒）才确认IDLE，避免误判
                if self._idle_streak >= 6:
                    return AgentStatus.IDLE
                else:
                    return AgentStatus.AUTHORIZING

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return AgentStatus.OFFLINE
    
    def _check_auth_jsonl(self) -> bool:
        """检查JSONL文件中是否有pending auth请求"""
        for base_dir in self._auth_jsonl_dirs:
            base_dir = os.path.expanduser(base_dir)
            if not os.path.isdir(base_dir):
                continue
            # 找到最新的JSONL文件
            jsonl_files = glob.glob(os.path.join(base_dir, "**", "*.jsonl"), recursive=True)
            if not jsonl_files:
                continue
            # 按修改时间排序，只检查最新的
            jsonl_files.sort(key=os.path.getmtime, reverse=True)
            latest = jsonl_files[0]
            try:
                with open(latest, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                # 只检查最后N行
                for line in lines[-self._auth_jsonl_max_lines:]:
                    try:
                        obj = json.loads(line.strip())
                        msg = obj.get("message", {})
                        # 检测permission request（pending状态）
                        if msg.get("type") == "permission_request":
                            self._jsonl_auth_detected = True
                            return True
                        content = msg.get("content", "")
                        if isinstance(content, str) and "permission" in content.lower() and "pending" in content.lower():
                            self._jsonl_auth_detected = True
                            return True
                        # 检测tool_use AskUser无对应tool_result
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "tool_use":
                                    tool_name = item.get("name", "")
                                    if "AskUser" in tool_name or "ask" in tool_name.lower():
                                        self._jsonl_auth_detected = True
                                        return True
                    except (json.JSONDecodeError, AttributeError):
                        continue
            except (IOError, OSError) as e:
                logger.debug(f"读取JSONL失败 {latest}: {e}")
                continue
        self._jsonl_auth_detected = False
        return False
    
    def get_state(self) -> AgentState:
        """获取当前Agent状态"""
        # 1. 验证缓存的进程是否依然存活
        if self._cached_proc:
            try:
                if not self._cached_proc.is_running():
                    self._cached_proc = None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._cached_proc = None

        # 2. 如果无缓存，则重新查找
        if self._cached_proc is None:
            self._cached_proc = self._find_agent_process()
            self._cpu_history = []
            self._idle_streak = 0
            if self._cached_proc:
                # 预热首次采样（丢弃结果）
                self._cached_proc.cpu_percent(interval=None)

        proc = self._cached_proc
        
        if proc is None:
            return AgentState(
                status=AgentStatus.OFFLINE,
                process_name="none",
                pid=None,
                cpu_percent=0.0,
                memory_mb=0.0,
                uptime_seconds=0.0,
                timestamp=time.time()
            )
        
        try:
            with proc.oneshot():
                cpu_percent = proc.cpu_percent(interval=0)
                memory_info = proc.memory_info()
                create_time = proc.create_time()
                
            status = self._analyze_cpu_pattern(proc)
            
            # JSONL auth检测优先：如果CPU判定为AUTHORIZING，用JSONL精确确认
            if status == AgentStatus.AUTHORIZING:
                if self._check_auth_jsonl():
                    logger.debug("Auth确认: JSONL检测到pending permission")
                # JSONL未确认auth但CPU低→保持AUTHORIZING（可能是等待输入）
            elif status == AgentStatus.WORKING:
                # 工作中也轻量检查JSONL（防止CPU刚升高但auth刚弹出的情况）
                if self._check_auth_jsonl():
                    status = AgentStatus.AUTHORIZING
            
            return AgentState(
                status=status,
                process_name=proc.name(),
                pid=proc.pid,
                cpu_percent=cpu_percent,
                memory_mb=memory_info.rss / 1024 / 1024,
                uptime_seconds=time.time() - create_time,
                timestamp=time.time()
            )
            
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"获取进程信息失败: {e}")
            self._cached_proc = None  # 进程异常，清除缓存
            return AgentState(
                status=AgentStatus.OFFLINE,
                process_name="unknown",
                pid=None,
                cpu_percent=0.0,
                memory_mb=0.0,
                uptime_seconds=0.0,
                timestamp=time.time()
            )
    
    def start_monitoring(self, callback=None):
        """启动持续监控"""
        self._running = True
        logger.info("Agent监控已启动")
        
        while self._running:
            state = self.get_state()
            self._current_state = state
            
            if callback:
                callback(state)
                
            time.sleep(self.check_interval)
    
    def stop_monitoring(self):
        """停止监控"""
        self._running = False
        logger.info("Agent监控已停止")
