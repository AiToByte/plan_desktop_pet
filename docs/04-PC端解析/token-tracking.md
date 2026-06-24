# Token 统计系统

> 源文件: `pc_monitor/modules/token_stats.py`

本文档描述桌面宠物项目中 Token 使用量的追踪、解析与统计机制。系统采用增量文件读取策略，避免每次轮询全量扫描日志文件带来的 IO 浪费，同时支持 JSONL 和纯文本两种日志格式。

---

## 一、LogTailer 增量文件读取器

`LogTailer` 类是整个统计系统的 IO 基础设施，负责以最小开销读取日志文件的新增内容。

### 1.1 位置追踪机制

每个被监控的文件在 `_file_states` 字典中维护一个状态条目：

```python
# 内部数据结构
self._file_states: Dict[str, Dict] = {}
# 例如: {"/path/to/log.jsonl": {"position": 4096, "inode": 1718956800000}}
```

- **position**: 上次读取结束时的文件偏移量（字节），下次读取从该位置开始
- **inode**: 文件的身份标识。Windows 系统没有 inode 概念，使用 `st_ctime * 1000`（创建时间的毫秒级整数）模拟

### 1.2 首次读取策略

当一个文件首次被读取时，不会从头开始扫描，而是从**末尾前 10KB** 处开始：

```python
start_pos = max(0, current_size - 10 * 1024)
```

这是冷启动优化：避免在程序刚启动时对大型日志文件进行全量扫描，只关注最近的记录。对于 Token 统计场景，近期数据比历史数据更有价值。

### 1.3 文件轮转检测

日志系统经常执行文件轮转（rotation），即把当前日志重命名归档、创建新文件。`LogTailer` 通过两种方式检测轮转：

**方式一：inode 变化**

```python
elif current_inode != state["inode"]:
    logger.info(f"文件轮转检测: {file_path}")
    state["position"] = 0
    state["inode"] = current_inode
```

当文件的 inode（或 Windows 上的创建时间）发生变化，说明原文件被重命名/归档，当前路径指向了一个新文件，需要从头读取。

**方式二：文件截断**

```python
elif current_size < state["position"]:
    logger.info(f"文件截断检测: {file_path}")
    state["position"] = 0
```

如果文件大小小于上次记录的偏移量，说明文件被截断（truncate）或被新内容完全覆盖，同样从头读取。

### 1.4 读取流程

```
read_new_lines(file_path)
    |
    v
文件不存在? ──是──> 返回空列表
    |
    否
    v
获取文件 stat (size + ctime)
    |
    v
首次读取? ──是──> position = max(0, size - 10KB)
    |
    否
    v
inode 变化? ──是──> 轮转检测, position = 0
    |
    否
    v
size < position? ──是──> 截断检测, position = 0
    |
    否
    v
size <= position? ──是──> 无新增内容, 返回空列表
    |
    否
    v
f.seek(position) → 逐行读取 → 更新 position = f.tell()
```

---

## 二、JSONL 解析

`TokenTracker` 支持两种日志格式的解析，优先尝试 JSONL，失败后回退到正则匹配。

### 2.1 Claude CLI JSONL 格式

Claude CLI 的使用日志采用 JSONL（JSON Lines）格式，每行一个 JSON 对象。Token 使用信息嵌套在 `message.usage` 字段中：

```json
{"message": {"usage": {"input_tokens": 1500, "output_tokens": 320}}}
```

解析逻辑：

```python
obj = json.loads(line)
msg = obj.get("message", {})
usage = msg.get("usage", {})
if usage and ("input_tokens" in usage or "output_tokens" in usage):
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0))
    }
```

### 2.2 正则匹配回退模式

对于非 JSONL 格式的纯文本日志，使用三个预编译的正则表达式模式进行匹配：

| 模式 | 匹配格式示例 |
|------|-------------|
| `tokens?:\s*input[=:]\s*(\d+)\s*output[=:]\s*(\d+)` | `token: input=1500 output=320` |
| `prompt_tokens?[=:]\s*(\d+).*?completion_tokens?[=:]\s*(\d+)` | `prompt_tokens=1500 ... completion_tokens=320` |
| `input_tokens[=:]\s*(\d+).*?output_tokens?[=:]\s*(\d+)` | `input_tokens=1500 ... output_tokens=320` |

这些模式在类级别预编译（`_TOKEN_PATTERNS`），避免每次解析日志行时重复编译正则表达式，是性能优化的关键细节。

### 2.3 自动发现机制

除了手动配置的日志路径，系统还支持自动发现 JSONL 文件：

```python
self.auto_discover = config.get("auto_discover", False)
self.auto_discover_dirs = config.get("auto_discover_dirs", [])
self.auto_discover_pattern = config.get("auto_discover_pattern", "*.jsonl")
```

发现流程：
1. 遍历配置的目录列表，递归搜索匹配 `*.jsonl` 的文件
2. 按修改时间降序排列，只保留最新的 **3 个文件**
3. 结果缓存 **60 秒**，避免频繁的文件系统扫描

---

## 三、价格模型

系统内置了 Claude 模型系列的 Token 定价（USD / 1M tokens）：

| 模型 | Input 价格 | Output 价格 | 特点 |
|------|-----------|------------|------|
| claude-3-opus | $15.00 | $75.00 | 最强推理能力，价格最高 |
| claude-3-sonnet | $3.00 | $15.00 | 平衡性能与成本 |
| claude-3-haiku | $0.25 | $1.25 | 最快速度，价格最低 |
| default | $3.00 | $15.00 | 默认使用 Sonnet 价格 |

费用估算公式：

```python
cost = (total_input * pricing["input"] + total_output * pricing["output"]) / 1_000_000
```

当前实现使用 `default`（Sonnet）价格进行估算。未来可扩展为根据日志中的模型名称动态选择对应价格。

---

## 四、24 小时滑动窗口

### 4.1 常量定义

```python
RECORD_RETENTION_HOURS = 86400   # 24小时 = 86400秒
HOUR_SECONDS = 3600              # 1小时
DAY_SECONDS = 86400              # 24小时
```

### 4.2 窗口裁剪

每次增量扫描后，系统会裁剪超出 24 小时窗口的旧记录：

```python
cutoff_time = now - RECORD_RETENTION_HOURS
self._accumulated_records = [
    r for r in self._accumulated_records if r.get("timestamp", 0) > cutoff_time
]
```

这是一个内存保护机制：程序长期运行时，旧的 Token 记录会被自动丢弃，防止内存无限增长。

### 4.3 时间窗口统计

`get_stats()` 方法计算两个维度的 Token 使用量：

- **tokens_last_hour**: 最近 1 小时内的总 Token 数（input + output）
- **tokens_last_day**: 最近 24 小时内的总 Token 数（input + output）

```python
hour_ago = now - HOUR_SECONDS
day_ago = now - DAY_SECONDS

tokens_hour = sum(
    r["input_tokens"] + r["output_tokens"]
    for r in records if r.get("timestamp", 0) > hour_ago
)
```

### 4.4 内存上限保护

除滑动窗口外，还有两层额外的内存保护：

| 机制 | 上限 | 作用 |
|------|------|------|
| `_stats_history` 列表 | 1000 条 | 限制历史快照数量 |
| `_accumulated_records` 窗口 | 24 小时 + 10000 条硬限制 | 双重防泄漏 |

```python
self._stats_history = self._stats_history[-MAX_STATS_HISTORY:]
```

---

## 五、缓存机制

### 5.1 内存缓存（10 秒 TTL）

`get_stats()` 方法实现了 10 秒的内存缓存，避免高频调用时重复扫描文件：

```python
STATS_CACHE_TTL = 10  # 秒

if (self._cached_stats and
    now - self._last_scan_time < STATS_CACHE_TTL and
    self._last_scan_time > 0):
    return self._cached_stats
```

缓存命中条件：
1. `_cached_stats` 不为 None（已经计算过至少一次）
2. 距上次扫描不超过 10 秒
3. `_last_scan_time` 大于 0（非初始状态）

### 5.2 持久化缓存（原子写入）

统计数据通过 `token_cache.json` 文件持久化，支持程序重启后恢复历史数据。

**原子写入流程**：

```python
def _save_cache(self):
    cache_file = "token_cache.json"
    tmp_file = cache_file + ".tmp"
    # 1. 写入临时文件
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(self._stats_history[-1000:], f, ensure_ascii=False)
    # 2. 原子替换（os.replace 在 Windows 和 Unix 上都是原子操作）
    os.replace(tmp_file, cache_file)
```

这种两步写入策略防止程序崩溃时损坏缓存文件：如果写入过程中断，只有 `.tmp` 文件被损坏，原始缓存文件保持完整。

### 5.3 缓存加载

程序启动时自动加载缓存：

```python
def _load_cache(self):
    cache_file = "token_cache.json"
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            self._stats_history = json.load(f)
```

---

## 数据流总览

```
日志文件 (.jsonl / .log)
        |
        v
  LogTailer.read_new_lines()    <-- 增量读取，跟踪 position
        |
        v
  TokenTracker._parse_log_line() <-- JSONL解析 → 正则回退
        |
        v
  _accumulated_records[]         <-- 内存中的记录列表
        |
        v
  24小时滑动窗口裁剪             <-- 防止内存泄漏
        |
        v
  get_stats() → TokenStats      <-- 聚合统计 + 10s缓存
        |
        v
  _save_cache()                  <-- 原子写入 token_cache.json
```

---

## 配置示例

```json
{
    "log_paths": [
        "~/.claude/logs/usage.jsonl",
        "/var/log/ai-agent/"
    ],
    "update_interval": 30,
    "auto_discover": true,
    "auto_discover_dirs": [
        "~/.claude/projects/",
        "~/.config/claude/"
    ],
    "auto_discover_pattern": "*.jsonl"
}
```
