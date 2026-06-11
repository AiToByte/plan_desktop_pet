"""
AI Agent状态监控模块
检测本地Agent进程状态（工作中/空闲/需授权）
"""
import psutil
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
        self._last_cpu_time = 0
        self._cpu_history = []
        self._idle_streak = 0
        
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
    
    def __init_cpu(self):
        """初始化非阻塞CPU采样（首次调用需预热）"""
        self._last_cpu_time = 0
        self._cpu_history = []  # 最近N次CPU采样
        self._idle_streak = 0   # 连续低CPU计数

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
    
    def get_state(self) -> AgentState:
        """获取当前Agent状态"""
        proc = self._find_agent_process()
        
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
                cpu_percent = proc.cpu_percent()
                memory_info = proc.memory_info()
                create_time = proc.create_time()
                
            status = self._analyze_cpu_pattern(proc)
            
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
