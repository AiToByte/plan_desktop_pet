# 贡献指南

感谢你对桌面电子宠物项目的关注。本文档说明如何报告问题、提交代码和参与项目协作。

---

## 一、如何报告 Bug

### 1.1 提交前检查

在创建 Issue 之前，请先：

1. 搜索 [已有 Issues](https://github.com/AiToByte/plan_desktop_pet/issues)，确认问题未被报告
2. 确认问题可复现（尝试重启程序、重新烧录固件等基本排查）
3. 收集必要的环境信息

### 1.2 Issue 模板

请按以下结构填写 Bug 报告：

```markdown
## 环境信息
- 操作系统: Windows 11 / macOS 14 / Ubuntu 22.04
- Python 版本: 3.11.x
- ESP32 开发板: 微雪 ESP32-S3 1.54inch LCD
- 固件版本: git commit hash 或版本号

## 问题描述
简要描述遇到的问题

## 复现步骤
1. 执行命令 `python pc_monitor/tray_app.py`
2. 等待 ESP32 连接
3. 观察到...

## 期望行为
描述你期望的正确行为

## 实际行为
描述实际发生的情况

## 日志/截图
附上串口日志、PC 端控制台输出或截图
```

### 1.3 日志收集

**ESP32 串口日志**：

```bash
pio device monitor --baud 115200 | tee esp32_log.txt
```

**PC 端日志**：

PC 端使用 Python `logging` 模块，默认输出到控制台。如需文件日志，可在配置中启用 `file_handler`。

---

## 二、如何提交 PR

### 2.1 Fork 与克隆

```bash
# 1. 在 GitHub 上 Fork 仓库
# 2. 克隆你的 Fork
git clone https://github.com/<your-username>/plan_desktop_pet.git
cd plan_desktop_pet

# 3. 添加上游远程仓库
git remote add upstream https://github.com/AiToByte/plan_desktop_pet.git

# 4. 保持与上游同步
git fetch upstream
git rebase upstream/main
```

### 2.2 开发流程

```bash
# 1. 从最新 main 创建功能分支
git checkout -b feat/my-feature

# 2. 开发、测试、提交（见下方代码审查标准）
# ...

# 3. 推送到你的 Fork
git push -u origin feat/my-feature

# 4. 在 GitHub 创建 Pull Request，目标分支为 upstream/main
```

### 2.3 PR 描述模板

```markdown
## 变更说明
简要描述本次 PR 的目的和内容

## 变更类型
- [ ] 新功能 (feat)
- [ ] Bug 修复 (fix)
- [ ] 重构 (refactor)
- [ ] 文档 (docs)
- [ ] 测试 (test)

## 影响范围
- [ ] ESP32 固件
- [ ] PC 端程序
- [ ] 像素工具

## 测试情况
- [ ] 已通过本地测试
- [ ] 已在 ESP32 硬件上验证
- [ ] 已添加新测试用例

## 关联 Issue
Closes #<issue-number>
```

### 2.4 PR 注意事项

- 保持 PR 范围聚焦，一个 PR 解决一个问题
- 如变更较大，拆分为多个小 PR 逐步提交
- 确保 CI 检查通过（lint、类型检查、测试）
- 响应 Code Review 反馈，及时修正问题

---

## 三、代码审查标准

### 3.1 审查检查清单

提交前请自查：

- [ ] 代码可读且命名良好
- [ ] 函数聚焦（建议 < 50 行）
- [ ] 文件内聚（建议 < 800 行）
- [ ] 无深层嵌套（> 4 层时使用提前返回）
- [ ] 错误显式处理，不静默吞掉异常
- [ ] 无硬编码密钥或凭据
- [ ] 无 `print` 调试语句（使用 `logging` 模块）
- [ ] 新功能有对应测试

### 3.2 审查严重级别

| 级别 | 含义 | 行动 |
|------|------|------|
| CRITICAL | 安全漏洞或数据丢失风险 | 必须修复后才能合并 |
| HIGH | Bug 或重大质量问题 | 应在合并前修复 |
| MEDIUM | 可维护性问题 | 建议修复 |
| LOW | 风格或次要建议 | 可选修复 |

### 3.3 安全审查触发条件

以下变更需额外安全审查：

- 认证或授权逻辑
- 用户输入处理
- 外部 API 调用（密钥管理）
- 文件系统操作（路径遍历风险）
- 网络通信协议

---

## 四、提交信息格式

### 4.1 Conventional Commits 规范

```
<type>(<scope>): <description>

<body>

<footer>
```

**type**（必填）：

| 类型 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变外部行为） |
| `docs` | 文档更新 |
| `test` | 添加或修改测试 |
| `chore` | 构建工具、依赖管理等 |
| `perf` | 性能优化 |
| `ci` | CI/CD 配置变更 |
| `style` | 代码格式（不影响逻辑） |

**scope**（选填）：

- `esp32` - ESP32 固件相关
- `pc` - PC 端程序相关
- `pixel` - 像素工具相关
- `comm` - 通信模块相关
- `display` - 显示模块相关

### 4.2 示例

```
feat(esp32): add night shift color temperature filter

Implement warm color matrix based on NTP time, smooth transition
during 20:00-06:00 window using EMA coefficient.

Closes #42
```

```
fix(pc): prevent token tracker memory leak in long-running sessions

Limit _stats_history to 1000 entries and _accumulated_records to
10000 entries using sliding window.
```

```
refactor(pixel): extract delta encoding into DeltaCompressor class

No behavior change. Extract inline delta logic from gif_to_pxl into
a reusable DeltaCompressor with encode/decode static methods.
```

### 4.3 提交信息规则

- 标题行不超过 72 字符
- 标题使用祈使语气（"add" 而非 "added"）
- 标题首字母小写
- 正文说明 **做了什么** 和 **为什么**，而非怎么做
- 关联 Issue 使用 `Closes #123` 或 `Fixes #123`

---

## 五、分支策略

### 5.1 分支模型

```
main (稳定发布)
  |
  +-- feat/night-shift-filter   (功能分支)
  +-- fix/token-memory-leak     (修复分支)
  +-- docs/api-reference        (文档分支)
```

### 5.2 分支命名规范

| 模式 | 用途 | 示例 |
|------|------|------|
| `feat/<name>` | 新功能 | `feat/weather-icons` |
| `fix/<name>` | Bug 修复 | `fix/serial-reconnect` |
| `refactor/<name>` | 重构 | `refactor/comm-module` |
| `docs/<name>` | 文档 | `docs/api-reference` |
| `test/<name>` | 测试 | `test/agent-monitor` |
| `chore/<name>` | 杂务 | `chore/update-deps` |

### 5.3 合并策略

- 功能分支通过 PR 合并到 `main`
- 合并前必须通过 Code Review
- 合并后删除功能分支
- `main` 分支保持可编译、可运行状态

### 5.4 同步上游

如果你的 Fork 落后于上游：

```bash
git fetch upstream
git rebase upstream/main

# 如有冲突，解决后继续
git rebase --continue

# 强制推送更新后的分支（仅限自己的功能分支）
git push --force-with-lease
```

---

## 附录：开发环境快速启动

```bash
# 克隆仓库
git clone https://github.com/AiToByte/plan_desktop_pet.git
cd plan_desktop_pet

# Python 环境
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# ESP32 固件（需要 PlatformIO）
cd esp32_firmware
pio run                         # 编译
pio run --target upload          # 烧录

# 运行测试
cd ..
python -m pytest tests/ -v
```
