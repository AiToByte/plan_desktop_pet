"""
pytest配置文件
提供基础fixture和测试工具
"""
import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 添加项目路径到sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "pc_monitor"))
sys.path.insert(0, str(project_root / "pixel_tool"))

# --- 基础路径fixtures ---

@pytest.fixture
def project_root_path():
    """项目根目录路径"""
    return project_root


@pytest.fixture
def temp_dir():
    """临时目录，测试结束后自动清理"""
    d = Path(tempfile.mkdtemp(prefix="deskpet_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fixtures_dir():
    """测试fixtures目录"""
    d = Path(__file__).parent / "fixtures" / "data"
    if d.exists():
        return d
    # 如果不存在，返回临时目录
    tmp = Path(tempfile.mkdtemp(prefix="deskpet_fixtures_"))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# --- Agent监控fixtures ---

@pytest.fixture
def mock_agent_state_factory():
    """AgentState工厂fixture"""
    from helpers.factories import make_agent_state
    return make_agent_state


@pytest.fixture
def mock_process():
    """模拟的Agent进程"""
    from helpers.mock_psutil import create_mock_process
    return create_mock_process()


@pytest.fixture
def mock_process_iter_factory():
    """psutil.process_iter工厂（原始名）"""
    from helpers.mock_psutil import create_mock_process_iter
    return create_mock_process_iter


@pytest.fixture
def mock_process_iter():
    """MockProcessIter实例，支持add_process()和作为psutil.process_iter的patch值"""
    from helpers.mock_psutil import create_mock_process_iter
    return create_mock_process_iter()


# --- JSONL fixtures ---

@pytest.fixture
def temp_jsonl_file():
    """创建含permission_request的临时JSONL文件，返回文件路径"""
    tmpdir = tempfile.mkdtemp(prefix="deskpet_jsonl_")
    jsonl_path = os.path.join(tmpdir, "session.jsonl")
    lines = [
        {"message": {"type": "assistant", "content": "Hello"}},
        {"message": {"type": "permission_request", "content": "Allow access?"}},
        {"message": {"type": "user", "content": "ok"}},
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")
    yield jsonl_path
    shutil.rmtree(tmpdir, ignore_errors=True)


# --- 通信fixtures ---

@pytest.fixture
def mock_serial():
    """模拟串口对象"""
    from helpers.mock_communication import MockSerial
    return MockSerial()


@pytest.fixture
def mock_communication():
    """模拟通信对象"""
    from helpers.mock_communication import MockCommunication
    return MockCommunication()


@pytest.fixture
def mock_socket():
    """模拟socket对象"""
    from helpers.mock_communication import MockSocket
    return MockSocket()


# --- 数据工厂fixtures ---

@pytest.fixture
def make_device_message():
    """DeviceMessage工厂"""
    from helpers.factories import make_device_message
    return make_device_message


@pytest.fixture
def make_token_data():
    """Token数据工厂"""
    from helpers.factories import make_token_data
    return make_token_data


@pytest.fixture
def make_weather_data():
    """天气数据工厂"""
    from helpers.factories import make_weather_data
    return make_weather_data


# --- JSONL测试fixtures ---

@pytest.fixture
def temp_jsonl_dir(temp_dir):
    """包含JSONL文件的临时目录结构（模拟Claude项目目录）"""
    project_dir = temp_dir / "projects" / "test-project"
    project_dir.mkdir(parents=True)
    jsonl_file = project_dir / "session.jsonl"
    jsonl_file.write_text("", encoding="utf-8")
    return temp_dir


@pytest.fixture
def jsonl_factory(temp_jsonl_dir):
    """JSONL文件工厂：写入指定行到临时JSONL文件"""
    from helpers.factories import make_jsonl_line
    
    def _write(lines: list) -> Path:
        jsonl_file = temp_jsonl_dir / "projects" / "test-project" / "session.jsonl"
        content = "\n".join(
            line if isinstance(line, str) else make_jsonl_line(**line)
            for line in lines
        )
        jsonl_file.write_text(content, encoding="utf-8")
        return jsonl_file
    
    return _write


# --- 通用配置fixtures ---

@pytest.fixture
def default_config():
    """默认PC端配置"""
    return {
        "process_names": ["claudecode", "codex"],
        "check_interval": 2,
        "serial_port": "COM3",
        "serial_baud": 115200,
        "wifi_port": 19876,
        "token_log_path": None,
        "weather_api_key": "test-api-key",
        "weather_city": "Shanghai",
    }


@pytest.fixture
def mock_time(monkeypatch):
    """冻结time.time()返回值"""
    frozen = time.time()
    
    def frozen_time():
        return frozen
    
    monkeypatch.setattr(time, "time", frozen_time)
    return frozen


# --- OTLP/ThinkingChain fixtures ---

@pytest.fixture
def make_otlp_payload():
    """OTLP payload工厂"""
    from helpers.factories import make_otlp_trace_payload
    return make_otlp_trace_payload


@pytest.fixture
def make_thinking_step():
    """Thinking step工厂"""
    from helpers.factories import make_thinking_step
    return make_thinking_step
