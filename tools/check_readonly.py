# -*- coding: utf-8 -*-
"""
只读验证：光标位置 / DPI 感知 / INPUT 结构体布局

不移动鼠标、不点击、不输入 —— 纯读，跑一百遍也不会打扰用户。
结构体尺寸是重点：SendInput 对 INPUT 的大小极其敏感，错了就静默失败。
"""
import ctypes
import sys
from ctypes import wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, r"C:\Users\Jestions\.dsh\desktop-mcp")
from desktop_mcp import win32_input as wi

print("=" * 66)
print("① 结构体布局（这是最容易错的地方）")
print(f"  sizeof(MOUSEINPUT)  = {ctypes.sizeof(wi.MOUSEINPUT)}   （期望 24 on x64）")
print(f"  sizeof(KEYBDINPUT)  = {ctypes.sizeof(wi.KEYBDINPUT)}   （期望 24 on x64）")
print(f"  sizeof(HARDWAREINPUT)= {ctypes.sizeof(wi.HARDWAREINPUT)}  （期望 8）")
print(f"  sizeof(INPUT)       = {ctypes.sizeof(wi.INPUT)}"
      f"   （期望 40 on x64 = 4 类型 + 4 对齐 + 24 联合 + 8 填充）")
expect = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
print(f"  判定：{'✓ 正确' if ctypes.sizeof(wi.INPUT) == expect else '✗ 不对，SendInput 会失败'}")

print()
print("=" * 66)
print("② DPI 感知级别")
level = wi.enable_dpi_awareness()
print(f"  生效级别：{level}")
if level in ("none", "non-windows"):
    print("  ⚠ 未生效 —— 坐标会和截图对不上（缩放屏幕上偏移几十像素）")

print()
print("=" * 66)
print("③ 光标当前位置（只读）")
x, y = wi.cursor_pos()
print(f"  GetCursorPos → ({x}, {y})")
print("  合理性检查：", end="")
if -32768 < x < 32768 and -32768 < y < 32768:
    print("✓ 在合理范围")
else:
    print("✗ 数值异常，说明返回值读错了")

print()
print("=" * 66)
print("④ 屏幕与虚拟桌面范围（多屏时很重要）")
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
SM_CMONITORS = 80
user32 = wi.user32
vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
mon = user32.GetSystemMetrics(SM_CMONITORS)
print(f"  虚拟桌面：原点 ({vx}, {vy})，尺寸 {vw}×{vh}，显示器数 {mon}")
print(f"  主屏：{user32.GetSystemMetrics(0)}×{user32.GetSystemMetrics(1)}")
print(f"  说明：有效坐标范围 x ∈ [{vx}, {vx + vw})，y ∈ [{vy}, {vy + vh})")
print("  光标在范围内：", "✓" if (vx <= x < vx + vw and vy <= y < vy + vh) else "✗")

print()
print("=" * 66)
print("⑤ 前台窗口（只读）")
hwnd = user32.GetForegroundWindow()
buf = ctypes.create_unicode_buffer(512)
user32.GetWindowTextW(hwnd, buf, 512)
print(f"  hwnd = {hwnd}")
print(f"  标题 = {buf.value!r}")
pid = wintypes.DWORD()
user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
print(f"  PID  = {pid.value}")

print()
print("=" * 66)
print("全部只读检查完成 —— 没有动过鼠标、没有点击、没有输入。")
