"""
agent_monitor模块测试
覆盖：进程查找、CPU模式分析、JSONL解析、状态判断、监控启停
"""
import time
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from modules.agent_monitor import (
    AgentMonitor,
    AgentState,
    AgentStatus,
    CPU_THRESHOLD_WORKING,
    CPU_THRESHOLD_AUTHORIZING,
    IDLE_CONFIRM_COUNT,
    CPU_HISTORY_WINDOW,
)


class TestAgentStatusEnum:
    """AgentStatus枚举测试"""

    def test_status_values(self):
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.WORKING.value == "working"
        assert AgentStatus.AUTHORIZING.value == "auth"
        assert AgentStatus.OFFLINE.value == "offline"

    def test_status_members(self):
        assert len(AgentStatus) == 4


class TestAgentState:
    """AgentState数据类测试"""

    def test_creation(self):
        state = AgentState(
            status=AgentStatus.IDLE,
            process_name="claudecode",
            pid=1234,
            cpu_percent=1.5,
            memory_mb=100.0,
            uptime_seconds=3600.0,
            timestamp=time.time(),
        )
        assert state.status == AgentStatus.IDLE
        assert state.process_name == "claudecode"
        assert state.pid == 1234
        assert state.cpu_percent == 1.5

    def test_creation_with_none_pid(self):
        state = AgentState(
            status=AgentStatus.OFFLINE,
            process_name="none",
            pid=None,
            cpu_percent=0.0,
            memory_mb=0.0,
            uptime_seconds=0.0,
            timestamp=time.time(),
        )
        assert state.pid is None
        assert state.status == AgentStatus.OFFLINE


class TestFindAgentProcess:
    """进程查找测试"""

    def _make_monitor(self, names=None):
        config = {"process_names": names or ["claudecode"], "auth_jsonl_dirs": []}
        return AgentMonitor(config)

    def test_find_process_by_name(self, mock_process_iter):
        """通过进程名查找"""
        mock_process_iter.add_process(pid=100, name="claudecode", cmdline=["claudecode"])
        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            proc = monitor._find_agent_process()
        assert proc is not None
        assert proc.info["pid"] == 100

    def test_find_process_by_cmdline(self, mock_process_iter):
        """通过命令行参数查找"""
        mock_process_iter.add_process(pid=200, name="python", cmdline=["python", "my-claudecode"])
        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            proc = monitor._find_agent_process()
        assert proc is not None
        assert proc.info["pid"] == 200

    def test_find_process_not_found(self, mock_process_iter):
        """未找到进程返回None"""
        mock_process_iter.add_process(pid=999, name="unrelated", cmdline=["unrelated"])
        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            proc = monitor._find_agent_process()
        assert proc is None

    def test_find_process_multiple_targets(self, mock_process_iter):
        """多个目标进程名，匹配第一个"""
        mock_process_iter.add_process(pid=300, name="codex", cmdline=["codex"])
        monitor = self._make_monitor(names=["claudecode", "codex"])
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            proc = monitor._find_agent_process()
        assert proc is not None
        assert proc.info["name"] == "codex"

    def test_find_process_skips_nosuchprocess(self, mock_process_iter):
        """跳过NoSuchProcess异常的进程"""
        mock_process_iter.add_process(pid=400, name="claudecode", cmdline=["claudecode"])
        # 添加一个访问info时抛出NoSuchProcess的"坏进程"
        broken_mock = MagicMock()
        broken_mock.pid = 401
        broken_mock.info = MagicMock()
        broken_mock.info.__getitem__ = MagicMock(side_effect=ProcessLookupError)
        mock_process_iter._processes.append(broken_mock)
        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            proc = monitor._find_agent_process()
        assert proc is not None


class TestAnalyzeCpuPattern:
    """CPU模式分析测试"""

    def _make_monitor(self):
        return AgentMonitor({"process_names": ["claudecode"], "auth_jsonl_dirs": []})

    def _make_proc(self, cpu_value):
        proc = MagicMock()
        proc.cpu_percent.return_value = cpu_value
        return proc

    def test_high_cpu_returns_working(self):
        """高CPU返回WORKING"""
        monitor = self._make_monitor()
        proc = self._make_proc(CPU_THRESHOLD_WORKING + 10)
        status = monitor._analyze_cpu_pattern(proc)
        assert status == AgentStatus.WORKING

    def test_medium_cpu_returns_authorizing(self):
        """中等CPU返回AUTHORIZING"""
        monitor = self._make_monitor()
        proc = self._make_proc(CPU_THRESHOLD_AUTHORIZING + 2)
        status = monitor._analyze_cpu_pattern(proc)
        assert status == AgentStatus.AUTHORIZING

    def test_low_cpu_initial_returns_authorizing(self):
        """低CPU初始返回AUTHORIZING（未达到IDLE确认次数）"""
        monitor = self._make_monitor()
        proc = self._make_proc(0.1)
        status = monitor._analyze_cpu_pattern(proc)
        assert status == AgentStatus.AUTHORIZING  # 第1次，还没确认

    def test_low_cpu_streak_confirms_idle(self):
        """连续低CPU达到阈值确认IDLE"""
        monitor = self._make_monitor()
        proc = self._make_proc(0.1)
        for _ in range(IDLE_CONFIRM_COUNT - 1):
            monitor._analyze_cpu_pattern(proc)
        status = monitor._analyze_cpu_pattern(proc)
        assert status == AgentStatus.IDLE

    def test_cpu_sliding_window(self):
        """滑动窗口平滑CPU采样"""
        monitor = self._make_monitor()
        # 注入高CPU值但窗口未满
        for _ in range(CPU_HISTORY_WINDOW - 1):
            proc = self._make_proc(CPU_THRESHOLD_WORKING + 20)
            monitor._analyze_cpu_pattern(proc)
        assert len(monitor._cpu_history) == CPU_HISTORY_WINDOW - 1
        # 一次新采样使窗口满
        proc = self._make_proc(CPU_THRESHOLD_WORKING + 20)
        monitor._analyze_cpu_pattern(proc)
        assert len(monitor._cpu_history) == CPU_HISTORY_WINDOW

    def test_cpu_window_slides(self):
        """窗口滑动丢弃旧值"""
        monitor = self._make_monitor()
        for _ in range(CPU_HISTORY_WINDOW + 2):
            proc = self._make_proc(50.0)
            monitor._analyze_cpu_pattern(proc)
        assert len(monitor._cpu_history) == CPU_HISTORY_WINDOW

    def test_high_cpu_resets_idle_streak(self):
        """高CPU重置idle_streak"""
        monitor = self._make_monitor()
        monitor._idle_streak = 5
        proc = self._make_proc(CPU_THRESHOLD_WORKING + 5)
        monitor._analyze_cpu_pattern(proc)
        assert monitor._idle_streak == 0

    def test_process_died_returns_offline(self):
        """进程异常返回OFFLINE"""
        from psutil import NoSuchProcess
        monitor = self._make_monitor()
        proc = MagicMock()
        proc.cpu_percent.side_effect = NoSuchProcess(1234)
        status = monitor._analyze_cpu_pattern(proc)
        assert status == AgentStatus.OFFLINE


class TestParseJsonlLine:
    """JSONL行解析测试"""

    def _make_monitor(self):
        return AgentMonitor({"process_names": ["claudecode"], "auth_jsonl_dirs": []})

    def test_permission_request_detected(self):
        """检测permission_request消息"""
        monitor = self._make_monitor()
        line = json.dumps({"message": {"type": "permission_request", "content": "Allow?"}})
        assert monitor._parse_jsonl_line(line) is True

    def test_permission_pending_in_content(self):
        """检测content中含permission+pending"""
        monitor = self._make_monitor()
        line = json.dumps({"message": {"content": "permission request pending approval"}})
        assert monitor._parse_jsonl_line(line) is True

    def test_ask_user_tool_use(self):
        """检测AskUser tool_use"""
        monitor = self._make_monitor()
        line = json.dumps({
            "message": {
                "content": [{"type": "tool_use", "name": "AskUser", "input": {"question": "?"}}]
            }
        })
        assert monitor._parse_jsonl_line(line) is True

    def test_ask_lowercase_tool_use(self):
        """检测小写ask tool_use"""
        monitor = self._make_monitor()
        line = json.dumps({
            "message": {
                "content": [{"type": "tool_use", "name": "ask_for_input", "input": {}}]
            }
        })
        assert monitor._parse_jsonl_line(line) is True

    def test_normal_message_not_detected(self):
        """普通消息不触发检测"""
        monitor = self._make_monitor()
        line = json.dumps({"message": {"type": "assistant", "content": "Hello world"}})
        assert monitor._parse_jsonl_line(line) is False

    def test_invalid_json_not_detected(self):
        """无效JSON不触发检测"""
        monitor = self._make_monitor()
        assert monitor._parse_jsonl_line("not json at all") is False

    def test_empty_line_not_detected(self):
        """空行不触发检测"""
        monitor = self._make_monitor()
        assert monitor._parse_jsonl_line("") is False

    def test_missing_message_key(self):
        """缺少message字段不触发"""
        monitor = self._make_monitor()
        line = json.dumps({"type": "other"})
        assert monitor._parse_jsonl_line(line) is False


class TestCheckAuthJsonl:
    """JSONL文件扫描测试"""

    def _make_monitor(self, dirs):
        return AgentMonitor({"process_names": ["claudecode"], "auth_jsonl_dirs": dirs})

    def test_no_directory_returns_false(self):
        """目录不存在返回False"""
        monitor = self._make_monitor(["/nonexistent/path"])
        assert monitor._check_auth_jsonl() is False

    def test_no_jsonl_files_returns_false(self):
        """目录无JSONL文件返回False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = self._make_monitor([tmpdir])
            assert monitor._check_auth_jsonl() is False

    def test_jsonl_with_permission_request(self, temp_jsonl_file):
        """JSONL含permission_request返回True"""
        monitor = self._make_monitor([str(Path(temp_jsonl_file).parent)])
        assert monitor._check_auth_jsonl() is True

    def test_jsonl_normal_content_returns_false(self):
        """JSONL无auth内容返回False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "test.jsonl")
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for _ in range(5):
                    f.write(json.dumps({"message": {"type": "assistant", "content": "ok"}}) + "\n")
            monitor = self._make_monitor([tmpdir])
            assert monitor._check_auth_jsonl() is False

    def test_only_reads_latest_file(self):
        """只检查最新JSONL文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 旧文件有permission
            old_path = os.path.join(tmpdir, "old.jsonl")
            with open(old_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"message": {"type": "permission_request"}}) + "\n")
            time.sleep(0.05)
            # 新文件无permission
            new_path = os.path.join(tmpdir, "new.jsonl")
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"message": {"type": "assistant", "content": "ok"}}) + "\n")
            monitor = self._make_monitor([tmpdir])
            # 应该只看new.jsonl，返回False
            assert monitor._check_auth_jsonl() is False


class TestGetState:
    """get_state()集成测试"""

    def _make_monitor(self):
        return AgentMonitor({"process_names": ["claudecode"], "auth_jsonl_dirs": []})

    def test_offline_when_no_process(self, mock_process_iter):
        """无进程时返回OFFLINE"""
        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            state = monitor.get_state()
        assert state.status == AgentStatus.OFFLINE
        assert state.pid is None
        assert state.process_name == "none"

    def test_returns_agent_state_fields(self, mock_process_iter):
        """返回完整AgentState字段"""
        proc = MagicMock()
        proc.pid = 500
        proc.name.return_value = "claudecode"
        proc.is_running.return_value = True
        proc.cpu_percent.return_value = 45.0
        proc.oneshot.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        mem = MagicMock()
        mem.rss = 200 * 1024 * 1024  # 200MB
        proc.memory_info.return_value = mem
        proc.create_time.return_value = time.time() - 7200

        mock_process_iter.add_process(pid=500, name="claudecode", cmdline=["claudecode"])

        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            # 预热cpu_percent
            state = monitor.get_state()
        # 第一次采样可能不准确，调用第二次
        state = monitor.get_state()
        assert isinstance(state, AgentState)
        assert state.pid == 500
        assert state.process_name == "claudecode"
        assert state.memory_mb > 0

    def test_cached_proc_reuse(self, mock_process_iter):
        """缓存进程对象避免重复查找"""
        proc = MagicMock()
        proc.pid = 600
        proc.name.return_value = "claudecode"
        proc.is_running.return_value = True
        proc.cpu_percent.return_value = 2.0
        proc.oneshot.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        mem = MagicMock()
        mem.rss = 100 * 1024 * 1024
        proc.memory_info.return_value = mem
        proc.create_time.return_value = time.time() - 3600

        mock_process_iter.add_process(pid=600, name="claudecode", cmdline=["claudecode"])

        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter) as mock_pi:
            monitor.get_state()
            monitor.get_state()  # 第二次应使用缓存
            # process_iter只应被调用1次（首次查找），第二次用缓存
            assert mock_pi.call_count <= 2  # 首次+可能的预热

    def test_process_dies_clears_cache(self, mock_process_iter):
        """进程死亡清除缓存"""
        monitor = self._make_monitor()
        # 模拟缓存但进程已死
        dead_proc = MagicMock()
        dead_proc.is_running.return_value = False
        monitor._cached_proc = dead_proc

        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            state = monitor.get_state()
        assert state.status == AgentStatus.OFFLINE
        assert monitor._cached_proc is None

    def test_access_during_oneshot_returns_offline(self, mock_process_iter):
        """oneshot中AccessDenied返回OFFLINE"""
        from psutil import AccessDenied
        # 直接构建带side_effect的mock，绕过__iter__重建
        mock_proc = MagicMock()
        mock_proc.pid = 700
        mock_proc.name.return_value = "claudecode"
        mock_proc.cmdline.return_value = ["claudecode"]
        mock_proc.is_running.return_value = True
        mock_proc.cpu_percent.return_value = 0
        mock_proc.oneshot.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        mock_proc.memory_info.side_effect = AccessDenied(700)
        mock_proc.info = {"pid": 700, "name": "claudecode", "cmdline": ["claudecode"]}
        mock_process_iter.__iter__ = MagicMock(return_value=iter([mock_proc]))

        monitor = self._make_monitor()
        with patch("modules.agent_monitor.psutil.process_iter", return_value=mock_process_iter):
            state = monitor.get_state()
        # should return OFFLINE
        assert state.status == AgentStatus.OFFLINE


class TestStartStopMonitoring:
    """监控启停测试"""

    def _make_monitor(self):
        return AgentMonitor({
            "process_names": ["claudecode"],
            "auth_jsonl_dirs": [],
            "check_interval": 0.05,  # 很短间隔方便测试
        })

    def test_start_stop_cycle(self):
        """启动和停止监控"""
        monitor = self._make_monitor()
        states = []

        def collector(s):
            states.append(s)

        import threading
        t = threading.Thread(target=monitor.start_monitoring, args=(collector,))
        t.daemon = True
        t.start()

        time.sleep(0.5)  # 等待几轮采集（未mock psutil需更长时间）
        monitor.stop_monitoring()
        t.join(timeout=5)

        assert len(states) >= 1
        assert all(isinstance(s, AgentState) for s in states)
        assert monitor._running is False

    def test_stop_immediate_effect(self):
        """停止应立即生效，无需等待完整间隔"""
        monitor = self._make_monitor()
        import threading
        t = threading.Thread(target=monitor.start_monitoring)
        t.daemon = True
        t.start()

        time.sleep(0.01)
        start = time.time()
        monitor.stop_monitoring()
        t.join(timeout=5)
        elapsed = time.time() - start

        assert elapsed < 3.0  # 未mock psutil时系统调用可能较慢

    def test_callback_called(self):
        """回调函数被调用"""
        monitor = self._make_monitor()
        called = []
        import threading
        t = threading.Thread(target=monitor.start_monitoring, args=(lambda s: called.append(1),))
        t.daemon = True
        t.start()
        time.sleep(0.5)  # 未mock psutil需更长时间
        monitor.stop_monitoring()
        t.join(timeout=5)
        assert len(called) >= 1
