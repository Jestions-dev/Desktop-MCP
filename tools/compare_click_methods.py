# -*- coding: utf-8 -*-
"""
靶场对比：desktop_click（两点一线瞬移） vs desktop_click_human（真人轨迹）

同一批靶心坐标，**交替**用两种方式点（避免"先点的靶子简单/难"这种偏差），
比命中率、落点偏差、耗时。光标怎么走，看屏幕就知道。

靶场是 tools/target_range.py —— 它把圆心屏幕坐标写进 <结果>.circles，
每次点击记录窗口收到的坐标，结果写进 <结果>.jsonl。
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ⚠ DPI 感知必须先设：否则读窗口/坐标全是逻辑像素（今天栽了四次的那个坑）
import ctypes

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

PKG = Path(r"C:\Users\Jestions\.dsh\desktop-mcp")
sys.path.insert(0, str(PKG))          # 必须在 import desktop_mcp 之前
SHOTS = Path(r"D:\ForDeepseek\DesktopMCP\tools\_shots")
SHOTS.mkdir(parents=True, exist_ok=True)
RESULT = SHOTS / "range_compare.jsonl"
N = 10

for suf in ("", ".circles"):
    p = Path(str(RESULT) + suf)
    if p.exists():
        p.unlink()

print("=" * 78)
print(f"① 启动靶场（{N} 个圆）")
range_proc = subprocess.Popen(
    [r"C:\Python314\python.exe", "tools/target_range.py", str(RESULT), str(N)],
    cwd=str(PKG), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

circles_file = Path(str(RESULT) + ".circles")
info = None
for _ in range(40):
    time.sleep(0.4)
    if circles_file.exists():
        try:
            info = json.loads(circles_file.read_text(encoding="utf-8"))
            break
        except Exception:
            pass
if not info:
    print("   ✗ 靶场没起来")
    if range_proc.stderr:
        print("   ", range_proc.stderr.read()[:300])
    sys.exit(1)

cs = info["circles"]
win = info["window"]
print(f"   ✓ 靶场就绪：窗口 {win['w']}x{win['h']} @({win['x']},{win['y']})")
for c in cs:
    print(f"     靶 {c['i']:>2}: 屏幕 ({c['x']},{c['y']})  半径 {c['r']}")

# 按"离屏幕中心由近到远"排序，再交替分配两种方式
cx0 = sum(c["x"] for c in cs) / len(cs)
cy0 = sum(c["y"] for c in cs) / len(cs)
ordered = sorted(cs, key=lambda c: math.hypot(c["x"] - cx0, c["y"] - cy0))
plan = []
for idx, c in enumerate(ordered):
    plan.append((c, "human" if idx % 2 == 0 else "plain"))

print()
print("② 交替分配（避免难易偏差）：")
for c, how in plan:
    d = math.hypot(c["x"] - cx0, c["y"] - cy0)
    print(f"     靶 {c['i']:>2}  离中心 {d:>5.0f}px  →  {'真人轨迹' if how == 'human' else '瞬移'}")

# 起服务器
srv = subprocess.Popen([r"C:\Python314\python.exe", "-m", "desktop_mcp.server"], cwd=str(PKG),
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
n = [0]


def tool(name, **a):
    n[0] += 1
    srv.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": "tools/call",
                                "params": {"name": name, "arguments": a}},
                               ensure_ascii=False) + "\n")
    srv.stdin.flush()
    line = srv.stdout.readline()
    if not line:
        raise RuntimeError("服务器无响应: " + (srv.stderr.read() or "")[:300])
    r = json.loads(line.strip()).get("result") or {}
    c = r.get("content") or []
    return "".join(x.get("text", "") for x in c if x.get("type") == "text")


srv.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18",
                                       "capabilities": {}}}) + "\n")
srv.stdin.flush()
srv.stdout.readline()

print()
print("③ 开点（每次先激活靶场窗口，再点靶心）")
print(f"   {'靶':>3} {'方式':<10}{'目标':>14}{'耗时':>8}  结果")
print("   " + "-" * 62)

# 找到靶场窗口并激活
from desktop_mcp import win32_window as W  # noqa: E402

timings = []
for c, how in plan:
    hits = [w for w in W.list_windows(limit=150) if "CLICK-RANGE" in (w.title or "")]
    if hits:
        W.activate(hits[0].hwnd)
        time.sleep(0.35)
    t0 = time.time()
    if how == "human":
        out = tool("desktop_click_human", x=c["x"], y=c["y"], screenshot=False, wait=0)
    else:
        out = tool("desktop_click", x=c["x"], y=c["y"], screenshot=False, wait=0)
    dt = time.time() - t0
    timings.append((c["i"], how, dt))
    land = [l for l in out.splitlines() if "落点复核" in l]
    label = "真人轨迹" if how == "human" else "瞬移"
    pos = f"({c['x']},{c['y']})".rjust(14)
    ok = "✓" if land and "✓ 一致" in land[0] else ""
    print(f"   {c['i']:>3} {label:<10}{pos}{dt:>7.2f}s  {ok}")

time.sleep(1.0)

print()
print("=" * 78)
print("④ 靶场判分（它按窗口实际收到的坐标算，与我无关）")
recs = [json.loads(l) for l in RESULT.read_text(encoding="utf-8").splitlines() if l.strip()]
shots = [r for r in recs if "shot" in r]
print(f"   {'靶':>3} {'方式':<10}{'收到的坐标':>18}{'离心距':>9}{'命中':>7}")
print("   " + "-" * 62)
by_method = {"human": [], "plain": []}
for (c, how), r in zip(plan, shots):
    by_method[how].append(r)
    mark = "✓" if r["hit"] else "✗"
    pos = f"({r['screen_x']},{r['screen_y']})".rjust(18)
    label = "真人轨迹" if how == "human" else "瞬移"
    print(f"   {c['i']:>3} {label:<10}{pos}{r['distance']:>8.1f}px{mark:>7}")

print()
print("=" * 78)
for how, label in (("plain", "瞬移 desktop_click"), ("human", "真人轨迹 desktop_click_human")):
    rs = by_method[how]
    if not rs:
        continue
    hits = sum(1 for r in rs if r["hit"])
    avg_d = sum(r["distance"] for r in rs) / len(rs)
    tm = [t for _, h, t in timings if h == how]
    avg_t = sum(tm) / len(tm) if tm else 0
    print(f"  {label:<32} 命中 {hits}/{len(rs)}   平均偏心 {avg_d:>5.1f}px   "
          f"平均耗时 {avg_t:.2f}s")

srv.stdin.close()
try:
    srv.wait(timeout=5)
except Exception:
    srv.kill()
if range_proc.poll() is None:
    range_proc.terminate()
print()
print(f"  靶场结果文件：{RESULT}")
