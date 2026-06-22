"""
测试数据工厂
提供各类数据对象的快速创建函数
"""
import time
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional


def make_agent_state(
    status: str = "idle",
    process_name: str = "claudecode",
    pid: int = 12345,
    cpu_percent: float = 5.0,
    memory_mb: float = 100.0,
    uptime_seconds: float = 3600.0,
) -> Dict[str, Any]:
    """创建AgentState字典（避免直接import依赖psutil的模块）"""
    return {
        "status": status,
        "process_name": process_name,
        "pid": pid,
        "cpu_percent": cpu_percent,
        "memory_mb": memory_mb,
        "uptime_seconds": uptime_seconds,
        "timestamp": time.time(),
    }


def make_device_message(
    msg_type: str = "status",
    data: Optional[Dict[str, Any]] = None,
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """创建DeviceMessage字典"""
    return {
        "type": msg_type,
        "data": data or {},
        "ts": timestamp or time.time(),
    }


def make_token_data(
    input_tokens: int = 1000,
    output_tokens: int = 500,
    model: str = "claude-sonnet-4-20250514",
    session_id: str = "test-session-001",
) -> Dict[str, Any]:
    """创建token统计数据"""
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": model,
        "session_id": session_id,
        "timestamp": time.time(),
    }


def make_weather_data(
    temp: float = 25.0,
    humidity: int = 60,
    description: str = "晴",
    icon: str = "01d",
    city: str = "Shanghai",
) -> Dict[str, Any]:
    """创建天气数据"""
    return {
        "temp": temp,
        "humidity": humidity,
        "description": description,
        "icon": icon,
        "city": city,
        "feels_like": temp - 2,
        "temp_min": temp - 3,
        "temp_max": temp + 3,
        "pressure": 1013,
        "visibility": 10000,
        "wind_speed": 3.5,
        "wind_deg": 180,
        "clouds": 20,
        "timestamp": time.time(),
    }


def make_jsonl_line(
    msg_type: str = "assistant",
    content: Any = "Hello",
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """创建JSONL格式行"""
    obj = {
        "message": {
            "type": msg_type,
            "content": content,
        },
        "timestamp": time.time(),
    }
    if extra:
        obj.update(extra)
    return json.dumps(obj, ensure_ascii=False)


def make_permission_request_jsonl() -> str:
    """创建包含permission_request的JSONL行"""
    return make_jsonl_line(
        msg_type="permission_request",
        content={"tool": "bash", "command": "rm -rf /"},
    )


def make_tool_use_jsonl(tool_name: str = "AskUser") -> str:
    """创建包含tool_use的JSONL行"""
    return make_jsonl_line(
        msg_type="assistant",
        content=[{"type": "tool_use", "name": tool_name, "input": {"question": "Continue?"}}],
    )


def create_temp_jsonl(lines: list, tmp_dir: Optional[Path] = None) -> Path:
    """在临时目录创建JSONL文件，返回路径"""
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp())
    jsonl_file = tmp_dir / "test.jsonl"
    jsonl_file.write_text("\n".join(lines), encoding="utf-8")
    return jsonl_file


def make_otlp_trace_payload(
    agent_name: str = "test-agent",
    status: str = "working",
    step_count: int = 5,
) -> Dict[str, Any]:
    """创建OTLP trace payload"""
    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "agent.name", "value": {"stringValue": agent_name}},
                    {"key": "agent.status", "value": {"stringValue": status}},
                ]
            },
            "scopeSpans": [{
                "spans": [{
                    "traceId": "abc123",
                    "spanId": "def456",
                    "name": "agent.step",
                    "attributes": [
                        {"key": "step_count", "value": {"intValue": step_count}},
                    ],
                }]
            }]
        }]
    }


def make_thinking_step(
    step_num: int = 1,
    thought: str = "分析问题",
    action: str = "read_file",
    status: str = "completed",
) -> Dict[str, Any]:
    """创建thinking chain步骤"""
    return {
        "step": step_num,
        "thought": thought,
        "action": action,
        "status": status,
        "timestamp": time.time(),
    }
