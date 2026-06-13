"""
AI Agent状态监控模块
检测本地Agent进程状态（工作中/空闲/需授权）

v2: 增加JSONL文件监控，精确检测auth pending状态

状态判断逻辑：
- CPU > 30%: WORKING（工作中）
- 3% < CPU <= 30%: AUTHORIZING（等待授权/输入）
- CPU <= 3% 连续6次(~12s): IDLE（空闲）
- 进程不存在: OFFLINE（离线）

JSONL检测增强：
- 读取Claude项目目录下的JSONL文件
- 检测permission_request、AskUser等授权请求
- 只读取文件末尾8KB避免大文件性能问题
"""
import os
import glob
import json
import time
import logging
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from enum import Enum

import psutil
from psutil import NoSuchProcess, AccessDenied

logger = logging.getLogger(__name__)

# 常量定义
DEFAULT_CHECK_INTERVAL: int = 2  # 秒
DEFAULT_PROCESS_NAMES: List[str] = ["claudecode", "codex"]
DEFAULT_AUTH_JSONL_DIRS: List[str] = ["~/.claude/projects"]
DEFAULT_AUTH_JSONL_MAX_LINES: int = 30
JSONL_READ_BUFFER_SIZE: int = 8192  # 字节

# CPU阈值常量
CPU_THRESHOLD_WORKING: float = 30.0
CPU_THRESHOLD_AUTHORIZING: float = 3.0
IDLE_CONFIRM_COUNT: int = 6  # 连续低CPU次数确认空闲（约12秒）

# CPU滑动窗口大小
CPU_HISTORY_WINDOW: int = 5


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
    """AI Agent进程监控器
    
    通过进程CPU使用率和JSONL日志文件检测Agent工作状态。
    使用进程缓存避免重复查找，支持滑动窗口平滑CPU采样。
    
    Attributes:
        process_names: 要监控的进程名称列表
        check_interval: 检查间隔（秒）
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """初始化Agent监控器
        
        Args:
            config: 配置字典，包含process_names, check_interval, auth_jsonl_dirs等
        """
        self.process_names: List[str] = config.get("process_names", DEFAULT_PROCESS_NAMES)
        self.check_interval: int = config.get("check_interval", DEFAULT_CHECK_INTERVAL)
        self._running: bool = False
        self._current_state: Optional[AgentState] = None
        self._cached_proc: Optional[psutil.Process] = None
        self._cpu_history: List[float] = []
        self._idle_streak: int = 0
        
        # JSONL auth检测配置
        default_dirs = [os.path.expanduser(d) for d in DEFAULT_AUTH_JSONL_DIRS]
        self._auth_jsonl_dirs: List[str] = config.get("auth_jsonl_dirs", default_dirs)
        self._auth_jsonl_max_lines: int = config.get("auth_jsonl_max_lines", DEFAULT_AUTH_JSONL_MAX_LINES)
        self._jsonl_auth_detected: bool = False
        
    def _find_agent_process(self) -> Optional[psutil.Process]:
        """查找Agent进程
        
        遍历系统进程列表，匹配进程名或命令行参数。
        
        Returns:
            匹配的psutil.Process对象，未找到返回None
        """
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_name: str = (proc.info['name'] or '').lower()
                cmdline: str = ' '.join(proc.info['cmdline'] or []).lower()
                
                for target in self.process_names:
                    if target in proc_name or target in cmdline:
                        return proc
            except (NoSuchProcess, AccessDenied):
                continue
        return None
    
    def _analyze_cpu_pattern(self, proc: psutil.Process) -> AgentStatus:
        """通过CPU使用模式判断Agent状态（非阻塞）
        
        使用滑动窗口平滑CPU采样，避免瞬时波动导致误判。
        
        Args:
            proc: 要监控的进程对象
            
        Returns:
            AgentStatus枚举值
        """
        try:
            # 非阻塞调用：首次返回0，后续返回自上次调用以来的CPU%
            cpu_percent: float = proc.cpu_percent(interval=0)

            # 维护滑动窗口
            self._cpu_history.append(cpu_percent)
            if len(self._cpu_history) > CPU_HISTORY_WINDOW:
                self._cpu_history.pop(0)

            avg_cpu: float = sum(self._cpu_history) / len(self._cpu_history)

            if avg_cpu > CPU_THRESHOLD_WORKING:
                self._idle_streak = 0
                return AgentStatus.WORKING
            elif avg_cpu > CPU_THRESHOLD_AUTHORIZING:
                self._idle_streak = 0
                return AgentStatus.AUTHORIZING  # 低CPU=等待输入/授权
            else:
                self._idle_streak += 1
                # 连续多次低CPU才确认IDLE，避免误判
                if self._idle_streak >= IDLE_CONFIRM_COUNT:
                    return AgentStatus.IDLE
                else:
                    return AgentStatus.AUTHORIZING

        except (NoSuchProcess, AccessDenied):
            return AgentStatus.OFFLINE
    
    def _check_auth_jsonl(self) -> bool:
        """检查JSONL文件中是否有pending auth请求
        
        扫描Claude项目目录下的JSONL日志文件，检测授权请求。
        只读取文件末尾8KB避免大文件性能问题。
        
        Returns:
            True表示检测到授权请求
        """
        for base_dir in self._auth_jsonl_dirs:
            expanded_dir: str = os.path.expanduser(base_dir)
            if not os.path.isdir(expanded_dir):
                continue
            
            # 找到最新的JSONL文件
            jsonl_files: List[str] = glob.glob(
                os.path.join(expanded_dir, "**", "*.jsonl"), 
                recursive=True
            )
            if not jsonl_files:
                continue
            
            # 按修改时间排序，只检查最新的
            jsonl_files.sort(key=os.path.getmtime, reverse=True)
            latest: str = jsonl_files[0]
            
            try:
                # 优化：只读取文件末尾，避免大文件全量读入
                with open(latest, 'rb') as f:
                    try:
                        f.seek(-JSONL_READ_BUFFER_SIZE, os.SEEK_END)
                    except OSError:
                        f.seek(0)  # 文件小于缓冲区则从头读取
                    content: str = f.read().decode('utf-8', errors='ignore')
                    lines: List[str] = content.splitlines()
                
                # 只检查最后N行
                for line in lines[-self._auth_jsonl_max_lines:]:
                    if self._parse_jsonl_line(line):
                        self._jsonl_auth_detected = True
                        return True
                        
            except (IOError, OSError) as e:
                logger.debug(f"读取JSONL失败 {latest}: {e}")
                continue
        
        self._jsonl_auth_detected = False
        return False
    
    def _parse_jsonl_line(self, line: str) -> bool:
        """解析单行JSONL，检测授权请求
        
        Args:
            line: JSONL格式的单行文本
            
        Returns:
            True表示检测到授权请求
        """
        try:
            obj: Dict[str, Any] = json.loads(line.strip())
            msg: Dict[str, Any] = obj.get("message", {})
            
            # 检测permission request（pending状态）
            if msg.get("type") == "permission_request":
                return True
            
            content: Any = msg.get("content", "")
            if isinstance(content, str) and "permission" in content.lower() and "pending" in content.lower():
                return True
            
            # 检测tool_use AskUser无对应tool_result
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tool_name: str = item.get("name", "")
                        if "AskUser" in tool_name or "ask" in tool_name.lower():
                            return True
                            
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
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

        proc: Optional[psutil.Process] = self._cached_proc
        
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
                cpu_percent: float = proc.cpu_percent(interval=0)
                memory_info: Any = proc.memory_info()
                create_time: float = proc.create_time()
                
            status: AgentStatus = self._analyze_cpu_pattern(proc)
            
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
