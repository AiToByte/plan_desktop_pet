"""
测试辅助工具包
提供mock对象、数据工厂、通用断言工具
"""
from .mock_communication import MockCommunication, MockSerial, MockSocket
from .mock_psutil import MockProcess, create_mock_process, create_mock_process_iter
from .factories import (
    make_agent_state,
    make_device_message,
    make_token_data,
    make_weather_data,
    make_jsonl_line,
    make_permission_request_jsonl,
    make_tool_use_jsonl,
    create_temp_jsonl,
    make_otlp_trace_payload,
    make_thinking_step,
)
