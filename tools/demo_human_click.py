# -*- coding: utf-8 -*-
"""
真轨迹端到端演示：起一个**新的** MCP 服务器进程（带最新代码），
用 desktop_click_human 走你录的那条"转圈"轨迹，落点点击。

为什么新起进程：DSH 里那个服务器是旧代码启动的，MCP 客户端不会热重载工具。
这里新起的进程协议完全一样，只是代码是新的。
"""
import json
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ⚠⚠ 必须在读任何窗口/光标坐标**之前**设 DPI 感知！
# 不设的话 GetCursorPos / GetWindowRect 返回的是**虚拟化坐标**（150% 屏上 ×2/3），
# 于是"验证"会把完全正确的移动判成偏差 851px。我在这上面连栽三次，
# 每次都是"尺子和被测对象不在同一个坐标系"。
import ctypes

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

PKG = r"C:\Users\Jestions\.dsh\desktop-mcp"
PY = r"C:\Python314\python.exe"

# 目标：桌面右下角一片空地（点它没有副作用）
TARGET_X, TARGET_Y = 2200, 1300
# 起点：左上角远处 —— 让路径尽可能长、尽可能显眼
START_X, START_Y = 400, 250
# 用那条转圈的
TRAJ = "traj_1791794446642.json"

srv = subprocess.Popen([PY, "-m", "desktop_mcp.server"], cwd=PKG,
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
        raise RuntimeError("无响应: " + (srv.stderr.read() or "")[:400])
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return ("".join(x.get("text", "") for x in c if x.get("type") == "text"),
            bool(r.get("isError")))


try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    print("=" * 76)
    print("先用普通 desktop_click 让大家看清起点")
    t, e = tool("desktop_click", x=START_X, y=START_Y, screenshot=False)
    print(f"  光标已移到起点 ({START_X},{START_Y})")
    time.sleep(0.6)

    print()
    print("=" * 76)
    print(f"现在用真人轨迹点击 → ({TARGET_X},{TARGET_Y})")
    print(f"  轨迹：{TRAJ}（你转了两圈那条，389 点 / 3216ms）")
    print(f"  起点 ({START_X},{START_Y}) → 终点 ({TARGET_X},{TARGET_Y})")
    print("  注意看：光标会先绕圈再落过去 —— 不是一条直线")
    print()
    t0 = time.time()
    t, e = tool("desktop_click_human",
                x=TARGET_X, y=TARGET_Y,
                from_x=START_X, from_y=START_Y,
                trajectory=TRAJ,
                wait=0,
                screenshot=False)
    dt = time.time() - t0
    print(f"  isError = {e}   实际耗时 {dt:.1f}s")
    for line in t.splitlines():
        print("   ", line)

    import ctypes

    class PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    # ⚠ 点完**立刻**读光标位置。中间只要插一个 sleep，用户一动鼠标读到就是别处，
    # 会被误判成"没落准"（我就这么骗了自己一轮）。
    p = PT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    print()
    print(f"  点击后光标实际位置：({p.x},{p.y})   目标 ({TARGET_X},{TARGET_Y})")
    print(f"  → {'✓ 落在目标上' if abs(p.x - TARGET_X) <= 3 and abs(p.y - TARGET_Y) <= 3 else '✗ 偏了'}")
finally:
    srv.stdin.close()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()
