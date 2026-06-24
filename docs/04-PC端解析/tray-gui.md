# 托盘 GUI 实现

> 源文件: `pc_monitor/tray_app.py`

本文档描述桌面宠物 PC 端的图形用户界面实现，包括系统托盘图标、悬浮状态面板、多显示器适配以及线程安全的更新机制。整个 GUI 系统由三个核心组件构成：`TrayApp`（托盘控制器）、`StatusPanel`（状态面板）和 `TokenHistory`（数据缓冲）。

---

## 一、pystray 系统托盘图标

### 1.1 依赖与降级策略

托盘功能依赖 `pystray` 和 `Pillow` 两个可选库：

```python
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    print("[Tray] pystray/Pillow not available, using tkinter window only")
```

当依赖不可用时，程序不会崩溃，而是降级为纯 tkinter 窗口模式。`HAS_TRAY` 标志在后续逻辑中控制是否启动托盘功能。

### 1.2 图标绘制

`create_icon_image()` 函数用 Pillow 的 `ImageDraw` 在 64x64 画布上绘制一个简易的宠物图标：

```python
def create_icon_image(color=(0, 150, 136)):
    img = Image.new('RGB', (64, 64), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # 圆形身体
    draw.ellipse([8, 8, 56, 56], fill=color)
    # 左眼
    draw.ellipse([20, 20, 28, 28], fill='white')
    draw.ellipse([22, 22, 26, 26], fill='black')
    # 右眼
    draw.ellipse([36, 20, 44, 28], fill='white')
    draw.ellipse([38, 22, 42, 26], fill='black')
    # 嘴巴弧线
    draw.arc([24, 32, 40, 46], start=0, end=180, fill='white', width=2)
    return img
```

图标由三个部分组成：
- 青色圆形背景（默认 `#009688`）
- 两个白色椭圆眼睛 + 黑色瞳孔
- 一条白色弧线嘴巴

### 1.3 托盘菜单

`pystray.Menu` 定义了右键菜单项：

```python
menu = pystray.Menu(
    pystray.MenuItem('Show Panel', self._on_show_panel, default=True),
    pystray.MenuItem('Exit', self._on_exit)
)
```

| 菜单项 | 行为 |
|--------|------|
| Show Panel（默认） | 左键单击托盘图标或右键选择此项，显示/激活状态面板 |
| Exit | 触发退出回调，停止托盘图标，销毁 tkinter 主窗口 |

### 1.4 线程模型

pystray 的事件循环与 tkinter 的主循环不能在同一线程中运行。解决方案是将 pystray 放在独立的守护线程中：

```python
threading.Thread(target=self.tray_icon.run, daemon=True).start()
```

- pystray 线程：处理系统托盘的鼠标事件（单击、右键等）
- 主线程：运行 tkinter 的 `mainloop()`，处理窗口事件和定时刷新

---

## 二、tkinter StatusPanel

### 2.1 面板结构

`StatusPanel` 继承自 `tk.Toplevel`，是一个独立的浮动窗口：

```
StatusPanel (tk.Toplevel)
    |
    +-- LabelFrame "Agent Metrics" (指标标签区域)
    |       |
    |       +-- Status:    status_val   (StringVar)
    |       +-- CPU:       cpu_val      (StringVar)
    |       +-- Memory:    mem_val      (StringVar)
    |       +-- Uptime:    uptime_val   (StringVar)
    |       +-- Crash Count: crash_val  (StringVar)
    |
    +-- matplotlib FigureCanvas (Token 使用曲线)
            |
            +-- Input tokens 曲线 (蓝色 #2196F3)
            +-- Output tokens 曲线 (橙色 #FF9800)
            +-- 填充区域 (alpha=0.15)
```

### 2.2 指标标签

五个指标使用 `ttk.Label` + `tk.StringVar` 的组合，支持从外部线程安全更新：

```python
labels = [
    ('Status', 'status_val'),       # Agent 状态 (Idle/Working/Auth)
    ('CPU', 'cpu_val'),             # CPU 使用率
    ('Memory', 'mem_val'),          # 内存使用量
    ('Uptime', 'uptime_val'),       # 运行时间
    ('Crash Count', 'crash_val'),   # 崩溃次数
]
```

标签采用网格布局，每行 3 个指标（6 个控件 = 3 对 label + value）。

### 2.3 matplotlib Token 曲线

当 `matplotlib` 可用时，面板底部显示一个实时更新的 Token 使用量折线图：

```python
self.fig = Figure(figsize=(4.5, 2), dpi=80, tight_layout=True)
self.ax = self.fig.add_subplot(111)
```

图表特性：
- **双曲线**: Input tokens（蓝色）和 Output tokens（橙色）
- **填充区域**: 曲线下方半透明填充，增强视觉效果
- **时间轴优化**: 当数据点超过 10 个时，只显示首、中、尾三个时间标签，避免 X 轴拥挤
- **刷新间隔**: 每 2 秒更新一次（`_refresh_interval_ms = 2000`）

### 2.4 matplotlib 降级

当 matplotlib 不可用时，显示灰色提示文本：

```python
if not HAS_MATPLOTLIB:
    ttk.Label(self, text="[matplotlib not installed]", foreground='gray').pack(pady=20)
    return
```

---

## 三、多显示器适配

### 3.1 问题背景

Windows 多显示器环境下，tkinter 的 `winfo_screenwidth()` 只返回主显示器的分辨率。如果用户在副显示器上点击托盘图标，面板可能出现在错误的显示器上。

### 3.2 Win32 API 方案

`_get_monitor_bounds()` 方法通过 ctypes 调用 Win32 API 获取鼠标所在显示器的精确工作区边界：

```python
def _get_monitor_bounds(self, mx, my):
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),   # 显示器完整区域
            ("rcWork", wintypes.RECT),       # 工作区（排除任务栏）
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    # 从鼠标坐标获取最近的显示器句柄
    pt = wintypes.POINT(mx, my)
    hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return (mi.rcWork.left, mi.rcWork.top,
                mi.rcWork.right, mi.rcWork.bottom)
    return None
```

关键 Win32 API 调用：

| API | 作用 |
|-----|------|
| `MonitorFromPoint` | 根据坐标点获取最近的显示器句柄 |
| `GetMonitorInfoW` | 获取显示器的矩形区域信息 |
| `MONITOR_DEFAULTTONEAREST` | 当点不在任何显示器上时，返回最近的显示器 |

返回值使用 `rcWork`（工作区）而非 `rcMonitor`（完整区域），自动排除任务栏占据的空间。

### 3.3 面板定位策略

`_position_on_current_monitor()` 方法实现了智能定位：

```python
def _position_on_current_monitor(self):
    mx, my = self.winfo_pointerx(), self.winfo_pointery()
    bounds = self._get_monitor_bounds(mx, my)

    if bounds:
        mon_l, mon_t, mon_r, mon_b = bounds
        x = mx + 20  # 鼠标右下方偏移 20px
        y = my + 20
        # 钉扎到显示器可视区域内
        x = max(mon_l, min(x, mon_r - panel_w))
        y = max(mon_t, min(y, mon_b - panel_h))
    else:
        # fallback: 居中显示
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - panel_w) // 2
        y = (screen_h - panel_h) // 2
```

**定位规则**：
1. 默认出现在鼠标右下方 20px 处
2. 如果超出当前显示器右边缘，向左移动到边缘内
3. 如果超出当前显示器下边缘，向上移动到边缘内
4. 如果 ctypes 调用失败（非 Windows 系统等），回退到主显示器居中显示

---

## 四、窗口拖拽与边缘吸附

### 4.1 拖拽实现

通过绑定鼠标事件实现窗口拖拽：

```python
self._drag_data = {'x': 0, 'y': 0}
self.bind('<Button-1>', self._on_drag_start)      # 按下
self.bind('<B1-Motion>', self._on_drag_motion)     # 拖动
self.bind('<ButtonRelease-1>', self._on_drag_end)  # 释放
```

**拖拽开始**：记录鼠标在窗口内的相对偏移量：

```python
def _on_drag_start(self, event):
    self._drag_data['x'] = event.x
    self._drag_data['y'] = event.y
```

**拖拽移动**：根据鼠标移动量更新窗口位置：

```python
def _on_drag_motion(self, event):
    dx = event.x - self._drag_data['x']
    dy = event.y - self._drag_data['y']
    x = self.winfo_x() + dx
    y = self.winfo_y() + dy
    self.geometry(f"+{x}+{y}")
```

### 4.2 边缘磁吸（Snap）

拖拽释放时触发磁吸检测，当窗口边缘接近显示器边缘时自动对齐：

```python
def _on_drag_end(self, event):
    SNAP_THRESHOLD = 20  # 像素阈值

    # 获取当前显示器工作区边界
    bounds = self._get_monitor_bounds(x + w // 2, y + h // 2)
    if not bounds:
        return
    mon_left, mon_top, mon_right, mon_bottom = bounds

    # 水平方向磁吸
    if abs(x - mon_left) < SNAP_THRESHOLD:
        x = mon_left                    # 左边缘吸附
    elif abs((x + w) - mon_right) < SNAP_THRESHOLD:
        x = mon_right - w               # 右边缘吸附

    # 垂直方向磁吸
    if abs(y - mon_top) < SNAP_THRESHOLD:
        y = mon_top                     # 上边缘吸附
    elif abs((y + h) - mon_bottom) < SNAP_THRESHOLD:
        y = mon_bottom - h              # 下边缘吸附
```

**磁吸规则**：

| 方向 | 条件 | 行为 |
|------|------|------|
| 左 | `\|x - mon_left\| < 20px` | 窗口左边缘对齐显示器左边缘 |
| 右 | `\|(x+w) - mon_right\| < 20px` | 窗口右边缘对齐显示器右边缘 |
| 上 | `\|y - mon_top\| < 20px` | 窗口上边缘对齐显示器上边缘（任务栏下方） |
| 下 | `\|(y+h) - mon_bottom\| < 20px` | 窗口下边缘对齐显示器下边缘（任务栏上方） |

磁吸检测使用窗口中心点确定所属显示器，确保在显示器边界附近拖拽时行为正确。

---

## 五、线程安全更新

### 5.1 问题描述

tkinter 不是线程安全的——只能在创建它的线程（主线程）中修改 UI 控件。然而 Token 数据和 Agent 指标来自通信线程（BLE/串口/BLE），直接从其他线程调用 `update_metrics()` 会导致不可预测的崩溃。

### 5.2 root.after() 调度

`TrayApp.update_metrics()` 使用 `root.after(0, ...)` 将更新操作调度到主线程执行：

```python
def update_metrics(self, data: dict):
    """线程安全：更新指标（从通信线程调用）"""
    self.root.after(0, self._do_update, data)
```

`root.after(0, callback)` 不会立即执行 `callback`，而是将其放入 tkinter 的事件队列，在下一次主循环迭代时由主线程执行。这保证了所有 UI 操作都在主线程中进行。

### 5.3 托盘事件的线程转换

pystray 运行在独立线程中，其菜单回调也需要通过 `root.after()` 转换到主线程：

```python
def _on_show_panel(self, icon=None, item=None):
    self.root.after(0, self.show_panel)

def _on_exit(self, icon=None, item=None):
    if self.on_exit_callback:
        self.on_exit_callback()
    if self.tray_icon:
        self.tray_icon.stop()
    self.root.after(0, self.root.destroy)
```

### 5.4 TokenHistory 的线程安全

`TokenHistory` 类使用 `threading.Lock` 保护共享数据：

```python
class TokenHistory:
    def __init__(self, maxlen=120):
        self.timestamps = deque(maxlen=maxlen)
        self.input_tokens = deque(maxlen=maxlen)
        self.output_tokens = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, ts, inp, out):
        with self._lock:
            self.timestamps.append(ts)
            self.input_tokens.append(inp)
            self.output_tokens.append(out)

    def get_recent(self, n=60):
        with self._lock:
            n = min(n, len(self.timestamps))
            return (list(self.timestamps)[-n:],
                    list(self.input_tokens)[-n:],
                    list(self.output_tokens)[-n:])
```

使用 `deque(maxlen=120)` 实现环形缓冲区，自动丢弃最旧的数据点，内存使用固定。

---

## 六、TrayApp 主控制器

### 6.1 初始化

```python
class TrayApp:
    def __init__(self, on_exit_callback=None):
        self.root = tk.Tk()
        self.root.withdraw()              # 隐藏主窗口
        self.root.title("Pet Controller")
        self.token_history = TokenHistory()
        self.panel = None
        self.tray_icon = None
        self.on_exit_callback = on_exit_callback
```

`root.withdraw()` 隐藏 tkinter 主窗口——用户只看到托盘图标和状态面板，不看到空白的主窗口。

### 6.2 启动流程

```python
def run(self):
    # 1. 创建托盘图标（如果依赖可用）
    if HAS_TRAY:
        icon_img = create_icon_image()
        menu = pystray.Menu(...)
        self.tray_icon = pystray.Icon('DeskPet', icon_img, 'ESP32 Pet', menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    # 2. 显示状态面板
    self.show_panel()

    # 3. 注册窗口关闭协议
    self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

    # 4. 进入 tkinter 主循环
    self.root.mainloop()
```

### 6.3 数据更新流程

```
通信线程 (BLE/串口)
        |
        |  app.update_metrics(data)
        v
  TrayApp.update_metrics()
        |
        |  root.after(0, _do_update, data)
        v
  主线程 _do_update()
        |
        +-- token_history.append(ts, input, output)
        |
        +-- panel.update_metrics(data)  → 更新标签
        |
        +-- panel._refresh() (定时)     → 更新图表
```

---

## 七、可选依赖矩阵

| 功能 | 依赖 | 无依赖时的行为 |
|------|------|---------------|
| 系统托盘图标 | `pystray` + `Pillow` | 降级为纯 tkinter 窗口 |
| Token 折线图 | `matplotlib` | 显示 "[matplotlib not installed]" 提示 |
| 多显示器适配 | `ctypes`（标准库） | 回退到主显示器居中显示 |

程序在任何依赖缺失的情况下都不会崩溃，实现了优雅降级。
