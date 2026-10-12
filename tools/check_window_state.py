# -*- coding: utf-8 -*-
"""
验证 desktop_focus_window 的四种动作：activate / maximize / minimize / restore

用记事本当靶子（前面测试里它稳定存在）。每步都用 Win32 查真实状态，
不看工具自己怎么说 —— 免得"工具说成功但窗口没动"这种假绿。
"""
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(r"C:\Users\Jestions\.dsh\desktop-mcp")
sys.path.insert(0, str(PKG))
from desktop_mcp import win32_window as W

u = ctypes.WinDLL("user32", use_last_error=True)

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"   ✓ {label}")
    else:
        fail += 1
        print(f"   ✗ {label}  {detail}")


srv = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", bufsize=1)
_n = [0]


def call(m, pr=None):
    _n[0] += 1
    srv.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _n[0], "method": m,
                                "params": pr or {}}, ensure_ascii=False) + "\n")
    srv.stdin.flush()
    line = srv.stdout.readline()
    if not line:
        raise RuntimeError("无响应：" + (srv.stderr.read() or "")[:300])
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return ("".join(x.get("text", "") for x in c if x.get("type") == "text"),
            bool(r.get("isError")))


def real_state(hwnd):
    return W.state_of(hwnd)


try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    print("=" * 70)
    print("① 找记事本")
    t, _ = tool("desktop_list_windows", query="记事本")
    cand = [l for l in t.splitlines() if "hwnd=" in l]
    if not cand:
        print("   ✗ 没找到记事本 —— 请先打开一个记事本窗口")
        raise SystemExit(1)
    hwnd = int(cand[0].split("hwnd=")[1].split()[0])
    print(f"   {cand[0].strip()[:100]}")
    print(f"   初始真实状态：{real_state(hwnd)}")

    print()
    print("=" * 70)
    print("② action=activate（默认）")
    t, e = tool("desktop_focus_window", hwnd=hwnd, screenshot=False)
    time.sleep(0.4)
    print(f"   工具说：{t[:90]}  isError={e}")
    check("窗口成为前台", u.GetForegroundWindow() == hwnd,
          f"前台是 {u.GetForegroundWindow()}")

    print()
    print("=" * 70)
    print("③ action=maximize")
    t, e = tool("desktop_focus_window", hwnd=hwnd, action="maximize", screenshot=False)
    time.sleep(0.5)
    print(f"   工具说：{t[:90]}  isError={e}")
    check("真实状态 = maximized", real_state(hwnd) == "maximized", real_state(hwnd))

    print()
    print("=" * 70)
    print("④ action=restore")
    t, e = tool("desktop_focus_window", hwnd=hwnd, action="restore", screenshot=False)
    time.sleep(0.5)
    print(f"   工具说：{t[:90]}  isError={e}")
    check("真实状态 = normal", real_state(hwnd) == "normal", real_state(hwnd))

    print()
    print("=" * 70)
    print("⑤ action=minimize")
    t, e = tool("desktop_focus_window", hwnd=hwnd, action="minimize", screenshot=False)
    time.sleep(0.5)
    print(f"   工具说：{t[:90]}  isError={e}")
    check("真实状态 = minimized", real_state(hwnd) == "minimized", real_state(hwnd))

    print()
    print("=" * 70)
    print("⑥ 从最小化直接 activate（应该自动还原并到前台）")
    t, e = tool("desktop_focus_window", hwnd=hwnd, screenshot=False)
    time.sleep(0.5)
    print(f"   工具说：{t[:90]}  isError={e}")
    check("真实状态 = normal 或 maximized",
          real_state(hwnd) in ("normal", "maximized"), real_state(hwnd))
    check("并且到了前台", u.GetForegroundWindow() == hwnd)

    print()
    print("=" * 70)
    print("⑦ 非法动作应报错")
    t, e = tool("desktop_focus_window", hwnd=hwnd, action="explode", screenshot=False)
    check("非法 action → isError", e and "不认识" in t, t[:80])
    print(f"   {t[:80]}")

finally:
    srv.stdin.close()
    try:
        srv.wait(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")
