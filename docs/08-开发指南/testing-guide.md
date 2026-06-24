# 测试指南

本文档说明桌面电子宠物项目的测试框架、运行方式、Mock 策略和覆盖率要求。

---

## 一、测试框架

项目使用 **pytest** 作为测试框架，配合 `unittest.mock` 进行 Mock。

### 1.1 依赖安装

```bash
pip install -e ".[dev]"
```

开发依赖包含：

| 包名 | 版本 | 用途 |
|------|------|------|
| pytest | >= 7.0.0 | 测试框架、断言、fixture |
| ruff | >= 0.1.0 | Lint + 格式化 |
| mypy | >= 1.0.0 | 静态类型检查 |

### 1.2 配置文件

`pyproject.toml` 中的 pytest 配置：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

- `testpaths`: 测试文件搜索目录
- `addopts`: 默认输出详细信息，使用简短 traceback

---

## 二、运行测试

### 2.1 基本运行

```bash
# 运行全部测试
python -m pytest tests/

# 运行指定文件
python -m pytest tests/test_agent_monitor.py

# 运行指定测试类
python -m pytest tests/test_agent_monitor.py::TestAgentMonitor

# 运行指定测试函数
python -m pytest tests/test_agent_monitor.py::TestAgentMonitor::test_get_state_returns_idle_when_no_process
```

### 2.2 常用选项

```bash
# 显示详细输出
python -m pytest tests/ -v

# 遇到第一个失败即停止
python -m pytest tests/ -x

# 只运行匹配关键字的测试
python -m pytest tests/ -k "weather"

# 显示 print 输出
python -m pytest tests/ -s

# 显示覆盖率报告
python -m pytest tests/ --cov=pc_monitor --cov=pixel_tool --cov-report=term-missing
```

### 2.3 测试目录结构

```
tests/
  conftest.py              # 全局 fixture 和工具
  helpers/
    factories.py            # 测试数据工厂
    mock_psutil.py          # psutil Mock 工具
  fixtures/
    data/                   # 测试数据文件
  test_agent_monitor.py     # Agent 监控模块测试
  test_token_stats.py       # Token 统计模块测试
  test_weather.py           # 天气服务模块测试
  test_communication.py     # 通信模块测试
  test_pxl_encoder.py       # PXL 编码器测试
  test_pxl_decoder.py       # PXL 解码器测试
```

---

## 三、测试结构（AAA 模式）

所有测试遵循 **Arrange-Act-Assert** 结构：

```python
def test_get_state_returns_offline_when_no_process_found():
    # Arrange: 准备测试环境
    monitor = AgentMonitor({"process_names": ["nonexistent_process"]})

    # Act: 执行被测操作
    state = monitor.get_state()

    # Assert: 验证结果
    assert state.status == AgentStatus.OFFLINE
    assert state.pid is None
    assert state.cpu_percent == 0.0
```

### 3.1 测试命名规范

测试函数名应清晰描述被测行为：

```python
# 好：描述行为
def test_get_state_returns_working_when_cpu_above_threshold():
def test_fetch_weather_returns_mock_data_when_api_key_missing():
def test_rle_compress_produces_smaller_output_for_repetitive_data():

# 差：描述实现
def test_cpu_check():
def test_weather():
def test_compress():
```

### 3.2 测试类组织

同一模块的测试用 `Test*` 类组织：

```python
class TestAgentMonitor:
    """AgentMonitor 模块测试"""

    def test_get_state_returns_offline_when_no_process(self):
        ...

    def test_get_state_returns_working_when_cpu_high(self):
        ...

    def test_get_state_returns_idle_after_consecutive_low_cpu(self):
        ...
```

---

## 四、Mock 策略

### 4.1 psutil Mock

进程监控依赖 `psutil`，测试中使用 Mock 避免依赖真实系统进程。

`tests/helpers/mock_psutil.py` 提供 Mock 工具：

```python
from tests.helpers.mock_psutil import create_mock_process, create_mock_process_iter

def test_get_state_returns_working_when_cpu_high(monkeypatch):
    # 创建 Mock 进程，CPU 使用率 50%
    mock_proc = create_mock_process(cpu_percent=50.0, name="claudecode", pid=1234)

    # 创建 Mock process_iter，返回包含 mock_proc 的列表
    mock_iter = create_mock_process_iter([mock_proc])

    # 注入到 AgentMonitor
    monitor = AgentMonitor({"process_names": ["claudecode"]})
    monkeypatch.setattr("psutil.process_iter", mock_iter)

    state = monitor.get_state()
    assert state.status == AgentStatus.WORKING
```

### 4.2 通信模块 Mock

网络通信使用 Mock 避免真实网络连接：

```python
from unittest.mock import MagicMock, patch

def test_send_message_queues_when_connected():
    comm = WiFiCommunication({"wifi_host": "127.0.0.1", "wifi_port": 19876})
    comm._connected = True
    comm._client_socket = MagicMock()

    msg = DeviceMessage(msg_type="status", data={"cpu": 50})
    result = comm.send_message(msg)

    assert result is True
    assert comm._send_queue.qsize() == 1
```

### 4.3 文件系统 Mock

文件操作使用 `temp_dir` fixture 和真实临时文件，而非 Mock 文件系统：

```python
def test_image_to_pxl_creates_valid_file(temp_dir):
    """测试图片编码为 PXL 文件"""
    from PIL import Image

    # 在临时目录创建测试图片
    img_path = temp_dir / "test.png"
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    img.save(str(img_path))

    # 编码为 PXL
    pxl_path = temp_dir / "test.pxl"
    image_to_pxl(str(img_path), str(pxl_path), size=(32, 32))

    # 验证文件存在且头信息正确
    assert pxl_path.exists()
    header = read_pxl_header(pxl_path.read_bytes())
    assert header["width"] == 32
    assert header["height"] == 32
    assert header["frame_count"] == 1
```

### 4.4 全局 Fixture（conftest.py）

`tests/conftest.py` 提供基础 fixture：

| Fixture | 用途 |
|---------|------|
| `project_root_path` | 项目根目录 `Path` 对象 |
| `temp_dir` | 临时目录，测试结束后自动清理 |
| `fixtures_dir` | 测试数据目录 |
| `mock_agent_state_factory` | `AgentState` 数据工厂 |
| `mock_process` | 模拟的 Agent 进程对象 |
| `mock_process_iter` | 可配置的 `psutil.process_iter` Mock |

使用示例：

```python
def test_with_temp_file(temp_dir):
    """temp_dir 在测试结束后自动清理"""
    file_path = temp_dir / "output.pxl"
    file_path.write_bytes(b"PXL" + b"\x00" * 13)
    assert file_path.exists()
```

---

## 五、添加新测试步骤

### 5.1 步骤流程

1. **确定测试目标**: 明确要测试的模块和行为
2. **创建测试文件**: 在 `tests/` 目录下创建 `test_<module>.py`
3. **编写测试用例**: 遵循 AAA 模式
4. **添加 Mock**: 如有外部依赖（网络、进程、硬件），使用 Mock 隔离
5. **运行测试**: 确认测试通过
6. **检查覆盖率**: 确保新代码覆盖率 >= 80%

### 5.2 示例：为新模块添加测试

假设新增了 `pc_monitor/modules/heatmap.py` 模块：

```python
# tests/test_heatmap.py
"""Heatmap 模块测试"""
from unittest.mock import MagicMock
from modules.heatmap import HeatmapGenerator


class TestHeatmapGenerator:
    """HeatmapGenerator 测试"""

    def test_generate_returns_empty_when_no_data(self, temp_dir):
        # Arrange
        gen = HeatmapGenerator(output_dir=str(temp_dir))

        # Act
        result = gen.generate(data_points=[])

        # Assert
        assert result is None

    def test_generate_creates_image_file(self, temp_dir):
        # Arrange
        gen = HeatmapGenerator(output_dir=str(temp_dir))
        points = [(10, 20, 0.8), (30, 40, 0.5)]

        # Act
        result = gen.generate(data_points=points)

        # Assert
        assert result is not None
        assert (temp_dir / "heatmap.png").exists()
```

### 5.3 测试数据工厂

`tests/helpers/factories.py` 提供数据工厂函数，用于快速创建测试数据：

```python
from tests.helpers.factories import make_agent_state

# 创建自定义 AgentState
state = make_agent_state(
    status=AgentStatus.WORKING,
    cpu_percent=75.0,
    pid=1234
)
```

---

## 六、覆盖率要求

### 6.1 最低标准

- **总体覆盖率**: >= 80%
- **新增代码覆盖率**: >= 80%
- **关键模块**: Agent 监控、Token 统计、天气服务、通信模块需达到 90%+

### 6.2 覆盖率工具

使用 `pytest-cov` 插件：

```bash
# 安装
pip install pytest-cov

# 运行并生成报告
python -m pytest tests/ \
    --cov=pc_monitor \
    --cov=pixel_tool \
    --cov-report=term-missing \
    --cov-report=html:htmlcov
```

- `--cov=pc_monitor`: 测量 `pc_monitor/` 目录覆盖率
- `--cov-report=term-missing`: 终端显示未覆盖行号
- `--cov-report=html:htmlcov`: 生成 HTML 报告到 `htmlcov/` 目录

### 6.3 覆盖率报告解读

终端输出示例：

```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
pc_monitor/modules/agent_monitor    120     10    92%   45-48, 112-115
pc_monitor/modules/token_stats       95     12    87%   78-82, 156-160
pc_monitor/modules/weather           80      8    90%   120-125
---------------------------------------------------------------
TOTAL                               295     30    90%
```

- **Stmts**: 语句总数
- **Miss**: 未执行的语句数
- **Cover**: 覆盖率百分比
- **Missing**: 未覆盖的行号

### 6.4 排除不需要覆盖的代码

以下代码可排除在覆盖率统计之外：

```python
# 排除平台特定代码
if sys.platform == "win32":  # pragma: no cover
    ...

# 排除防御性编程的不可能分支
except Exception as e:  # pragma: no cover
    logger.critical(f"不可预期的错误: {e}")
```

在 `pyproject.toml` 中全局排除：

```toml
[tool.coverage.run]
omit = [
    "tests/*",
    "*/conftest.py",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.",
    "raise NotImplementedError",
]
```

---

## 附录：常用测试模式

### A. 异常测试

```python
import pytest

def test_read_pxl_header_raises_on_invalid_magic():
    with pytest.raises(ValueError, match="无效的PXL文件"):
        read_pxl_header(b"INVALID_DATA_TOO_SHORT")
```

### B. 参数化测试

```python
@pytest.mark.parametrize("cpu,expected_status", [
    (0.5, AgentStatus.AUTHORIZING),   # 低 CPU
    (5.0, AgentStatus.AUTHORIZING),   # 中 CPU
    (50.0, AgentStatus.WORKING),      # 高 CPU
])
def test_cpu_threshold_classification(cpu, expected_status, mock_process):
    monitor = AgentMonitor({"process_names": ["claudecode"]})
    mock_process.cpu_percent.return_value = cpu
    # ... 验证状态分类
```

### C. Fixture 作用域

```python
@pytest.fixture(scope="module")
def expensive_resource():
    """整个测试模块只创建一次"""
    resource = create_heavy_resource()
    yield resource
    resource.cleanup()
```

### D. 临时文件与目录

```python
def test_cache_file_creation(temp_dir):
    """temp_dir fixture 自动清理，无需手动删除"""
    cache_path = temp_dir / "cache.json"
    cache_path.write_text('{"key": "value"}')
    assert cache_path.exists()
```
