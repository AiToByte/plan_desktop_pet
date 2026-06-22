"""
psutil Mock对象
模拟进程监控，避免依赖真实系统进程
"""
import time
from typing import Optional, List, Dict, Any
from unittest.mock import MagicMock


class MockProcessInfo:
    """模拟psutil.Process.info字典"""
    
    def __init__(self, pid: int = 12345, name: str = "claudecode", cmdline: Optional[List[str]] = None):
        self.pid = pid
        self.name = name
        self.cmdline = cmdline or ["claudecode", "--portable"]
    
    @property
    def info(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "cmdline": self.cmdline,
        }


class MockProcess:
    """模拟psutil.Process"""
    
    def __init__(
        self,
        pid: int = 12345,
        name: str = "claudecode",
        cpu_percent: float = 15.0,
        memory_rss: int = 100 * 1024 * 1024,
        create_time: Optional[float] = None,
    ):
        self.pid = pid
        self._name = name
        self._cpu_percent = cpu_percent
        self._memory_rss = memory_rss
        self._create_time = create_time or (time.time() - 3600)
        self._running = True
    
    def name(self) -> str:
        return self._name
    
    def cpu_percent(self, interval: Optional[float] = None) -> float:
        return self._cpu_percent
    
    def memory_info(self):
        """返回mock的memory_info命名元组"""
        mem = MagicMock()
        mem.rss = self._memory_rss
        return mem
    
    def create_time(self) -> float:
        return self._create_time
    
    def is_running(self) -> bool:
        return self._running
    
    def set_cpu(self, percent: float):
        """测试用：设置CPU百分比"""
        self._cpu_percent = percent
    
    def set_dead(self):
        """测试用：模拟进程死亡"""
        self._running = False
    
    def oneshot(self):
        """返回context manager"""
        return MagicMock(__enter__=MagicMock(return_value=self), __exit__=MagicMock())


class MockProcessIter:
    """模拟psutil.process_iter()返回值
    
    可直接作为patch目标。支持：
    - add_process(): 测试时动态添加进程
    - __call__(attrs): 返回进程列表（兼容psutil.process_iter(attrs)）
    - __iter__: 支持for循环
    """
    
    def __init__(self):
        self._processes: List[MockProcess] = []
        self._last_attrs: Optional[List[str]] = None
    
    def add_process(self, pid: int = 12345, name: str = "claudecode", 
                    cmdline: Optional[List[str]] = None, cpu_percent: float = 15.0):
        """测试用：添加进程到迭代器"""
        proc = MockProcess(pid=pid, name=name, cpu_percent=cpu_percent, memory_rss=100*1024*1024)
        # 保留自定义cmdline
        if cmdline is not None:
            proc._cmdline = cmdline
        else:
            proc._cmdline = [name]
        self._processes.append(proc)
    
    def __call__(self, attrs=None):
        """模拟 psutil.process_iter(attrs) 调用"""
        self._last_attrs = attrs
        result = []
        for proc in self._processes:
            mock_proc = MagicMock()
            mock_proc.pid = proc.pid
            mock_proc.name.return_value = proc._name
            mock_proc.cmdline.return_value = getattr(proc, '_cmdline', [proc._name])
            mock_proc.cpu_percent.return_value = proc._cpu_percent
            mock_proc.memory_info.return_value = MagicMock(rss=proc._memory_rss)
            mock_proc.create_time.return_value = proc._create_time
            mock_proc.is_running.return_value = proc._running
            # psutil在有attrs时设置.info字典，__iter__也需要此信息
            mock_proc.info = {
                "pid": proc.pid,
                "name": proc._name,
                "cmdline": getattr(proc, '_cmdline', [proc._name]),
            }
            result.append(mock_proc)
        return result
    
    def __iter__(self):
        """支持 for proc in mock_process_iter()
        
        注意：psutil.process_iter(attrs)返回的对象在迭代时总是带有.info字典。
        __iter__必须独立于__call__创建带info的mock对象。
        """
        result = []
        for proc in self._processes:
            mock_proc = MagicMock()
            mock_proc.pid = proc.pid
            mock_proc.name.return_value = proc._name
            mock_proc.cmdline.return_value = getattr(proc, '_cmdline', [proc._name])
            mock_proc.cpu_percent.return_value = proc._cpu_percent
            mock_proc.memory_info.return_value = MagicMock(rss=proc._memory_rss)
            mock_proc.create_time.return_value = proc._create_time
            mock_proc.is_running.return_value = proc._running
            mock_proc.info = {
                "pid": proc.pid,
                "name": proc._name,
                "cmdline": getattr(proc, '_cmdline', [proc._name]),
            }
            result.append(mock_proc)
        return iter(result)
    
    def clear(self):
        """清空所有进程"""
        self._processes.clear()


def create_mock_process(
    pid: int = 12345,
    name: str = "claudecode",
    cpu_percent: float = 15.0,
    memory_rss: int = 100 * 1024 * 1024,
) -> MockProcess:
    """工厂函数：创建MockProcess"""
    return MockProcess(pid=pid, name=name, cpu_percent=cpu_percent, memory_rss=memory_rss)


def create_mock_process_iter() -> MockProcessIter:
    """工厂函数：创建MockProcessIter实例
    
    返回的实例可直接用作patch的return_value，也支持add_process()动态添加进程。
    """
    return MockProcessIter()
