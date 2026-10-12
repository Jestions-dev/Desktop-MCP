# -*- coding: utf-8 -*-
"""
desktop-mcp —— Win32 基础层（纯 ctypes，零依赖）

与 dsh-orb 用的是同一套 Win32 API（user32/gdi32 的 SendInput / BitBlt），
这里用 Python ctypes 重写，这样任何 MCP 客户端都能用，不绑 DSH 插件体系。

坐标约定：全屏物理像素，原点在**主屏左上角**，允许负值（多屏在主屏左侧时）。
分数坐标（0–1000）由 tools 层换算，本层只认像素。
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ⚠ 函数签名必须显式声明。ctypes 对未声明的参数一律按 32 位 int 处理，
    # 在 x64 上指针会被截断 —— SendInput 会直接返回 0 并置 ERROR_INVALID_PARAMETER(87)。
    # 这个坑一开始没暴露，是因为当时的测试只校验了结构体尺寸、没真的发过事件。
    # 注意：SendInput 的签名要等 INPUT 结构体定义之后才能声明（见文件下半部分）。

    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL

    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL

    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
else:                                     # 非 Windows 只用于导入不炸，调用会报错
    user32 = kernel32 = None

# ---------------------------------------------------------------- DPI
# 不设 DPI 感知时，进程拿到的是"逻辑像素"，鼠标坐标会被系统缩放，
# 于是截图坐标和点击坐标对不上（125%/150% 缩放下偏移几十像素）。
# 必须在任何窗口/输入操作之前设置一次。
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def enable_dpi_awareness() -> str:
    """让本进程按物理像素工作。返回实际生效的级别，便于排查。"""
    if not IS_WINDOWS:
        return "non-windows"
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except AttributeError:
        pass
    try:                                   # Windows 8.1 及更早
        if ctypes.WinDLL("shcore").SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "none"


# ⚠ 必须在**任何**窗口/输入操作之前生效，所以 import 时就设一次。
#
# 踩过的坑：这个函数原来只在测试脚本里被调用，服务器自己从没调过 ——
# 于是 MCP 服务器进程一直是不感知 DPI 的，`list_windows` / `measure_window`
# 报的是**逻辑像素**，而 `click` 要的是物理像素。之所以一直没暴露，是因为
# 我每次都是"看截图、从图上读坐标"，而截图和操作用同一套坐标系，自洽了。
# 换一个来源的坐标（比如用户给的、或别的工具报的）就会偏 1.5 倍。
_DPI_LEVEL = enable_dpi_awareness()


# ---------------------------------------------------------------- INPUT 结构
# 这段是踩了两轮坑才对的，别随手改：
#
# 坑 1：ctypes 对未声明签名的参数按 32 位 int 处理 → SendInput 的指针参数在 x64 上被
#       截断，返回 0 并置 ERROR_INVALID_PARAMETER(87)。必须在定义完 INPUT 后显式
#       声明 argtypes。
# 坑 2：**绝对不要给这些结构体加 _pack_**。Windows 要的是自然对齐的布局：
#       sizeof(MOUSEINPUT)=24（末尾 4 字节填充，让 union 达到 8 字节对齐）
#       sizeof(INPUT)=40（type 4 + 填充 4 + union 32）
#       加了 _pack_ = 8 会算成 MOUSEINPUT=20 / KEYBDINPUT=16 / INPUT=28，
#       SendInput 一律拒收（错误码 87），字段偏移也会错（dwFlags 跑到 20 而非 16）。
#
# 下面每个结构体都在模块末尾用 assert 校验过尺寸，改坏了会立刻炸。
class MOUSEINPUT(ctypes.Structure):
    # dwExtraInfo 是 ULONG_PTR；写成 c_void_p 让 ctypes 按 8 字节对齐，
    # 于是本结构 = 32 字节、dwFlags 在 offset 12。**不要加 _pack_**，也不要省掉
    # dwExtraInfo —— 那两个改法会让 sizeof(INPUT) 变成 28/32，
    # 而 SendInput 对 cbSize 极其严格：非 40 一律返回 0 + 错误码 87。
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTunion(ctypes.Union):
    # 必须显式把 dwExtraInfo 的 8 字节算进去 —— 用 c_void_p 而非 ULONG_PTR，
    # 否则 Python 的整数 0 会被当成 32 位，union 尺寸和整体布局都会偏。
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT),
                ("_align", ctypes.c_void_p)]


class INPUT(ctypes.Structure):
    # type 后必须有 4 字节显式填充，让 union 落在 offset 8。
    # 少了它，Python 会把 union 放在 offset 4，整个结构偏移错位 ——
    # 症状是 SendInput 不报错但光标跳到屏幕角（实测过）。
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("_pad", wintypes.DWORD),
                ("u", _INPUTunion)]


if IS_WINDOWS:
    # 现在 INPUT 有了，可以声明 SendInput 的真实签名
    user32.SendInput.argtypes = [wintypes.UINT,
                                 ctypes.POINTER(INPUT),
                                 ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT

    # ---- 布局自检：改坏结构体要立刻炸，而不是等 SendInput 静默返回 0（错误码 87）
    #
    # 注意 sizeof(MOUSEINPUT) 在 ctypes 下是 **32** 而不是 C 的 24：
    #   ctypes 把末尾的 c_void_p 按 8 字节对齐，于是 dwExtraInfo 落在 offset 24
    #   （C 里是 16 + 8 字节尾部填充）。两者**总大小恰好都是 32**，且我们总是把
    #   dwExtraInfo 传 None(=0)、从不读它，所以这个差异无害。
    # 真正必须守住的是 sizeof(INPUT) == 40 —— SendInput 按它校验，错了就返回 0。
    _PTR = ctypes.sizeof(ctypes.c_void_p)
    if _PTR == 8:                                   # x64
        # ⚠ 40 是硬要求：SendInput 校验 cbSize，非 40 一律返回 0 + 错误码 87。
        # 这个值由 "type(4) + 填充(4) + union(32)" 得来，而 union 的 32 来自
        # MOUSEINPUT 里的 c_void_p（8 字节对齐）。
        assert ctypes.sizeof(INPUT) == 40, \
            f"INPUT 应为 40，实为 {ctypes.sizeof(INPUT)} —— SendInput 会拒收(87)"
        assert INPUT.u.offset == 8, \
            f"INPUT.u 偏移应为 8，实为 {INPUT.u.offset}"
        assert ctypes.sizeof(MOUSEINPUT) == 32, \
            f"MOUSEINPUT 应为 32，实为 {ctypes.sizeof(MOUSEINPUT)}"
        assert ctypes.sizeof(KEYBDINPUT) == 24, \
            f"KEYBDINPUT 应为 24，实为 {ctypes.sizeof(KEYBDINPUT)}"
        assert MOUSEINPUT.dwFlags.offset == 12, \
            f"MOUSEINPUT.dwFlags 偏移应为 12，实为 {MOUSEINPUT.dwFlags.offset}"
        assert KEYBDINPUT.dwFlags.offset == 4 and KEYBDINPUT.time.offset == 8, \
            "KEYBDINPUT 字段偏移不对"


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("desktop-mcp 的桌面操作目前只支持 Windows")


def _send(*inputs: INPUT) -> None:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise OSError(f"SendInput 只发送了 {sent}/{n} 个事件"
                      f"（错误码 {ctypes.get_last_error()}）")


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    # dwExtraInfo 恒为 None（= 0）；它是 c_void_p，传 None 才是本分写法
    return INPUT(type=INPUT_MOUSE,
                 mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, None))


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, None))


# ---------------------------------------------------------------- 鼠标
def cursor_pos() -> tuple[int, int]:
    _require_windows()
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError("GetCursorPos 失败")
    return pt.x, pt.y


def _normalize(x: int, y: int) -> tuple[int, int]:
    """
    把物理像素坐标归一化到 0..65535（MOUSEEVENTF_ABSOLUTE 要的形式）。

    归一化范围必须是**整个虚拟桌面**（不是主屏），否则多屏/负坐标下会偏。
    用 65535（而非 65536）并配合 `-1` 分母，才不会在右/下边缘差 1 像素。
    """
    vx, vy = _virtual_origin()
    vw, vh = _virtual_size()
    nx = int(round((x - vx) * 65535 / max(1, vw - 1)))
    ny = int(round((y - vy) * 65535 / max(1, vh - 1)))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _virtual_origin() -> tuple[int, int]:
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))     # SM_X/YVIRTUALSCREEN


def _virtual_size() -> tuple[int, int]:
    return (user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))     # SM_CX/CYVIRTUALSCREEN


def move_to(x: int, y: int) -> None:
    """
    绝对移动到物理像素坐标。

    ⚠ 不能用相对位移（MOUSEEVENTF_MOVE + dx/dy）—— Windows 8.1 之后鼠标加速的语义
    变了，实测 dx=-455 会被当成**绝对坐标**把光标甩到屏幕左上角。
    必须用 MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK + 归一化坐标。
    """
    _require_windows()
    nx, ny = _normalize(int(x), int(y))
    _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def click(x: int | None = None, y: int | None = None, button: str = "left",
          clicks: int = 1, interval: float = 0.02) -> tuple[int, int]:
    _require_windows()
    if button not in _BUTTONS:
        raise ValueError(f"button 必须是 {list(_BUTTONS)}，收到 {button!r}")
    if x is not None and y is not None:
        move_to(x, y)
        time.sleep(interval)
    down, up = _BUTTONS[button]
    for _ in range(max(1, int(clicks))):
        _send(_mouse(down), _mouse(up))
        time.sleep(interval)
    return cursor_pos()


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left",
         steps: int = 20, duration: float = 0.3) -> None:
    """
    按下 → 分步移动 → 抬起。
    分步是必须的：一步跳过去，很多程序（画布、滑块、拖放目标）收不到中间事件。
    """
    _require_windows()
    if button not in _BUTTONS:
        raise ValueError(f"button 必须是 {list(_BUTTONS)}")
    down, up = _BUTTONS[button]
    move_to(x1, y1)
    time.sleep(0.05)
    _send(_mouse(down))
    time.sleep(0.05)
    steps = max(2, int(steps))
    for i in range(1, steps + 1):
        move_to(round(x1 + (x2 - x1) * i / steps), round(y1 + (y2 - y1) * i / steps))
        time.sleep(max(0.0, duration / steps))
    time.sleep(0.05)
    _send(_mouse(up))


def scroll(amount: int, x: int | None = None, y: int | None = None,
           horizontal: bool = False) -> None:
    """滚轮。正数向上/向右，负数向下/向左；一格 = 120"""
    _require_windows()
    if x is not None and y is not None:
        move_to(x, y)
        time.sleep(0.05)
    flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    # 拆成小步：一次发几千会被某些程序忽略
    remaining = int(amount)
    step = 120 if remaining > 0 else -120
    while remaining:
        chunk = step if abs(remaining) >= 120 else remaining
        _send(_mouse(flag, data=chunk & 0xFFFFFFFF))
        remaining -= chunk
        time.sleep(0.01)


# ---------------------------------------------------------------- 键盘
VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "numlock": 0x90, "scrolllock": 0x91,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    # 常见符号（US 布局的 OEM 键）
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for _c in "0123456789":
    VK[_c] = 0x30 + int(_c)
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())


# 系统截图/录屏快捷键：注入这些会拉起系统 UI（截图条、录屏条），
# 把用户桌面搅乱，而且和"agent 自己截图"这件事语义冲突。
# 这个保护借鉴自 dsh-orb（MIT）的 isForbiddenScreenshotHotkey。
_FORBIDDEN_SCREENSHOT_KEYS = {"printscreen", "snapshot"}
_SCREENSHOT_HOTKEY_MODS = {"win", "lwin", "rwin", "meta", "cmd"}


def reject_screenshot_chord(keys: list[str]) -> None:
    """
    拦下系统截图/录屏组合键。命中就抛 ValueError（tools 层会转成 isError）。

    拦 Win+Shift+3/4/5（macOS 习惯）和 Win+Shift+S（Windows 截图工具）、
    以及单独的 PrtScn —— 这些都不是"操作某个程序"，而是唤起系统 UI。
    """
    norm = {k.strip().lower() for k in keys}
    if norm & _FORBIDDEN_SCREENSHOT_KEYS:
        raise ValueError(
            "不允许注入 PrtScn/截图键 —— 它会拉起系统截图工具，"
            "而且 agent 需要看屏幕时应该直接调用 screenshot 工具。")
    if (norm & _SCREENSHOT_HOTKEY_MODS) and "shift" in norm and (norm & {"s", "3", "4", "5"}):
        raise ValueError(
            "不允许注入系统截图组合键（Win+Shift+S / 3 / 4 / 5）—— "
            "需要截图请直接调用 screenshot 工具。")


def type_text(text: str, per_char: float = 0.0) -> None:
    """
    输入文本，**支持中文**（走 KEYEVENTF_UNICODE，绕过键盘布局）。

    注意：UNICODE 注入对部分程序（尤其游戏、部分 Electron）无效 —— 那些程序
    只认真实键盘扫描码。遇到无效时改用剪贴板粘贴（tools 层的 method="clipboard"）。
    """
    _require_windows()
    for ch in text:
        if ch == "\n":
            _send(_key(VK["enter"]), _key(VK["enter"], flags=KEYEVENTF_KEYUP))
        elif ch == "\t":
            _send(_key(VK["tab"]), _key(VK["tab"], flags=KEYEVENTF_KEYUP))
        else:
            code = ord(ch)
            if code > 0xFFFF:                        # 增补平面（emoji 等）→ 代理对
                code -= 0x10000
                units = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
            else:
                units = [code]
            for u in units:
                _send(_key(scan=u, flags=KEYEVENTF_UNICODE),
                      _key(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if per_char:
            time.sleep(per_char)


def hotkey(keys: list[str] | str, gap: float = 0.01) -> None:
    """按组合键，如 "ctrl+s" 或 ["ctrl","shift","esc"]。顺序按下，逆序抬起。"""
    _require_windows()
    gap = 0.01 if gap is None else float(gap)      # 调用方漏传时别让 time.sleep(None) 崩
    if isinstance(keys, str):
        parts = [p for p in keys.replace("+", " ").split() if p]
    else:
        parts = list(keys)
    if not parts:
        raise ValueError("keys 不能为空")
    reject_screenshot_chord(parts)
    vks = []
    for p in parts:
        k = p.strip().lower()
        if k not in VK:
            raise ValueError(f"不认识的键：{p!r}（支持：{', '.join(sorted(VK))}）")
        vks.append(VK[k])
    for vk in vks:
        _send(_key(vk))
        time.sleep(gap)
    for vk in reversed(vks):
        _send(_key(vk, flags=KEYEVENTF_KEYUP))
        time.sleep(gap)


# ---------------------------------------------------------------- 剪贴板（中文输入的兜底）
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def set_clipboard_text(text: str) -> None:
    """写文本到剪贴板（供 type_via_clipboard 使用）"""
    _require_windows()
    if not user32.OpenClipboard(None):
        raise OSError("打不开剪贴板（可能被别的程序占用）")
    try:
        user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            raise OSError("GlobalAlloc 失败")
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, buf, size)
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise OSError("SetClipboardData 失败")
    finally:
        user32.CloseClipboard()
