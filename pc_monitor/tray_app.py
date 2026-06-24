"""
ESP32 桌面宠物 - 桌面托盘应用
功能：托盘图标 + Token曲线 + Agent指标面板
依赖：pystray, Pillow, matplotlib
"""
import sys
import os
import time
import threading
import tkinter as tk
from tkinter import ttk
import json
from datetime import datetime
from collections import deque

# 可选依赖
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    print("[Tray] pystray/Pillow not available, using tkinter window only")

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[Tray] matplotlib not available, charts disabled")


# ============ Token历史数据 ============

class TokenHistory:
    """Token使用量时序数据（环形缓冲）"""
    def __init__(self, maxlen=120):
        self.timestamps = deque(maxlen=maxlen)
        self.input_tokens = deque(maxlen=maxlen)
        self.output_tokens = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, ts: float, inp: int, out: int):
        """追加一条Token使用记录"""
        with self._lock:
            self.timestamps.append(ts)
            self.input_tokens.append(inp)
            self.output_tokens.append(out)

    def get_recent(self, n=60):
        """获取最近n条Token记录"""
        with self._lock:
            n = min(n, len(self.timestamps))
            return (
                list(self.timestamps)[-n:],
                list(self.input_tokens)[-n:],
                list(self.output_tokens)[-n:]
            )


# ============ 状态面板 ============

class StatusPanel(tk.Toplevel):
    """悬浮状态面板（Token曲线 + Agent指标）"""
    def __init__(self, master, token_history: TokenHistory):
        super().__init__(master)
        self.title("Pet Status")
        self.attributes('-topmost', True)
        self.resizable(False, False)

        self.token_history = token_history

        # 指标标签
        self._create_info_frame()
        # Token曲线
        self._create_chart()

        # 多显示器适配：定位到鼠标所在的显示器
        self._position_on_current_monitor()

        # 支持拖拽移动
        self._drag_data = {'x': 0, 'y': 0}
        self.bind('<Button-1>', self._on_drag_start)
        self.bind('<B1-Motion>', self._on_drag_motion)
        self.bind('<ButtonRelease-1>', self._on_drag_end)

        # 定时刷新
        self._refresh_interval_ms = 2000
        self.after(self._refresh_interval_ms, self._refresh)

    def _create_info_frame(self):
        frame = ttk.LabelFrame(self, text="Agent Metrics", padding=8)
        frame.pack(fill='x', padx=8, pady=4)

        labels = [
            ('Status', 'status_val'),
            ('CPU', 'cpu_val'),
            ('Memory', 'mem_val'),
            ('Uptime', 'uptime_val'),
            ('Crash Count', 'crash_val'),
        ]
        self._vars = {}
        for i, (text, key) in enumerate(labels):
            ttk.Label(frame, text=f"{text}:").grid(row=i // 3, column=(i % 3) * 2, sticky='e', padx=4)
            var = tk.StringVar(value='--')
            ttk.Label(frame, textvariable=var, foreground='blue').grid(row=i // 3, column=(i % 3) * 2 + 1, sticky='w', padx=4)
            self._vars[key] = var

    def _create_chart(self):
        if not HAS_MATPLOTLIB:
            ttk.Label(self, text="[matplotlib not installed]", foreground='gray').pack(pady=20)
            return

        self.fig = Figure(figsize=(4.5, 2), dpi=80, tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Token Usage (recent)")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Tokens")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill='both', expand=True, padx=8, pady=4)

    def update_metrics(self, data: dict):
        """外部调用：更新指标显示"""
        if 'status' in data:
            self._vars['status_val'].set(data['status'])
        if 'cpu' in data:
            self._vars['cpu_val'].set(f"{data['cpu']:.1f}%")
        if 'mem' in data:
            self._vars['mem_val'].set(f"{data['mem']:.0f} MB")
        if 'uptime' in data:
            self._vars['uptime_val'].set(data['uptime'])
        if 'crash_count' in data:
            self._vars['crash_val'].set(str(data['crash_count']))

    def _refresh(self):
        self._update_chart()
        self.after(self._refresh_interval_ms, self._refresh)

    def _update_chart(self):
        if not HAS_MATPLOTLIB:
            return

        times, inps, outs = self.token_history.get_recent(60)
        if len(times) < 2:
            return

        self.ax.clear()
        x = [datetime.fromtimestamp(t).strftime('%H:%M:%S') for t in times]
        self.ax.plot(range(len(x)), inps, label='Input', color='#2196F3', linewidth=1.2)
        self.ax.plot(range(len(x)), outs, label='Output', color='#FF9800', linewidth=1.2)
        self.ax.fill_between(range(len(x)), inps, alpha=0.15, color='#2196F3')
        self.ax.fill_between(range(len(x)), outs, alpha=0.15, color='#FF9800')
        self.ax.legend(loc='upper left', fontsize=8)
        self.ax.set_title("Token Usage (recent)", fontsize=9)
        self.ax.set_ylabel("Tokens", fontsize=8)
        # 只显示首尾时间标签
        if len(x) > 10:
            tick_pos = [0, len(x) // 2, len(x) - 1]
            self.ax.set_xticks(tick_pos)
            self.ax.set_xticklabels([x[i] for i in tick_pos], fontsize=7)
        self.canvas.draw_idle()

    def _get_monitor_bounds(self, mx, my):
        """[OPT-5] 用ctypes获取鼠标所在单显示器的精确工作区边界"""
        try:
            import ctypes
            from ctypes import wintypes
            
            # MONITORINFOEXW 结构体
            class MONITORINFOEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]
            
            MONITOR_DEFAULTTONEAREST = 2
            
            # 从鼠标坐标获取最近的显示器句柄
            pt = wintypes.POINT(mx, my)
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            
            if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                # rcWork 是排除任务栏的工作区
                return (mi.rcWork.left, mi.rcWork.top,
                        mi.rcWork.right, mi.rcWork.bottom)
        except Exception:
            pass
        return None

    def _position_on_current_monitor(self):
        """[OPT-5] 多显示器适配：用单显示器边界钉扎窗口位置"""
        self.update_idletasks()  # 确保winfo获取准确尺寸
        panel_w, panel_h = 400, 300
        # 获取鼠标当前位置（跨显示器准确）
        mx, my = self.winfo_pointerx(), self.winfo_pointery()
        
        # 尝试获取鼠标所在单显示器的工作区边界
        bounds = self._get_monitor_bounds(mx, my)
        
        if bounds:
            mon_l, mon_t, mon_r, mon_b = bounds
            mon_w = mon_r - mon_l
            mon_h = mon_b - mon_t
            # 在鼠标右下方偏移20px
            x = mx + 20
            y = my + 20
            # 钉扎到单显示器可视区域内（确保不超出当前显示器边缘）
            x = max(mon_l, min(x, mon_r - panel_w))
            y = max(mon_t, min(y, mon_b - panel_h))
        else:
            # fallback：单显示器或ctypes失败，用tkinter方法居中
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            x = (screen_w - panel_w) // 2
            y = (screen_h - panel_h) // 2
        
        x = max(x, 0)
        y = max(y, 0)
        self.geometry(f"{panel_w}x{panel_h}+{x}+{y}")

    def _on_drag_start(self, event):
        """拖拽开始：记录鼠标在窗口内的偏移"""
        self._drag_data['x'] = event.x
        self._drag_data['y'] = event.y

    def _on_drag_motion(self, event):
        """拖拽移动：更新窗口位置"""
        dx = event.x - self._drag_data['x']
        dy = event.y - self._drag_data['y']
        x = self.winfo_x() + dx
        y = self.winfo_y() + dy
        self.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event):
        """[OPT-MAG] 拖拽释放：屏幕边缘磁吸检测"""
        SNAP_THRESHOLD = 20  # 像素阈值
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        
        # 获取当前显示器工作区边界
        bounds = self._get_monitor_bounds(x + w // 2, y + h // 2)
        if not bounds:
            return  # 获取不到则跳过
        mon_left, mon_top, mon_right, mon_bottom = bounds
        
        # 左边缘吸附
        if abs(x - mon_left) < SNAP_THRESHOLD:
            x = mon_left
        # 右边缘吸附
        elif abs((x + w) - mon_right) < SNAP_THRESHOLD:
            x = mon_right - w
        
        # 上边缘吸附
        if abs(y - mon_top) < SNAP_THRESHOLD:
            y = mon_top
        # 下边缘吸附
        elif abs((y + h) - mon_bottom) < SNAP_THRESHOLD:
            y = mon_bottom - h
        
        self.geometry(f"+{x}+{y}")


# ============ 托盘图标 ============

def create_icon_image(color=(0, 150, 136)):
    """创建简单托盘图标"""
    img = Image.new('RGB', (64, 64), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # 画一个圆形宠物图标
    draw.ellipse([8, 8, 56, 56], fill=color)
    # 眼睛
    draw.ellipse([20, 20, 28, 28], fill='white')
    draw.ellipse([36, 20, 44, 28], fill='white')
    draw.ellipse([22, 22, 26, 26], fill='black')
    draw.ellipse([38, 22, 42, 26], fill='black')
    # 嘴巴
    draw.arc([24, 32, 40, 46], start=0, end=180, fill='white', width=2)
    return img


class TrayApp:
    """系统托盘应用"""
    def __init__(self, on_exit_callback=None):
        self.root = tk.Tk()
        self.root.withdraw()  # 隐藏主窗口
        self.root.title("Pet Controller")

        self.token_history = TokenHistory()
        self.panel = None
        self.tray_icon = None
        self.on_exit_callback = on_exit_callback

    def show_panel(self):
        """显示/隐藏Agent指标面板"""
        if self.panel is None or not self.panel.winfo_exists():
            self.panel = StatusPanel(self.root, self.token_history)
        else:
            self.panel.deiconify()
            self.panel.lift()

    def update_metrics(self, data: dict):
        """线程安全：更新指标（从通信线程调用）"""
        self.root.after(0, self._do_update, data)

    def _do_update(self, data: dict):
        # 更新token历史
        if 'input_tokens' in data and 'output_tokens' in data:
            self.token_history.append(time.time(), data['input_tokens'], data['output_tokens'])
        # 更新面板
        if self.panel and self.panel.winfo_exists():
            self.panel.update_metrics(data)

    def _on_show_panel(self, icon=None, item=None):
        self.root.after(0, self.show_panel)

    def _on_exit(self, icon=None, item=None):
        if self.on_exit_callback:
            self.on_exit_callback()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def run(self):
        """启动托盘+主循环"""
        if HAS_TRAY:
            icon_img = create_icon_image()
            menu = pystray.Menu(
                pystray.MenuItem('Show Panel', self._on_show_panel, default=True),
                pystray.MenuItem('Exit', self._on_exit)
            )
            self.tray_icon = pystray.Icon('DeskPet', icon_img, 'ESP32 Pet', menu)
            # 在线程中运行pystray
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.show_panel()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self.root.mainloop()


# ============ 入口 ============

if __name__ == '__main__':
    app = TrayApp()

    # 模拟数据（测试用）
    def simulate():
        """模拟Agent数据更新（独立测试用）"""
        import random
        while True:
            app.update_metrics({
                'status': random.choice(['Idle', 'Working', 'Auth']),
                'cpu': random.uniform(5, 80),
                'mem': random.uniform(100, 500),
                'uptime': f"{random.randint(0, 24)}h {random.randint(0, 59)}m",
                'crash_count': 0,
                'input_tokens': random.randint(100, 2000),
                'output_tokens': random.randint(50, 800),
            })
            time.sleep(2)

    threading.Thread(target=simulate, daemon=True).start()
    app.run()
