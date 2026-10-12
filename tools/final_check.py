# -*- coding: utf-8 -*-
"""最终验收：导入、工具数、Electron 框的完整往返"""
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(r"C:\Users\Jestions\.dsh\desktop-mcp")
sys.path.insert(0, str(PKG))

# ⚠ 这里**不要**自己设 DPI 感知！
# 进程的 DPI 感知级别**只能设一次**，先设的赢。我之前在这里调了
# shcore.SetProcessDpiAwareness(2)，把级别锁成 "system"，于是 win32_input
# 再想升到 per-monitor-v2 就失败了 —— 而 system 感知在 150% 缩放的屏上
# 会返回虚拟化坐标，量出来的窗口正好小 1.5 倍（我为此绕了三轮）。
# 交给 win32_input 在 import 时设，它用的是正确的 per-monitor-v2。
ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"   ✓ {label}")
    else:
        fail += 1
        global _FAILED
        _FAILED = True
        print(f"   ✗ {label}  {detail}")


print("=" * 70)
print("① 模块导入")
from desktop_mcp import tools as T
from desktop_mcp import electron_frame as EF
from desktop_mcp import screen as S, win32_input as I, win32_window as W

_FAILED = False        # 任一检查失败就置 True（末尾据此设退出码）

print("   ✓ desktop_mcp.tools / electron_frame / screen / win32_input / win32_window 均可导入")

print()
print("=" * 70)
print("② 工具注册表")
names = [t["name"] for t in T.list_tools()]
print(f"   {len(names)} 个：")
for n in names:
    print(f"     · {n}")
check("17 个工具", len(names) == 17, f"实际 {len(names)}")
check("注册表与工具名一致", set(T._DISPATCH) == set(names))
check("新增人味点击", "desktop_click_human" in names)
check("新增框管理三件套",
      {"desktop_frame_start", "desktop_frame_stop", "desktop_frame_status"} <= set(names))
check("都有描述与 schema",
      all(t.get("description", "").strip() and t.get("inputSchema", {}).get("type") == "object"
          for t in T.list_tools()))

print()
print("=" * 70)
print("③ Electron 可执行文件定位")
exe = EF.find_electron()
print(f"   {exe}")
check("找到 electron.exe", bool(exe))

print()
print("=" * 70)
print("④ 框的完整往返（启动 → 显示 → 隐藏 → 收掉）")
f = EF.ElectronFrame()
t0 = time.time()
started = f.start(timeout=25)
check(f"启动（{time.time() - t0:.1f}s）", started, str(f.errors[-1:]))
if started:
    check("启动后就有 hwnd（不用等页面加载）", f.hwnd > 0, f"hwnd={f.hwnd}")
    try:
        res = f.show_region(700, 400, 700, 450)
        check("show 指令被接受", res.get("ok") is True, str(res))
    except Exception as e:
        check("show 指令", False, f"{type(e).__name__}: {e}")

    time.sleep(1.5)
    print(f"     （本进程 DPI 级别：{I._DPI_LEVEL}）")
    import ctypes as _ct
    import ctypes.wintypes as _wt
    u = _ct.WinDLL("user32", use_last_error=True)
    r = _wt.RECT()
    hwnd_used = f.hwnd
    u.GetWindowRect(_wt.HWND(hwnd_used), _ct.byref(r))
    got = (r.left, r.top, r.right - r.left, r.bottom - r.top)
    # 期望值 = 请求区域外扩 44px（frame.css 里 #frame 的 inset）。
    # ⚠ 这里量的是**物理像素**，前提是电子侧把物理像素换算成了 DIP 再 setBounds
    # （150% 缩放的屏上不换算会差 1.5 倍 —— 踩过，见 README）。
    want = (float(700 - 44), float(400 - 44), float(700 + 88), float(450 + 88))
    off = max(abs(got[0] - want[0]), abs(got[1] - want[1]),
              abs(got[2] - want[2]), abs(got[3] - want[3]))
    print(f"     hwnd={hwnd_used}  实测 {got}  期望 {tuple(int(v) for v in want)}  最大偏差 {off:.0f}px")
    check("窗口位置与尺寸精确（±2px，允许取整）", off <= 2, f"{got} vs {want}")
    check("窗口可见", bool(u.IsWindowVisible(_wt.HWND(f.hwnd))))

    f.hide()
    time.sleep(0.8)
    check("hide 后不可见", not u.IsWindowVisible(_wt.HWND(f.hwnd)))

    f.stop()
    time.sleep(0.4)
    check("stop 后进程结束", not f.running)

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")


sys.exit(1 if _FAILED else 0)
