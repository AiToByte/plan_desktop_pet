# Agent进程检测机制

本文档详细描述 `pc_monitor/modules/agent_monitor.py` 中实现的AI Agent进程检测机制，包括支持的Agent类型、进程发现流程、CPU模式分析算法、JSONL授权检测和进程缓存策略。

---

## 一、支持的Agent类型

`AgentMonitor` 通过配置文件中的 `process_names` 列表定义要监控的Agent类型。默认配置支持以下三种：

| Agent标识 | 进程名/命令行特征 | 说明 |
|-----------|-------------------|------|
| `claudecode` | 进程名或命令行包含 `claudecode` | Anthropic Claude Code CLI |
| `codex` | 进程名或命令行包含 `codex` | OpenAI Codex CLI |
| `ooencode` | 进程名或命令行包含 `ooencode` | 其他AI编码助手 |

匹配逻辑采用**模糊匹配**：只要进程名（`proc.info['name']`）或命令行参数（`proc.info['cmdline']`）中包含目标字符串即视为匹配。匹配不区分大小写。

### Agent状态枚举

```python
class AgentStatus(Enum):
    IDLE       = "idle"      # 空闲：Agent已启动但未执行任务
    WORKING    = "working"   # 工作中：Agent正在处理请求
    AUTHORIZING = "auth"     # 等待授权：Agent需要用户确认操作
    OFFLINE    = "offline"   # 离线：未检测到Agent进程
```

### 状态数据结构

```python
@dataclass
class AgentState:
    status: AgentStatus      # 当前状态
    process_name: str        # 进程名称
    pid: Optional[int]       # 进程PID
    cpu_percent: float       # CPU使用率 (%)
    memory_mb: float         # 内存占用 (MB)
    uptime_seconds: float    # 运行时长 (秒)
    timestamp: float         # 采集时间戳
```

---

## 二、进程发现流程

进程发现采用**两级查找策略**：优先使用PID缓存（微秒级），缓存失效时才触发全量进程遍历。

### 2.1 整体流程

```
get_state() 入口
       │
       ▼
┌─────────────────────┐
│ PID缓存是否有效？     │
│  - is_running()      │
│  - name() 匹配       │
└──────┬──────────────┘
       │
   ┌───┴───┐
   │有效    │失效
   │       │
   ▼       ▼
 直接使用  ┌──────────────────────────┐
           │ psutil.process_iter()    │
           │ 遍历全部系统进程           │
           │                          │
           │ 对每个进程:               │
           │  1. 取 name (小写)        │
           │  2. 取 cmdline (小写拼接)  │
           │  3. 逐一匹配 process_names│
           │  4. 匹配成功 → 返回Process│
           └──────────┬───────────────┘
                      │
                      ▼
              重置CPU历史窗口
              预热首次cpu_percent采样
              （丢弃首次返回的0值）
```

### 2.2 匹配算法

```python
def _find_agent_process(self) -> Optional[psutil.Process]:
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        proc_name = (proc.info['name'] or '').lower()
        cmdline = ' '.join(proc.info['cmdline'] or []).lower()

        for target in self.process_names:
            if target in proc_name or target in cmdline:
                return proc
    return None
```

关键细节：

- `process_iter()` 使用 `attrs` 参数限制返回字段，减少内存开销
- 进程名和命令行参数均转为小写后匹配
- 遇到 `NoSuchProcess` 或 `AccessDenied` 异常时静默跳过
- 返回第一个匹配的进程（不支持多实例）

### 2.3 缓存失效条件

PID缓存在以下情况被清除：

1. `proc.is_running()` 返回 `False`（进程已退出）
2. `proc.name()` 不再匹配任何 `process_names`（进程被替换）
3. 捕获到 `NoSuchProcess` 或 `AccessDenied` 异常
4. CPU采样或内存读取时进程消失

---

## 三、CPU模式分析算法

CPU模式分析是Agent状态判断的核心，通过滑动窗口平滑采样和多级阈值判定实现稳定的状态识别。

### 3.1 算法概述

```
cpu_percent(interval=0)  ← 非阻塞采样
        │
        ▼
   追加到滑动窗口 (deque, maxlen=5)
        │
        ▼
   计算窗口平均值 avg_cpu
        │
        ├── avg_cpu > 30%  ──→ WORKING
        │
        ├── avg_cpu > 3%   ──→ AUTHORIZING
        │
        └── avg_cpu <= 3%  ──→ idle_streak += 1
                                │
                                ├── streak < 6  ──→ AUTHORIZING（暂不确认空闲）
                                └── streak >= 6  ──→ IDLE（连续6次确认空闲）
```

### 3.2 阈值常量

| 常量 | 值 | 含义 |
|------|----|------|
| `CPU_THRESHOLD_WORKING` | 30.0% | 高于此值判定为工作中 |
| `CPU_THRESHOLD_AUTHORIZING` | 3.0% | 3%~30%之间判定为等待授权 |
| `IDLE_CONFIRM_COUNT` | 6 | 连续低CPU次数确认空闲 |
| `CPU_HISTORY_WINDOW` | 5 | 滑动窗口大小 |

### 3.3 状态判定逻辑

| 平均CPU范围 | idle_streak | 判定状态 | 说明 |
|-------------|-------------|----------|------|
| > 30% | 任意（重置为0） | WORKING | Agent正在处理请求 |
| 3% ~ 30% | 任意（重置为0） | AUTHORIZING | Agent可能在等待用户输入或授权 |
| <= 3% | < 6 | AUTHORIZING | 暂不确认空闲，继续观察 |
| <= 3% | >= 6 | IDLE | 连续12秒低CPU，确认空闲 |

### 3.4 为什么需要滑动窗口

`psutil.cpu_percent(interval=0)` 返回的是自上次调用以来的瞬时CPU百分比，容易受到以下因素干扰：

- **系统调度抖动**：单次采样可能偏高或偏低
- **Agent间歇性工作**：短时间内CPU波动剧烈
- **GC暂停**：Python垃圾回收导致短暂CPU飙升

滑动窗口（deque, maxlen=5）保留最近5次采样，取平均值平滑波动。窗口自动淘汰旧数据，无需手动清理。

### 3.5 为什么需要idle确认计数

从AUTHORIZING切换到IDLE需要连续6次低CPU（约12秒），原因：

1. **防止误判**：Agent可能短暂等待后继续工作
2. **避免闪烁**：防止状态在AUTHORIZING和IDLE之间频繁切换
3. **匹配实际行为**：用户通常需要几秒到十几秒来响应授权请求

一旦CPU回升，`_idle_streak` 立即重置为0，确保下次进入低CPU时重新计数。

---

## 四、JSONL授权检测

JSONL授权检测是对CPU模式分析的**精确补充**，通过读取Agent的日志文件确认是否存在待处理的授权请求。

### 4.1 检测流程

```
_check_auth_jsonl() 入口
       │
       ▼
  遍历 _auth_jsonl_dirs
  （默认: ~/.claude/projects）
       │
       ▼
  glob搜索JSONL文件
  优先级: */*/*/*.jsonl → */*.jsonl → *.jsonl
  （限制搜索深度≤3层）
       │
       ▼
  按修改时间排序，取最新文件
       │
       ▼
  读取文件末尾8KB（避免大文件性能问题）
       │
       ▼
  解析最后N行（默认30行）
       │
       ▼
  逐行检测授权请求特征
  → 检测到 → return True
  → 未检测到 → return False
```

### 4.2 授权请求特征

`_parse_jsonl_line()` 检测以下三种授权请求模式：

**模式1：permission_request类型**

```json
{"message": {"type": "permission_request", ...}}
```

直接匹配 `message.type == "permission_request"`。

**模式2：permission + pending关键词**

```json
{"message": {"content": "Waiting for permission approval..."}}
```

在 `message.content` 字符串中同时包含 `"permission"` 和 `"pending"`（不区分大小写）。

**模式3：AskUser工具调用**

```json
{"message": {"content": [{"type": "tool_use", "name": "AskUser", ...}]}}
```

`message.content` 为列表时，检测其中 `type == "tool_use"` 且 `name` 包含 `"AskUser"` 或 `"ask"` 的条目。

### 4.3 性能优化

| 优化策略 | 说明 |
|----------|------|
| 文件末尾读取 | `f.seek(-8192, SEEK_END)` 只读最后8KB |
| 行数限制 | 只检查最后30行 (`_auth_jsonl_max_lines`) |
| 搜索深度限制 | glob最多3层目录，避免递归home目录 |
| 只检查最新文件 | 按 `mtime` 排序后只取第一个 |
| 异常静默 | `IOError`/`OSError` 记录debug日志后继续 |

### 4.4 与CPU分析的协作

JSONL检测不是独立使用的，而是与CPU模式分析**联合判定**：

```
CPU分析结果          JSONL检测结果        最终状态
─────────────────────────────────────────────────
AUTHORIZING          检测到auth           AUTHORIZING（精确确认）
AUTHORIZING          未检测到             AUTHORIZING（可能是等待输入）
WORKING              检测到auth           AUTHORIZING（CPU刚升高但auth刚弹出）
WORKING              未检测到             WORKING
IDLE                 任意                 IDLE（已确认空闲，不检测JSONL）
OFFLINE              任意                 OFFLINE（进程不存在）
```

关键逻辑：当CPU判定为WORKING但JSONL检测到授权请求时，**优先提升为AUTHORIZING**，防止用户在等待授权时看到"工作中"状态。

---

## 五、进程缓存策略

进程缓存是Agent检测的性能优化核心，通过避免每2秒执行一次全量进程遍历，大幅降低PC端CPU开销。

### 5.1 缓存架构

```
_cached_proc: Optional[psutil.Process]
       │
       ▼
┌─────────────────────────────────┐
│ 轻量级验证（微秒级）              │
│  1. is_running() → 进程是否存活   │
│  2. name() → 进程名是否匹配       │
└──────────┬──────────────────────┘
           │
       ┌───┴───┐
       │有效    │失效
       │       │
       ▼       ▼
   直接使用  全量遍历 _find_agent_process()
             │
             ▼
         重置CPU历史窗口
         重置idle_streak
         预热cpu_percent（首次采样丢弃）
```

### 5.2 缓存命中路径（快速路径）

```python
if self._cached_proc:
    try:
        if self._cached_proc.is_running() and \
           any(t in self._cached_proc.name().lower() for t in self.process_names):
            pass  # 缓存有效，直接使用
        else:
            self._cached_proc = None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        self._cached_proc = None
```

- `is_running()` 仅检查 `/proc/{pid}` 是否存在（Linux）或进程句柄是否有效（Windows）
- `name()` 读取进程名，与 `process_names` 列表做子串匹配
- 整个验证过程耗时在微秒级

### 5.3 缓存失效路径（慢速路径）

当缓存失效时：

1. 调用 `_find_agent_process()` 遍历全部系统进程
2. 重置 `_cpu_history`（清空滑动窗口）
3. 重置 `_idle_streak`（清空空闲计数）
4. 如果找到新进程，执行 `cpu_percent(interval=None)` 预热

**预热的必要性**：`psutil.cpu_percent()` 首次调用返回0（因为没有上次调用的基准），预热后丢弃这个0值，避免首次采样导致误判为AUTHORIZING。

### 5.4 缓存一致性保障

缓存在以下场景会被主动清除：

| 场景 | 触发位置 | 说明 |
|------|----------|------|
| 进程退出 | `is_running()` 返回False | 进程正常退出或被kill |
| 进程名变更 | `name()` 不匹配 | 极少见，可能是PID复用 |
| 进程消失 | `NoSuchProcess` 异常 | 进程在检查过程中退出 |
| 权限丢失 | `AccessDenied` 异常 | 进程权限提升后无法访问 |
| 信息读取失败 | `get_state()` 的except块 | `proc.oneshot()` 中进程消失 |

### 5.5 性能对比

| 策略 | 每次调用耗时 | CPU开销 |
|------|-------------|---------|
| 无缓存（全量遍历） | 50~200ms | 高（每2秒遍历数百个进程） |
| 有缓存（命中） | <0.1ms | 极低（仅检查PID存活） |
| 有缓存（失效） | 50~200ms | 与无缓存相同，但极少发生 |

在Agent正常运行期间，缓存命中率接近100%，实际CPU开销可忽略不计。

---

## 附录：完整状态机

```
                    ┌───────────────────────────────────┐
                    │                                   │
                    ▼                                   │
              ┌──────────┐    进程启动     ┌──────────┐ │
              │          │ ─────────────→ │          │ │
              │  OFFLINE │                │ IDLE     │─┘
              │          │ ←───────────── │          │
              └──────────┘    进程退出     └────┬─────┘
                                   ▲           │
                                   │    CPU>3% │ CPU<=3%×6
                                   │           ▼
                              ┌────┴────┐  ┌──────────┐
                              │         │  │          │
                              │ WORKING │←─│AUTHORIZING│
                              │         │→ │          │
                              └─────────┘  └──────────┘
                              CPU>30%     3%<CPU<=30%
                              或JSONL确认  或JSONL检测
```

### 状态转移条件

| 当前状态 | 触发条件 | 目标状态 |
|----------|----------|----------|
| OFFLINE | 进程被检测到 | IDLE（首次进入） |
| IDLE | CPU > 3% | AUTHORIZING |
| AUTHORIZING | CPU > 30% | WORKING |
| AUTHORIZING | CPU <= 3% 且 idle_streak >= 6 | IDLE |
| WORKING | CPU <= 30% | AUTHORIZING |
| WORKING | JSONL检测到auth请求 | AUTHORIZING |
| 任意（非OFFLINE） | 进程消失 | OFFLINE |
