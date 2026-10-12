# -*- coding: utf-8 -*-
"""
真场景：在 **B 站**（真站点，有行为风控）用真人轨迹点击视频。

流程：开 Edge → 进 bilibili.com → 截图找视频链接 → 用 desktop_click_human 点它
      → 采样光标画出真实移动曲线 → 核对是否进了视频页。

为什么选 B 站：它记录鼠标轨迹做风控，"瞬移式点击"是典型的机器特征。
这正是 desktop_click_human 要解决的场景。

⚠ DPI 感知必须最先设（今天栽了六次的坑：尺子不在同一坐标系）。
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


class PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor():
    p = PT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


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
        raise RuntimeError("无响应：" + (srv.stderr.read() or "")[:300])
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return "".join(x.get("text", "") for x in c if x.get("type") == "text")


call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

print("=" * 78)
print("① 开 Edge 并打开 B 站")
tool("desktop_press", keys="win+r", wait=0.8)
tool("desktop_type", text="msedge https://www.bilibili.com\n", wait=2.0)

edge = None
for i in range(40):
    time.sleep(0.7)
    hits = [w for w in W.list_windows(limit=150)
            if "bilibili" in (w.title or "").lower() or "哔哩哔哩" in (w.title or "")]
    if hits:
        edge = hits[0]
        if i > 2:                       # 标题稳定几轮再算加载完
            break
if not edge:
    print("   ✗ B 站页面没起来")
    srv.stdin.close()
    srv.kill()
    sys.exit(1)
print(f"   ✓ {edge.title[:60]}")
print(f"     窗口 ({edge.rect[0]},{edge.rect[1]}) {edge.width}x{edge.height}")

# 最大化，让视频卡片大一点、点击更稳
tool("desktop_focus_window", hwnd=edge.hwnd, action="maximize", screenshot=False, wait=1.5)
edge = [w for w in W.list_windows(limit=150) if "bilibili" in (w.title or "").lower()][0]
l, t, r, b = edge.rect
print(f"   最大化后 ({l},{t}) {r - l}x{b - t}")
time.sleep(1.5)

print()
print("=" * 78)
print("② 截图看看首页长什么样（挑一个视频链接的坐标）")
shot = PKG / ".." / ".." / "ForDeepseek" / "DesktopMCP" / "tools" / "_shots"
out_dir = Path(r"D:\ForDeepseek\DesktopMCP\tools\_shots")
out_dir.mkdir(parents=True, exist_ok=True)
png = tool("desktop_screenshot", max_width=1280)
# 工具返回的是图像，不是文本；这里改用它写到磁盘的方式 —— 直接用 screen 抓
from desktop_mcp import screen as S  # noqa: E402

img = S.grab_window(edge.hwnd)
bili_png = out_dir / "bili_home.png"
if img:
    img.save(bili_png)
    print(f"   截图 {img.size[0]}x{img.size[1]} → {bili_png}")

print()
print("=" * 78)
print("③ 用真人轨迹点击（在首页找一个视频，点它的封面）")
print("   ⚠ 我在这一步会同时采样光标位置，8ms 一次")

# 目标：首页的视频卡片。B 站首页是响应式网格，取第一行第二张卡片的封面中心
# （左上角有 logo/导航，避开；右侧有登录区，避开）
cx0 = l + int((r - l) * 0.30)
cy0 = t + int((b - t) * 0.42)

# 起点：屏幕左下角远处（这样会有一大段可见的移动）
SX, SY = l + 120, b - 80
print(f"   起点 ({SX},{SY})  →  目标 ({cx0},{cy0})   "
      f"直线 {math.hypot(cx0 - SX, cy0 - SY):.0f}px")

tool("desktop_click", x=SX, y=SY, screenshot=False, wait=0)
time.sleep(0.3)

samples = []
stop_flag = threading.Event()


def sampler():
    while not stop_flag.is_set():
        samples.append((time.perf_counter(),) + cursor())
        time.sleep(0.008)


stop_flag.clear()
th = threading.Thread(target=sampler, daemon=True)
th.start()
time.sleep(0.12)

t0 = time.time()
res = tool("desktop_click_human", x=cx0, y=cy0, from_x=SX, from_y=SY,
           screenshot=False, wait=0)
dt = time.time() - t0
stop_flag.set()
th.join(timeout=1)

for line in res.splitlines():
    print("   " + line)

print()
print("=" * 78)
print("④ 采样到的真实移动曲线")
moved = []
last = None
for (tt, x, y) in samples:
    if last is None or (x, y) != last:
        moved.append((tt, x, y))
        last = (x, y)
if len(moved) >= 5:
    t_start = moved[0][0]
    rows = []
    for i in range(1, len(moved)):
        dti = moved[i][0] - moved[i - 1][0]
        dd = math.hypot(moved[i][1] - moved[i - 1][1], moved[i][2] - moved[i - 1][2])
        if dti > 0 and dd > 0.5:
            rows.append((dd, dd / dti))
    total_len = sum(d for d, _ in rows)
    dur = moved[-1][0] - moved[0][0]
    straight = math.hypot(cx0 - SX, cy0 - SY)
    if rows and dur > 0:
        v = total_len / dur
        peak = max(s for _, s in rows)
        print(f"   采样 {len(moved)} 个位置点，跨 {dur * 1000:.0f}ms")
        print(f"   实测路径长 {total_len:.0f}px   直线 {straight:.0f}px   "
              f"绕路比 {total_len / straight:.2f}")
        print(f"   平均速度 {v:.0f} px/s   峰值 {peak:.0f} px/s   "
              f"峰值/平均 {peak / v:.2f}")
        seg = max(1, len(rows) // 5)
        fives = []
        for i in range(5):
            part = [s for _, s in rows[i * seg:(i + 1) * seg]]
            if part:
                fives.append(sum(part) / len(part))
        if fives:
            mx = max(fives) or 1
            print("\n   实测速度剖面：")
            for i, val in enumerate(fives):
                lbl = ["起步", "加速", "最快", "减速", "收尾"][i]
                print(f"     {lbl} {val:>7.0f} px/s  {'█' * max(1, int(val / mx * 40))}")
            print(f"\n   收尾/峰值 = {fives[-1] / mx:.2f}  （人手 0.1~0.4；恒速 1.0）")
else:
    print(f"   ⚠ 采样点太少（{len(moved)}）")

final = cursor()
off = math.hypot(final[0] - cx0, final[1] - cy0)
print(f"\n   最终光标 {final}  目标 ({cx0},{cy0})  偏差 {off:.0f}px"
      f"  {'✓' if off <= 3 else '✗'}")

print()
print("=" * 78)
print("⑤ 点击后发生了什么（标题变了就是进了视频页）")
time.sleep(2.5)
now = [w for w in W.list_windows(limit=150) if "bilibili" in (w.title or "").lower()]
if now:
    print(f"   当前标题：{now[0].title[:70]}")
    if any(k in now[0].title for k in ("video/BV", "哔哩哔哩", "_哔哩哔哩")):
        print("   → 标题里带 BV 号或站点名，可能进了视频页")
else:
    print("   找不到浏览器窗口了")

final_img = S.grab_window(now[0].hwnd) if now else None
if final_img:
    p2 = out_dir / "bili_after_click.png"
    final_img.save(p2)
    print(f"   截图 → {p2}")

srv.stdin.close()
try:
    srv.wait(timeout=5)
except Exception:
    srv.kill()
