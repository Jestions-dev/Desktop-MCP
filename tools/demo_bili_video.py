# -*- coding: utf-8 -*-
"""
B 站首页 → 点第一张**视频卡片**（不是广告位），带光标采样。

坐标来源：截图目视定位后换算。**预览图坐标必须乘回原图比例** ——
截给模型看的图是缩过的（2582→1666），直接用预览坐标点会偏一大截。
"""
import ctypes
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

PKG = Path(r"C:\Users\Jestions\.dsh\desktop-mcp")
sys.path.insert(0, str(PKG))
from desktop_mcp import win32_window as W  # noqa: E402
from desktop_mcp import screen as S       # noqa: E402

TARGET = (1272, 651)      # 视频卡片#2「我让你装DSH没让你装大扫货！」
#   ↑ 坐标怎么来的：截图（原图 2582 宽）上目视定位卡片中心约 (1283,662)，
#     再减掉窗口原点 (-11,-11) 得到屏幕坐标。注意给模型看的预览图是 1666 宽，
#     必须 ×(2582/1666)=1.55 换算回原图 —— 直接用预览坐标会偏一大截。
START = (240, 1420)       # 左下角远处


class PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor():
    p = PT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def edge_win():
    hs = [w for w in W.list_windows(limit=150) if "Edge" in (w.title or "")]
    return hs[0] if hs else None


srv = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
n = [0]


def call(m, pr=None):
    n[0] += 1
    srv.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": m,
                                "params": pr or {}}, ensure_ascii=False) + "\n")
    srv.stdin.flush()
    line = srv.stdout.readline()
    if not line:
        raise RuntimeError("无响应")
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return "".join(x.get("text", "") for x in c if x.get("type") == "text")


call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

w = edge_win()
if not w:
    print("✗ 没有 Edge 窗口")
    sys.exit(1)
tool("desktop_focus_window", hwnd=w.hwnd, action="maximize", screenshot=False, wait=1.0)

print("① 退回 B 站首页（alt+left）")
tool("desktop_press", keys="alt+left", wait=2.5)
time.sleep(1.5)
w = edge_win()
print(f"   {w.title[:70]}")

print()
print("② 起点归位 + 采样点击")
tool("desktop_click", x=START[0], y=START[1], screenshot=False, wait=0)
time.sleep(0.3)

samples = []
stop = threading.Event()


def sampler():
    while not stop.is_set():
        samples.append((time.perf_counter(),) + cursor())
        time.sleep(0.008)


stop.clear()
th = threading.Thread(target=sampler, daemon=True)
th.start()
time.sleep(0.12)

t0 = time.time()
res = tool("desktop_click_human", x=TARGET[0], y=TARGET[1],
           from_x=START[0], from_y=START[1], screenshot=False, wait=0)
dt = time.time() - t0
stop.set()
th.join(timeout=1)
for line in res.splitlines():
    print("   " + line)

print()
print("③ 真实移动曲线（采样）")
moved, last = [], None
for (tt, x, y) in samples:
    if last is None or (x, y) != last:
        moved.append((tt, x, y))
        last = (x, y)
if len(moved) >= 5:
    rows = []
    for i in range(1, len(moved)):
        dti = moved[i][0] - moved[i - 1][0]
        dd = math.hypot(moved[i][1] - moved[i - 1][1], moved[i][2] - moved[i - 1][2])
        if dti > 0 and dd > 0.8:
            rows.append((dd, dd / dti))
    total = sum(d for d, _ in rows)
    dur = moved[-1][0] - moved[0][0]
    straight = math.hypot(TARGET[0] - START[0], TARGET[1] - START[1])
    if rows and dur > 0:
        seg = max(1, len(rows) // 5)
        fives = []
        for i in range(5):
            part = [s for _, s in rows[i * seg:(i + 1) * seg]]
            if part:
                fives.append(sum(part) / len(part))
        print(f"   采样 {len(moved)} 点，跨 {dur * 1000:.0f}ms")
        print(f"   路径 {total:.0f}px  直线 {straight:.0f}px  绕路比 {total / straight:.2f}")
        if fives:
            mx = max(fives) or 1
            for i, val in enumerate(fives):
                lbl = ["起步", "加速", "最快", "减速", "收尾"][i]
                print(f"     {lbl} {val:>7.0f} px/s  {'█' * max(1, int(val / mx * 38))}")
            print(f"   收尾/峰值 = {fives[-1] / mx:.2f}")

fin = cursor()
print(f"\n   落点 {fin}  目标 {TARGET}  偏差 {math.hypot(fin[0]-TARGET[0], fin[1]-TARGET[1]):.0f}px")

print()
print("④ 结果：标题变了吗")
time.sleep(3.0)
w2 = edge_win()
if w2:
    print(f"   {w2.title[:80]}")
img = S.grab_window(w2.hwnd) if w2 else None
if img:
    out = Path(r"D:\ForDeepseek\DesktopMCP\tools\_shots\bili_after_video.png")
    img.resize((img.size[0] // 2, img.size[1] // 2)).save(out)
    print(f"   截图 → {out}")

srv.stdin.close()
try:
    srv.wait(timeout=5)
except Exception:
    srv.kill()
