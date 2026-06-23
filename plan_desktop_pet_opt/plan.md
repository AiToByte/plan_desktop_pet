# 桌面宠物深度优化 - 执行计划

> 创建时间: 2026-06-23
> 约束: 现有硬件不变，不增加物料成本
> 项目路径: D:\_MyProject\AIProject\DesktopTool\plan_desktop_pet

---

## 优化1: [ ] PSRAM 思考链历史滚动展示（History Roll）

**目标**: 用PSRAM静态链表实现40步思考历史缓冲，展示最近5步，CIE缓动滚动
**修改文件**: `esp32_firmware/src/display_manager.h`, `esp32_firmware/src/display_manager.cpp`, `esp32_firmware/src/main.cpp`, `esp32_firmware/include/config.h`

### 步骤:
- [ ] 1.1 `display_manager.h` 添加 `ThinkingStep` 结构体（timestamp + truncated step string），`ThinkingStepCache` 类声明（PSRAM链表节点, 环形缓冲MAX=40, 滑动窗口VISIBLE=5）
- [ ] 1.2 `display_manager.cpp` 实现 `ThinkingStepCache`（ps_malloc分配节点, addStep追加+淘汰旧节点, getVisibleSteps计算可见5步偏移）
- [ ] 1.3 `display_manager.h` 的 `DisplayData` 结构体添加 `ThinkingStepCache* thinkingHistory;` 指针和 `float scrollOffset; bool needsScroll; unsigned long scrollStartTime;`
- [ ] 1.4 `config.h` 添加 `THINKING_HISTORY_MAX=40`, `THINKING_VISIBLE_COUNT=5`, `SCROLL_DURATION_MS=800`, `THINKING_STEP_TEXT_MAX=64`
- [ ] 1.5 `main.cpp` 的 `handleStatusUpdate` 中 thinking 状态时调用 `g_displayData.thinkingHistory->addStep(info)`
- [ ] 1.6 `display_manager.cpp` 的 thinking 渲染分支：检查 `needsScroll`，用CIE缓动函数 `t*t*(3-2t)` 计算 `scrollOffset`，按行偏移绘制历史文本
- [ ] 1.7 初始化：`setup()` 中 `new ThinkingStepCache()` 分配到PSRAM

---

## 优化2: [ ] .pxl 差分帧编码（Delta Encoding）

**目标**: 像素动画帧间差分编码，仅传输变化像素，降低60-90%传输量
**修改文件**: `pixel_tools/pixel_animator.py`, `esp32_firmware/src/main.cpp`, `esp32_firmware/src/comm_manager.cpp`, `esp32_firmware/include/config.h`

### 步骤:
- [ ] 2.1 `config.h` 定义差分协议：`DELTA_FULL=0x01`, `DELTA_DIFF=0x02`, `COPY=0x00`, `REPEAT=0x01`, `LITERAL=0x02`，`RLE_MAX_RUN=127`, `LITERAL_MAX_LEN=127`
- [ ] 2.2 `pixel_animator.py` 新增 `DeltaCompressor` 类：`encode(prev, curr)` 生成差分帧，`decode(prev, delta)` 还原完整帧
- [ ] 2.3 `pixel_animator.py` 的 `export_pxl_frame()` 累积模式修改：遍历相邻帧调用 DeltaCompressor，首帧 FULL 后续 DIFF
- [ ] 2.4 `main.cpp` 的 `processData` 中 `CMD_PIXEL_DATA` 分支：解析 header 字节判断 FULL vs DIFF，DIFF 时调用解码器还原
- [ ] 2.5 `comm_manager.cpp` 的 `processPixelData`：支持 DIFF 帧解析（复用或提取共享解码函数）
- [ ] 2.6 配置向导 `--configure` 的 HEX 导出保持不变（单帧静态图不走差分）

---

## 优化3: [ ] LovyanGFX DMA 异步块传输（DMA Async Push）

**目标**: 像素渲染拆为4块DMA推送，CPU等待时并行计算，降低CPU占用15-25%
**修改文件**: `esp32_firmware/src/display_manager.cpp`, `esp32_firmware/include/display_manager.h`, `esp32_firmware/include/config.h`

### 步骤:
- [ ] 3.1 `display_manager.h` 定义 `DMXferState` 枚举（DMX_IDLE/DMX_PUSHING/DMX_WAIT_NEXT/DMX_READY），添加 `DMA_XFER_BLOCK_COUNT=4`
- [ ] 3.2 `display_manager.h` 的 `DisplayManager` 类添加：`DMXferState _dmXferState`, `uint8_t _dmNextBlock`, `unsigned long _dmWaitStart`, `bool _dmInFlight`
- [ ] 3.3 `display_manager.cpp` 重构 `updateDisplayPixel()`：DMX_READY 状态下逐块推送（`pushImageDMA`），每块完成后 DMX_WAIT_NEXT，5ms超时推进下一块
- [ ] 3.4 V-Sync同步：pushImageDMA 前等待 `lcd.getScanLine()` 在非消隐区（line > 0 && line < 239）
- [ ] 3.5 `main.cpp` 循环确保 `updateDisplayPixel()` 每帧可多次调用以推进 DMA 状态机

---

## 优化4: [ ] 动态 WiFi DTIM + Modem-Sleep

**目标**: 空闲态自动切换 DTIM10 + Modem-Sleep，待机电流从 30mA 降至 3-8mA
**修改文件**: `esp32_firmware/src/wifi_manager.h`, `esp32_firmware/src/wifi_manager.cpp`, `esp32_firmware/src/main.cpp`, `esp32_firmware/include/config.h`

### 步骤:
- [ ] 4.1 `config.h` 添加省电配置：`IDLE_POWER_MODE=2`, `SLEEP_TARGET_CURRENT_UA=4000`, `DTIM_ACTIVE=1`, `DTIM_IDLE=10`, `IDLE_TIMEOUT_MS=30000`, `WAKE_CHECK_INTERVAL_MS=500`
- [ ] 4.2 `wifi_manager.h` 添加 `PowerMode` 枚举（ACTIVE/MODEM_SLEEP_AUTO/LIGHT_SLEEP），`PowerState` 结构体，`WifiManager` 添加 `PowerState _powerState`
- [ ] 4.3 `wifi_manager.cpp` 实现 `configureModemSleep(mode)`：ACTIVE→`esp_wifi_set_ps(PS_MODEM)` + WiFi.setSleep(true)；MODEM_SLEEP_AUTO→PS_MODEM + DTIM10 + BSS Max Idle 300s；LIGHT_SLEEP→`esp_light_sleep_start()`
- [ ] 4.4 `wifi_manager.cpp` 实现 `updatePowerMode(bool active)`：active→ACTIVE模式 + DTIM1；idle→IDLE_POWER_MODE + DTIM_IDLE
- [ ] 4.5 `main.cpp` 主循环添加空闲检测：累计 `idleMs`，超时调用 `updatePowerMode(false)`；收到数据重置并 `updatePowerMode(true)`
- [ ] 4.6 `main.cpp` 添加定期唤醒检查：每 `WAKE_CHECK_INTERVAL_MS` 检查 pending 任务（动画/OTA），有则提前唤醒

---

## 优化5: [ ] PC端线程健康监护（Thread Health Guardian）

**目标**: 监控核心服务线程存活状态，异常时自动恢复/重启
**修改文件**: `pc_monitor/main.py`

### 步骤:
- [ ] 5.1 `DesktopPetMonitor.__init__()` 中初始化 `self._threads = {}` 和 `self.stop_event = threading.Event()`
- [ ] 5.2 `start()` 中启动各核心线程后保存引用到 `self._threads`
- [ ] 5.3 添加 `_thread_health_check()` 方法：遍历 `_threads` 检查 `is_alive()`，死亡线程 `logger.critical` 报告
- [ ] 5.4 死亡线程处理：`self.stop_event.set()` 通知所有线程清理 → `os.execv(sys.executable, ['python'] + sys.argv)` 重启自身
- [ ] 5.5 启动监护：主循环中定期调用 `_thread_health_check()` 或用 `threading.Timer` 循环

---

## 全局注意事项

1. **ESP32编译验证**: 修改C++后用 `platformio run` 验证编译
2. **Python语法检查**: 修改Python后用 `python -m py_compile` 验证
3. **config.h常量**: 新常量用 `#define` 放在 `// --- Protocol constants ---` 区域
4. **PSRAM**: ThinkingStepCache 必须 `ps_malloc`，析构 `free`
5. **DMA兼容**: `pushImageDMA` 仅 LovyanGFX 驱动可用，`#ifdef` 保护
