# -*- coding: utf-8 -*-
"""
窗口层：枚举/查找/激活/缩放窗口

agent 操作 GUI 时，"先切到目标窗口"是几乎所有动作的前提 —— 所以这层很重要。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    user32 = kernel32 = None

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process: str
    rect: tuple[int, int, int, int]     # left, top, right, bottom
    minimized: bool
    foreground: bool

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    def describe(self) -> str:
        l, t, r, b = self.rect
        flags = []
        if self.foreground:
            flags.append("前台")
        if self.minimized:
            flags.append("最小化")
        mark = f"  [{', '.join(flags)}]" if flags else ""
        return (f"hwnd={self.hwnd}  {self.title or '(无标题)'}"
                f"  [{self.process}#{self.pid}]  "
                f"({l},{t})-({r},{b}) {self.width}×{self.height}{mark}")


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, n + 1)
    return buf.value


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _process_name(pid: int) -> str:
    """用 QueryFullProcessImageName 拿进程名（不需要管理员权限）"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            import os
            return os.path.basename(buf.value)
        return "?"
    finally:
        kernel32.CloseHandle(h)


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(wintypes.HWND(hwnd)))


def foreground() -> Optional[WindowInfo]:
    hwnd = user32.GetForegroundWindow()
    return info(hwnd) if hwnd else None


def info(hwnd: int) -> WindowInfo:
    pid = _pid(hwnd)
    return WindowInfo(hwnd=int(hwnd), title=_title(hwnd), pid=pid,
                      process=_process_name(pid), rect=_rect(hwnd),
                      minimized=_is_minimized(hwnd),
                      foreground=(user32.GetForegroundWindow() == hwnd))


def list_windows(only_titled: bool = True, include_tool_windows: bool = False,
                 limit: int = 60) -> list[WindowInfo]:
    """
    枚举可见的顶层窗口。
    默认过滤掉无标题窗口和工具窗口（后者是托盘/隐藏辅助窗口，通常没意义）。
    """
    out: list[WindowInfo] = []
    fg = user32.GetForegroundWindow()

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        if not include_tool_windows and (ex & WS_EX_TOOLWINDOW):
            return True
        title = _title(hwnd)
        if only_titled and not title.strip():
            return True
        pid = _pid(hwnd)
        out.append(WindowInfo(int(hwnd), title, pid, _process_name(pid), _rect(hwnd),
                              _is_minimized(hwnd), hwnd == fg))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    # 前台窗口排最前，其余按标题
    out.sort(key=lambda w: (not w.foreground, w.title.lower()))
    return out[:limit]


def find(query: str, limit: int = 20) -> list[WindowInfo]:
    """按标题或进程名模糊匹配（不区分大小写）"""
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = [w for w in list_windows(limit=400)
            if q in w.title.lower() or q in w.process.lower()]
    return hits[:limit]


def activate(hwnd: int, timeout: float = 2.0) -> bool:
    """
    把窗口切到前台并返回是否成功。

    Windows 有前台锁定（foreground lock）：后台进程不能随便抢焦点。
    业界通用的绕过法是 AttachThreadInput —— 把自己的输入队列临时接到目标窗口
    所在线程上，SetForegroundWindow 就会被放行。这里两种都试。
    """
    import time
    hwnd = int(hwnd)
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        return False
    if _is_minimized(hwnd):
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)

    if user32.GetForegroundWindow() == hwnd:
        return True
    user32.SetForegroundWindow(wintypes.HWND(hwnd))

    # 还不行就上 AttachThreadInput
    if user32.GetForegroundWindow() != hwnd:
        fg = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(wintypes.HWND(fg), None) if fg else 0
        attached = []
        try:
            for t in (fg_thread, target_thread):
                if t and t != cur_thread and user32.AttachThreadInput(cur_thread, t, True):
                    attached.append(t)
            user32.BringWindowToTop(wintypes.HWND(hwnd))
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
        finally:
            for t in attached:
                user32.AttachThreadInput(cur_thread, t, False)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def move_resize(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    user32.SetWindowPos(wintypes.HWND(int(hwnd)), None, int(x), int(y),
                        max(1, int(width)), max(1, int(height)),
                        SWP_NOZORDER | SWP_NOACTIVATE)


def set_state(hwnd: int, action: str) -> bool:
    """
    改窗口的显示状态：maximize / minimize / restore / activate。

    为什么不做"拖边框调大小"：要处理边框命中测试、吸附、最小尺寸……
    而点最大化按钮、或点任务栏都能达到同样效果 —— 收益不值那个复杂度。
    这里只做状态切换，一行 ShowWindow 就够了。
    """
    hwnd = int(hwnd)
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        return False
    act = (action or "").lower()
    if act in ("activate", "focus", "show"):
        return activate(hwnd)
    if act in ("maximize", "max"):
        user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)
    elif act in ("minimize", "min"):
        user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
    elif act in ("restore", "normal", "unmaximize"):
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    else:
        raise ValueError(f"不认识的动作：{action!r}（可用 maximize / minimize / restore / activate）")
    return True


def state_of(hwnd: int) -> str:
    """当前显示状态：maximized / minimized / normal"""
    hwnd = int(hwnd)
    if user32.IsZoomed(wintypes.HWND(hwnd)):
        return "maximized"
    if user32.IsIconic(wintypes.HWND(hwnd)):
        return "minimized"
    return "normal"


def client_rect_screen(hwnd: int) -> tuple[int, int, int, int]:
    """
    客户区在屏幕上的位置（不含标题栏边框）。
    点击窗口内部控件时应该用客户区坐标，而不是整窗坐标。
    """
    r = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(int(hwnd)), ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(int(hwnd)), ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top
