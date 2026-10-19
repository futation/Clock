import tkinter as tk
from tkinter import ttk, messagebox
import time
import sys
import os

# Win32 常量（自定义窗口框架用）
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HTCLIENT = 1
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
SM_CXSIZEFRAME = 32
SM_CXPADDEDBORDER = 92


class TimerApp:
    # ---- 最小窗口尺寸（96DPI 逻辑像素，实际会乘屏幕缩放系数）----
    # 手动调这两个值决定最小窗口多大；程序打开时即为该尺寸且无法再缩小
    # 当前值经实测校准：125% 缩放下窗口客户区 = 345x291 物理像素
    MIN_W = 261.6
    MIN_H = 232.2

    # 标题栏配色（浅色，与界面主体一致；要微调颜色就改这里的值）
    TB_BG = "#F0F0F0"          # 标题栏背景
    TB_FG = "#1B1B1B"          # 标题栏文字/按钮颜色
    TB_HOVER_BG = "#DADADA"    # 按钮悬停背景
    CLOSE_HOVER_BG = "#E81123" # 关闭键悬停红（通用）
    CLOSE_HOVER_FG = "#FFFFFF"
    PIN_ON_FG = "#0067C0"      # 图钉置顶时的高亮蓝（浅底用深蓝）

    # Win10/11 原生标题栏字形（Segoe MDL2 Assets），保证与系统按钮同比例
    CAPTION_FONT = "Segoe MDL2 Assets"
    GLYPH_PIN = "📌"           # 图钉（置顶时变蓝色）
    GLYPH_MIN = "\uE921"       # ChromeMinimize
    GLYPH_MAX = "\uE922"       # ChromeMaximize
    GLYPH_RESTORE = "\uE923"   # ChromeRestore（最大化时显示）
    GLYPH_CLOSE = "\uE8BB"     # ChromeClose

    def __init__(self, root):
        self.root = root
        self.root.title("定时器")
        # DPI 感知进程下 tk 像素=物理像素，按实际 DPI 缩放初始/最小窗口尺寸
        try:
            s = self.root.winfo_fpixels("1i") / 96.0
        except Exception:
            s = 1.0
        self.root.geometry(f"{round(400 * s)}x{round(330 * s)}")  # 占位，稍后按内容请求尺寸校正
        self.root.configure(bg=self.TB_BG)

        # 设置窗口图标（兼容源码运行与 PyInstaller 单文件解压目录 _MEIPASS）
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            self.root.iconbitmap(default=os.path.join(base, "Clock.ico"))
        except Exception:
            pass

        # 控制变量
        self.is_running = False
        self.is_countdown = True   # True为倒计时，False为正计时
        self.is_alarm = False      # 闹钟模式
        self.total_seconds = 0  # 总秒数（用于倒计时）
        self.elapsed_seconds = 0  # 已过秒数（用于正计时）
        self.start_time = 0  # 开始时间（时间戳）
        self.blink_on = False
        self.blink_timer = None
        self.timer_id = None  # 用于取消定时器
        self.is_countdown_finished = False  # 标记倒计时是否结束
        self.alarm_target_ts = 0  # 闹钟触发时刻（时间戳），0表示未设定
        self.saved_countdown_input = "00:25:00"  # 倒计时模式记住的输入栏内容
        self._clock_tick_id = None  # 闹钟模式的实时时钟刷新定时器

        # 置顶状态变量
        self.topmost_var = tk.BooleanVar(value=False)

        # 设置字体
        self.normal_font = ("Arial", 10)
        self.large_font = ("Arial", 30)
        self.huge_font = ("Arial", 72)

        # Windows：去掉系统标题栏，自绘标题栏（含置顶图钉按钮）
        self._win32_ok = self._setup_native_frame()

        # 创建UI
        if self._win32_ok:
            self._create_titlebar()
        self.create_widgets()

        # 绑定窗口缩放事件
        self.root.bind("<Configure>", self.on_resize)

        # 初始化字体大小（按设计逻辑高度 330 计算）
        self.update_font_size(width=round(400 * s), height=round(330 * s))

        # 冻结几何传播：窗口大小只由用户拖拽决定，字体自适应不再反向推动窗口
        # （否则拖动缩小时字体与窗口互相推挤，大数字会一直抖动）
        self.root.grid_propagate(False)

        # 打开尺寸 = 最小尺寸（MIN_W/MIN_H，类顶部常量可手动调）
        self.root.minsize(round(self.MIN_W * s), round(self.MIN_H * s))
        self.root.geometry(f"{round(self.MIN_W * s)}x{round(self.MIN_H * s)}")

    # ---------------- Win32 自定义窗口框架 ----------------

    def _setup_native_frame(self):
        """拦截 WM_NCCALCSIZE / WM_NCHITTEST 去掉系统标题栏，
        同时保留原生拖拽、边缘缩放、Aero Snap、任务栏与阴影。
        任何一步失败都回退为系统标题栏（置顶选项退化为普通复选框）。"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            self._ctypes = ctypes
            self._wintypes = wintypes

            # 强制完成窗口创建，否则 GetParent(winfo_id()) 拿不到有效句柄
            self.root.update_idletasks()

            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
            try:
                self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            except OSError:
                self.dwmapi = None

            # tk 8.6.9+（Python 3.8+）默认进程级 DPI 感知：tk 像素≈物理像素
            dpi = 96
            if hasattr(self.user32, "GetDpiForWindow"):
                dpi = self.user32.GetDpiForWindow(self._hwnd_of(self.root)) or 96
            self._scale = dpi / 96.0
            self._tk_to_phys = 1.0 if self.root.winfo_fpixels("1i") > 96 else self._scale
            self._ui_scale = self._scale if self._tk_to_phys == 1.0 else 1.0
            self._titlebar_h_phys = 0

            LRESULT = ctypes.c_ssize_t
            # wparam/lparam 必须用 c_void_p：部分消息的值超出 c_size_t/c_ssize_t
            # 范围会导致回调 OverflowError（拦截完全失效）
            self._subclassproc_type = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, ctypes.c_uint,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.c_size_t)

            hwnd = self._hwnd_of(self.root)
            if not hwnd:
                return False
            self._hwnd = hwnd

            self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self.user32.IsZoomed.argtypes = [wintypes.HWND]
            self.user32.IsZoomed.restype = wintypes.BOOL
            self.comctl32.SetWindowSubclass.argtypes = [
                wintypes.HWND, self._subclassproc_type, ctypes.c_uint, ctypes.c_size_t]
            self.comctl32.SetWindowSubclass.restype = wintypes.BOOL
            self.comctl32.DefSubclassProc.argtypes = [
                wintypes.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            self.comctl32.DefSubclassProc.restype = LRESULT

            self._main_proc_ref = self._subclassproc_type(self._wnd_proc)
            if not self.comctl32.SetWindowSubclass(hwnd, self._main_proc_ref, 1, 0):
                return False
            self._defsubclass = self.comctl32.DefSubclassProc

            # 窗口可能在子类安装前已映射，错过首次 WM_NCCALCSIZE；
            # FRAMECHANGED 强制系统按新拦截逻辑重算非客户区（去掉系统标题栏）
            self.user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self.user32.SetWindowPos(
                hwnd, wintypes.HWND(None), 0, 0, 0, 0,
                0x1 | 0x2 | 0x4 | 0x10 | 0x20)  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED

            # 原生缩放边框厚度，作为边缘命中区域
            self._edge = (self.user32.GetSystemMetrics(SM_CXSIZEFRAME)
                          + self.user32.GetSystemMetrics(SM_CXPADDEDBORDER))

            # tk 的客户区被 TkChild 子窗口层层覆盖，真实鼠标的命中测试先落在子窗口上。
            # 必须让根 TkChild 在标题栏带/缩放边框带返回 HTTRANSPARENT，
            # 命中才会继续落到顶层窗口，由 _wnd_proc 给出 HTCAPTION/边缘码。
            # 否则窗口能看不能拖、不能缩放。
            self._inner_hwnd = wintypes.HWND(self.root.winfo_id())
            self._inner_proc_ref = self._subclassproc_type(self._inner_wnd_proc)
            if not self.comctl32.SetWindowSubclass(self._inner_hwnd, self._inner_proc_ref, 3, 0):
                return False

            # Win11 圆角（可选，失败忽略）
            if self.dwmapi is not None:
                try:
                    pref = ctypes.c_int(2)  # DWMWCP_ROUND
                    self.dwmapi.DwmSetWindowAttribute(
                        hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
                except Exception:
                    pass
            return True
        except Exception:
            # 回退为系统标题栏；打印原因便于诊断
            import traceback
            traceback.print_exc()
            return False

    def _hwnd_of(self, widget):
        try:
            return self._wintypes.HWND(self.user32.GetParent(widget.winfo_id()))
        except Exception:
            return None

    def _wnd_proc(self, hwnd, msg, wparam, lparam, uid, ref):
        try:
            if msg == WM_NCCALCSIZE and wparam:
                # 客户区铺满整个窗口（去掉非客户区）；最大化时缩进边框厚度
                if self.user32.IsZoomed(hwnd):
                    f = self._edge
                    rect = self._ctypes.cast(
                        lparam, self._ctypes.POINTER(self._wintypes.RECT)).contents
                    rect.left += f
                    rect.top += f
                    rect.right -= f
                    rect.bottom -= f
                return 0
            if msg == WM_NCHITTEST:
                return self._hit_test(hwnd, lparam)
        except Exception:
            pass
        return self._defsubclass(hwnd, msg, wparam, lparam)

    def _inner_wnd_proc(self, hwnd, msg, wparam, lparam, uid, ref):
        """根 TkChild 子窗口的过程：仅在标题栏带/缩放边缘带向顶层窗口透传命中"""
        try:
            if msg == WM_NCHITTEST:
                # 最大化时窗口贴满屏幕，无缩放边缘，标题栏带保留（拖动=还原）
                if not self.user32.IsZoomed(self._hwnd):
                    code = self._hit_test(hwnd, lparam)
                    if code != HTCLIENT:
                        return HTTRANSPARENT
                else:
                    x = self._ctypes.c_short(lparam & 0xFFFF).value
                    y = self._ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    rect = self._wintypes.RECT()
                    self.user32.GetWindowRect(hwnd, self._ctypes.byref(rect))
                    if 0 <= y - rect.top < self._titlebar_h_phys:
                        return HTTRANSPARENT
        except Exception:
            pass
        return self._defsubclass(hwnd, msg, wparam, lparam)

    def _hit_test(self, hwnd, lparam):
        lparam = self._ctypes.c_void_p(lparam).value or 0
        x = self._ctypes.c_short(lparam & 0xFFFF).value
        y = self._ctypes.c_short((lparam >> 16) & 0xFFFF).value
        rect = self._wintypes.RECT()
        self.user32.GetWindowRect(hwnd, self._ctypes.byref(rect))
        lx = x - rect.left
        ly = y - rect.top
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if not self.user32.IsZoomed(hwnd):
            m = self._edge
            if ly < m and lx < m:
                return HTTOPLEFT
            if ly < m and lx >= w - m:
                return HTTOPRIGHT
            if ly >= h - m and lx < m:
                return HTBOTTOMLEFT
            if ly >= h - m and lx >= w - m:
                return HTBOTTOMRIGHT
            if ly < m:
                return HTTOP
            if ly >= h - m:
                return HTBOTTOM
            if lx < m:
                return HTLEFT
            if lx >= w - m:
                return HTRIGHT
        if ly < self._titlebar_h_phys:
            return HTCAPTION
        return HTCLIENT

    def _subclass_transparent(self, widget):
        """让控件区域对鼠标"透明"，命中测试交给顶层窗口处理
        （这样标题栏空白处可原生拖拽、四周留白处可原生缩放）。"""
        try:
            hwnd = self._wintypes.HWND(widget.winfo_id())
            ref = self._subclassproc_type(
                lambda h, m, w, l, u, r: HTTRANSPARENT if m == WM_NCHITTEST
                else self._defsubclass(h, m, w, l))
            widget._transparent_proc_ref = ref  # 防止回调被垃圾回收
            self.comctl32.SetWindowSubclass(hwnd, ref, 2, 0)
        except Exception:
            pass

    # ---------------- 自定义标题栏 ----------------

    def _create_titlebar(self):
        s = self._ui_scale
        tb = tk.Frame(self.root, bg=self.TB_BG, height=round(36 * s))
        tb.grid(row=0, column=0, sticky="ew")
        tb.grid_propagate(False)
        self._titlebar = tb
        self._subclass_transparent(tb)
        tb.bind("<Configure>", self._on_titlebar_configure)

        # 标题（同样透明，保证整个标题栏可拖拽）
        title = tk.Label(tb, text="定时器", bg=self.TB_BG, fg=self.TB_FG,
                         font=("Microsoft YaHei UI", 10), padx=round(10 * s))
        title.pack(side=tk.LEFT, fill=tk.Y)
        self._subclass_transparent(title)

        # 右侧按钮：关闭 / 最大化 / 最小化 / 置顶（图钉在最左，同参考图）
        def make_btn(text, cmd, hover_bg, hover_fg, padx, font=None):
            lbl = tk.Label(tb, text=text, bg=self.TB_BG, fg=self.TB_FG,
                           font=font or (self.CAPTION_FONT, round(8 * s)), padx=padx)
            lbl.pack(side=tk.RIGHT, fill=tk.Y)
            lbl.bind("<Enter>", lambda e: lbl.config(bg=hover_bg, fg=hover_fg))
            lbl.bind("<Leave>", lambda e: self._on_titlebtn_leave(lbl))
            lbl.bind("<Button-1>", lambda e: cmd())
            return lbl

        self._btn_close = make_btn(self.GLYPH_CLOSE, self.root.destroy,
                                   self.CLOSE_HOVER_BG, self.CLOSE_HOVER_FG, round(12 * s))
        self._btn_max = make_btn(self.GLYPH_MAX, self._toggle_maximize,
                         self.TB_HOVER_BG, self.TB_FG, round(12 * s),
                         font=(self.CAPTION_FONT, round(6 * s)))
        self._btn_min = make_btn(self.GLYPH_MIN, self.root.iconify,
                                 self.TB_HOVER_BG, self.TB_FG, round(12 * s))
        self._btn_pin = make_btn(self.GLYPH_PIN, self._toggle_pin,
                                 self.TB_HOVER_BG, self.TB_FG, round(10 * s),
                                 font=("Segoe UI Emoji", round(10 * s)))

    def _on_titlebar_configure(self, event):
        self._titlebar_h_phys = int(event.height * self._tk_to_phys)

    def _on_titlebtn_leave(self, lbl):
        lbl.config(bg=self.TB_BG, fg=self.TB_FG)
        if lbl is getattr(self, "_btn_pin", None):
            self._update_pin_visual()

    def _update_pin_visual(self):
        """按置顶状态切换图钉颜色"""
        on = self.topmost_var.get()
        self._btn_pin.config(fg=self.PIN_ON_FG if on else self.TB_FG)

    def _toggle_pin(self):
        v = not self.topmost_var.get()
        self.topmost_var.set(v)
        self.root.attributes("-topmost", v)
        self._update_pin_visual()

    def _toggle_maximize(self):
        try:
            if self.root.state() == "zoomed":
                self.root.state("normal")
                self._btn_max.config(text=self.GLYPH_MAX)
            else:
                self.root.state("zoomed")
                self._btn_max.config(text=self.GLYPH_RESTORE)
        except Exception:
            pass

    # ---------------- 主界面 ----------------

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        content_row = 1 if self._win32_ok else 0
        main_frame.grid(row=content_row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        if self._win32_ok:
            self._subclass_transparent(main_frame)

        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(content_row, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # 控制面板
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # 第一行：时间输入
        self.input_label = ttk.Label(control_frame, text="时间输入 (时:分:秒):",
                                     font=self.normal_font)
        self.input_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

        self.time_entry = ttk.Entry(control_frame, font=self.normal_font, width=15)
        self.time_entry.grid(row=0, column=1, sticky=tk.W)
        self.time_entry.insert(0, "00:25:00")  # 默认25分钟

        # 第二行：模式选择（倒计时 / 正计时 / 闹钟）
        self.timer_mode = tk.StringVar(value="countdown")
        mode_frame = ttk.Frame(control_frame)
        mode_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        for text, value in (("倒计时", "countdown"), ("正计时", "countup"), ("闹钟", "alarm")):
            ttk.Radiobutton(mode_frame, text=text, variable=self.timer_mode,
                            value=value, command=self.on_mode_change).pack(side=tk.LEFT, padx=(0, 14))

        # 非 Windows / 自绘标题栏失败时，置顶选项退化为复选框
        if not self._win32_ok:
            ttk.Checkbutton(mode_frame, text="置顶窗口", variable=self.topmost_var,
                            command=self.toggle_topmost).pack(side=tk.LEFT, padx=(14, 0))

        # 时间显示区域
        display_frame = ttk.Frame(main_frame, relief=tk.SUNKEN)
        display_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        display_frame.columnconfigure(0, weight=1)
        display_frame.rowconfigure(0, weight=1)

        # 时间显示标签
        self.time_label = tk.Label(display_frame, text="00:00:00", font=self.huge_font,
                                   bg="white", fg="black")
        self.time_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 按钮框架 - 移动到数字下方
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, pady=(10, 5))

        # 合并的开始/暂停按钮
        self.toggle_button = ttk.Button(button_frame, text="开始", command=self.toggle_timer, width=10)
        self.toggle_button.grid(row=0, column=0, padx=(0, 5))

        self.reset_button = ttk.Button(button_frame, text="重置", command=self.reset_timer, width=10)
        self.reset_button.grid(row=0, column=1, padx=(0, 5))

        # 底部状态栏（分隔线 + 小字状态）
        ttk.Separator(main_frame).grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(6, 0))
        self.status_label = ttk.Label(main_frame, text="就绪",
                                      font=("Microsoft YaHei UI", 9), foreground="gray")
        self.status_label.grid(row=4, column=0, sticky=tk.W, pady=(3, 0))

        # 初始大屏与输入栏同步（倒计时模式默认 00:25:00）
        self.time_label.config(
            text=self.format_time(self.parse_time_input(self.time_entry.get())))

    def toggle_topmost(self):
        """切换窗口置顶状态"""
        is_topmost = self.topmost_var.get()
        self.root.attributes('-topmost', is_topmost)
        if self._win32_ok:
            self._update_pin_visual()

    def on_mode_change(self):
        """切换计时器模式"""
        prev_mode = getattr(self, "_active_mode", None)
        mode = self.timer_mode.get()
        # 离开倒计时时记住输入栏内容
        if prev_mode == "countdown" and mode != "countdown":
            self.saved_countdown_input = self.time_entry.get()
        self._active_mode = mode
        self.is_countdown = (mode == "countdown")
        self.is_alarm = (mode == "alarm")
        if self.is_alarm:
            self.input_label.config(text="闹钟时间 (时:分:秒):")
        else:
            self.input_label.config(text="时间输入 (时:分:秒):")

        self._stop_clock_tick()
        self.reset_timer()

        # 进入模式时同步输入栏与大屏
        if self.is_countdown:
            # 倒计时：恢复上次输入，大屏与其同步
            self._set_entry(self.saved_countdown_input)
            self.time_label.config(
                text=self.format_time(self.parse_time_input(self.time_entry.get())))
        elif mode == "countup":
            # 正计时：输入栏与大屏同时清零
            self._set_entry("00:00:00")
            self.time_label.config(text="00:00:00")
        else:
            # 闹钟：输入栏与大屏更新为进入时的当前时间，大屏随后走实时时钟
            self._set_entry(time.strftime("%H:%M:%S"))
            self._start_clock_tick()

    def _set_entry(self, text):
        """整体替换输入栏内容"""
        self.time_entry.delete(0, tk.END)
        self.time_entry.insert(0, text)

    def _start_clock_tick(self):
        """大屏显示实时时钟（闹钟模式未开始计时时的状态）"""
        if self._clock_tick_id is None:
            self._clock_tick()

    def _stop_clock_tick(self):
        if self._clock_tick_id is not None:
            self.root.after_cancel(self._clock_tick_id)
            self._clock_tick_id = None

    def _clock_tick(self):
        self.time_label.config(text=time.strftime("%H:%M:%S"))
        self._clock_tick_id = self.root.after(500, self._clock_tick)

    def parse_time_input(self, time_str):
        """解析时间输入，返回总秒数"""
        try:
            # 分割时间字符串
            parts = time_str.split(":")

            if len(parts) == 1:  # 只有秒
                return int(parts[0])
            elif len(parts) == 2:  # 分:秒
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # 时:分:秒
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                raise ValueError("无效的时间格式")
        except ValueError:
            return 0

    def parse_alarm_input(self, time_str):
        """解析24小时制时刻，返回今天的目标时间戳；无效返回 None"""
        try:
            parts = [int(p) for p in time_str.strip().split(":")]
            if len(parts) == 2:
                parts.append(0)
            if len(parts) != 3:
                return None
            h, m, s = parts
            if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
                return None
            t = time.localtime()
            return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, s, 0, 0, -1))
        except (ValueError, OverflowError):
            return None

    def format_time(self, seconds):
        """将秒数格式化为时:分:秒字符串"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def toggle_timer(self):
        """切换计时器状态：开始/暂停"""
        if not self.is_running:
            # 从暂停/停止状态切换到运行状态
            self.start_timer()
        else:
            # 从运行状态切换到暂停状态
            self.pause_timer()

    def start_timer(self):
        """开始计时"""
        if self.is_running:
            return

        if self.is_alarm:
            # 闹钟模式：监控设定时刻
            self._stop_clock_tick()  # 大屏从实时时钟切换为剩余时间倒计时
            if not self.alarm_target_ts:
                target = self.parse_alarm_input(self.time_entry.get())
                if target is None:
                    messagebox.showerror("错误", "请输入有效的闹钟时间（24小时制 时:分:秒）！")
                    return
                if target <= time.time():
                    target += 86400  # 时刻已过则定为明天
                self.alarm_target_ts = target
            elif self.alarm_target_ts <= time.time():
                # 暂停期间已到点，立即触发
                self.alarm_triggered()
                return

            self.is_running = True
            self.toggle_button.config(text="暂停")
            t = time.localtime(self.alarm_target_ts)
            self.status_label.config(
                text=f"闹钟监控中，将于 {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} 触发")
            self.update_display(max(0, int(self.alarm_target_ts - time.time())))
            self.update_alarm_loop()
            return

        if self.is_countdown and not self.is_countdown_finished:
            # 倒计时模式（非倒计时结束后的情况）
            if self.total_seconds <= 0:  # 首次开始或重置后
                time_str = self.time_entry.get()
                self.total_seconds = self.parse_time_input(time_str)

                if self.total_seconds <= 0:
                    messagebox.showerror("错误", "请输入有效的时间！")
                    return

                # 显示初始时间
                self.update_display(self.total_seconds)
        elif self.is_countdown_finished:
            # 倒计时结束后的正计时模式
            if self.elapsed_seconds == 0:  # 首次开始
                self.start_time = time.time()
            else:  # 从暂停继续
                # 调整开始时间，使得从暂停点继续
                self.start_time = time.time() - self.elapsed_seconds
        else:
            # 正常的正计时模式
            if self.elapsed_seconds == 0:  # 首次开始
                self.start_time = time.time()
            else:  # 从暂停继续
                # 调整开始时间，使得从暂停点继续
                self.start_time = time.time() - self.elapsed_seconds

        self.is_running = True
        self.toggle_button.config(text="暂停")

        if self.is_countdown and not self.is_countdown_finished:
            self.status_label.config(text=f"倒计时进行中...")
        elif self.is_countdown_finished:
            self.status_label.config(text="倒计时结束后的正计时...")
        else:
            self.status_label.config(text="正计时进行中...")

        # 启动计时器
        self.update_timer()

    def pause_timer(self):
        """暂停计时"""
        if not self.is_running:
            return

        self.is_running = False
        self.toggle_button.config(text="继续")

        # 取消定时器
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

        # 记录当前进度（闹钟模式无需记录）
        if (self.is_countdown_finished or (not self.is_countdown)) and not self.is_alarm:
            self.elapsed_seconds = int(time.time() - self.start_time)

        self.status_label.config(text="已暂停")

    def update_timer(self):
        """更新时间显示"""
        if not self.is_running:
            return

        if self.is_countdown and not self.is_countdown_finished:
            # 倒计时
            if self.total_seconds <= 0:
                self.timer_finished()
                return

            # 更新显示
            self.update_display(self.total_seconds)
            self.total_seconds -= 1
        else:
            # 正计时（包括倒计时结束后的正计时）
            self.elapsed_seconds = int(time.time() - self.start_time)
            self.update_display(self.elapsed_seconds)

        # 安排下一次更新（1000毫秒后）
        self.timer_id = self.root.after(1000, self.update_timer)

    def update_alarm_loop(self):
        """闹钟模式：刷新剩余时间并检测触发"""
        if not self.is_running or not self.is_alarm:
            return
        remaining = int(self.alarm_target_ts - time.time())
        if remaining <= 0:
            self.alarm_triggered()
            return
        self.update_display(remaining)
        self.timer_id = self.root.after(250, self.update_alarm_loop)

    def update_display(self, seconds):
        """更新显示"""
        self.time_label.config(text=self.format_time(seconds))

    def reset_timer(self):
        """重置计时器"""
        # 停止计时
        self.is_running = False
        self.is_countdown_finished = False
        self.alarm_target_ts = 0
        self.toggle_button.config(text="开始")

        # 取消定时器
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

        # 停止闪烁并恢复颜色
        self.stop_blinking()

        # 重置计时变量
        self.total_seconds = 0
        self.elapsed_seconds = 0
        self.start_time = 0

        if self.is_alarm:
            # 重置 = 回到实时时钟状态（输入栏保持不变）
            self.status_label.config(text="就绪 (闹钟模式)")
            self._start_clock_tick()
        elif self.is_countdown:
            time_str = self.time_entry.get()
            seconds = self.parse_time_input(time_str)
            self.time_label.config(text=self.format_time(seconds))
            self.status_label.config(text="就绪 (倒计时模式)")
        else:
            self.time_label.config(text="00:00:00")
            self.status_label.config(text="就绪 (正计时模式)")

    def timer_finished(self):
        """倒计时结束"""
        self.is_running = False
        self.is_countdown_finished = True
        self.toggle_button.config(text="开始")
        self.status_label.config(text="倒计时结束，开始正计时...")

        # 显示0秒
        self.time_label.config(text="00:00:00")

        # 设置正计时的开始时间
        self.start_time = time.time()
        self.elapsed_seconds = 0

        # 开始闪烁
        self.start_blinking()

        # 开始倒计时结束后的正计时
        self.is_running = True
        self.toggle_button.config(text="暂停")
        self.update_timer()

        # 播放提示音
        self.play_alert_sound(1)

        # 显示消息框
        messagebox.showinfo("时间到", "倒计时结束！现在开始正计时。")

    def alarm_triggered(self):
        """闹钟到点"""
        self.is_running = False
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.alarm_target_ts = 0  # 触发后清除，避免再次点"开始"立即重响
        self.toggle_button.config(text="开始")
        self.status_label.config(text="闹钟时间到！")
        self.time_label.config(text="00:00:00")

        # 开始闪烁 + 提示音
        self.start_blinking()
        self.play_alert_sound(3)

        messagebox.showinfo("闹钟", "闹钟时间到！")

        # 关闭弹窗后停止闪烁，大屏回到实时时钟
        self.stop_blinking()
        self.status_label.config(text="闹钟已触发，请重置")
        self._start_clock_tick()

    def play_alert_sound(self, times):
        """播放提示音（如果可用）"""
        try:
            if sys.platform == "win32":
                import winsound

                def beep(i):
                    if i >= times:
                        return
                    try:
                        winsound.Beep(1200, 400)
                    except Exception:
                        pass
                    self.root.after(450, lambda: beep(i + 1))

                beep(0)
            # macOS系统
            elif sys.platform == "darwin":
                for _ in range(times):
                    os.system("afplay /System/Library/Sounds/Ping.aiff 2> /dev/null")
            # Linux系统
            else:
                for _ in range(times):
                    os.system("aplay /usr/share/sounds/speech-dispatcher/test.wav 2> /dev/null || paplay /usr/share/sounds/freedesktop/stereo/complete.oga 2> /dev/null")
        except Exception:
            pass  # 忽略声音播放错误

    def start_blinking(self):
        """开始闪烁效果"""
        if self.blink_on:
            self.time_label.config(bg="white", fg="black")
            self.blink_on = False
        else:
            self.time_label.config(bg="red", fg="white")
            self.blink_on = True

        self.blink_timer = self.root.after(500, self.start_blinking)

    def stop_blinking(self):
        """停止闪烁并恢复颜色"""
        if self.blink_timer:
            self.root.after_cancel(self.blink_timer)
            self.blink_timer = None
        self.blink_on = False
        self.time_label.config(bg="white", fg="black")

    def on_resize(self, event):
        """窗口大小改变时更新字体大小"""
        if event.widget != self.root:
            return
        # 仅位置变化（拖动窗口）不重算字体
        if (event.width, event.height) == getattr(self, "_last_wh", None):
            return
        self._last_wh = (event.width, event.height)
        self.update_font_size()

    def update_font_size(self, width=None, height=None):
        """根据窗口大小更新字体"""
        # 获取当前窗口大小
        if width is None:
            width = self.root.winfo_width()
        if height is None:
            height = self.root.winfo_height()

        # DPI 感知下宽高是物理像素；折算回 96DPI 等效尺寸再套用原公式，
        # 避免字体点数随 DPI 再缩放导致的双重放大
        try:
            dpi = self.root.winfo_fpixels("1i") or 96
        except Exception:
            dpi = 96
        h96 = int(height * 96 / dpi)
        w96 = int(width * 96 / dpi)

        # 字体取"高度的1/5"与"宽度的1/6"中较小者：窄窗口时宽度优先，
        # 保证数字横向不溢出
        base_size = min(h96 // 5, w96 // 6)

        # 限制字体大小范围，确保在最小窗口尺寸下也能清晰显示
        font_size = max(24, min(base_size, 120))

        # 字号没变化就不重绘（拖动缩放过程中避免无谓的抖动）
        if font_size == getattr(self, "_last_font_size", None):
            return
        self._last_font_size = font_size

        # 更新显示时间的字体
        new_font = ("Arial", font_size)
        self.time_label.config(font=new_font)

        # 更新其他控件的字体大小
        normal_size = max(10, font_size // 4)

        # 只更新特定控件的字体，避免递归更新所有控件导致的问题
        # （状态栏字体固定为小号，不参与缩放）
        for widget in [self.time_entry]:
            try:
                widget.config(font=("Arial", normal_size))
            except:
                pass


def main():
    # 启用进程级 DPI 感知：高分屏缩放下窗口原生渲染不模糊（微信式深度集成的前提）
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    app = TimerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
