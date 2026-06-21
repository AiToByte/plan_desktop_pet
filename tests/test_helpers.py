"""
测试辅助模块 - 外部依赖mock
在GA venv无pip环境下，mock所有外部依赖
"""
import sys
from unittest.mock import MagicMock

# Mock psutil
psutil_mock = MagicMock()
psutil_mock.Process = MagicMock()
psutil_mock.NoSuchProcess = type('NoSuchProcess', (Exception,), {})
psutil_mock.AccessDenied = type('AccessDenied', (Exception,), {})
sys.modules['psutil'] = psutil_mock

# Mock serial
serial_mock = MagicMock()
serial_mock.Serial = MagicMock()
serial_mock.SerialException = type('SerialException', (Exception,), {})
sys.modules['serial'] = serial_mock

# Mock requests
requests_mock = MagicMock()
requests_mock.exceptions = MagicMock()
requests_mock.exceptions.RequestException = type('RequestException', (Exception,), {})
requests_mock.exceptions.Timeout = type('Timeout', (Exception,), {})
requests_mock.exceptions.ConnectionError = type('ConnectionError', (Exception,), {})
sys.modules['requests'] = requests_mock
sys.modules['requests.exceptions'] = requests_mock.exceptions

# Mock http.server (for otlp_receiver)
# Already available in stdlib, no need to mock
