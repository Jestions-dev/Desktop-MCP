# -*- coding: utf-8 -*-
"""
把观察框引擎打包成便携版（放进项目文件夹）

方案（已验证）：**官方 Electron runtime + 我们的 app 放进 resources/app/**
就够跑，不需要 node_modules —— 那个 junction 只是"Electron 退化成 Node 模式"
时才会用到的假象（见 README 的启动条件那节）。

产物：
    D:\\ForDeepseek\\DesktopMCP\\runtime\\
    ├── electron.exe          官方运行时（Chromium + Node + V8）
    ├── *.dll, *.pak, ...     它自带的依赖
    └── resources\\app\\        我们的 4 个文件（main.js / index.html / frame.css / package.json）
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUNTIME_SRC = Path(r"C:\Users\Jestions\.dsh\dsh-orb\electron-runtime")
APP_SRC = Path(r"C:\Users\Jestions\.dsh\desktop-mcp\frame")
APP_FILES = ["main.js", "package.json", "index.html", "frame.css"]
DEST = Path(r"D:\ForDeepseek\DesktopMCP\runtime")
APP_DEST = DEST / "resources" / "app"


def size_of(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1024 / 1024


print("=" * 70)
print("① 复制官方 runtime")
if DEST.exists():
    print("   目标已存在，先删（重建更干净）")
    shutil.rmtree(DEST)
print(f"   {RUNTIME_SRC}  →  {DEST}")
shutil.copytree(RUNTIME_SRC, DEST)
n = sum(1 for f in DEST.rglob("*") if f.is_file())
print(f"   {n} 个文件，{size_of(DEST):.1f} MB")

print()
print("② 放进我们的 app")
APP_DEST.mkdir(parents=True, exist_ok=True)
for f in APP_FILES:
    shutil.copy2(APP_SRC / f, APP_DEST / f)
    print(f"   + {f}  ({(APP_SRC / f).stat().st_size} 字节)")

print()
print("③ 删掉官方的默认 app（否则它可能抢先加载）")
for junk in ["default_app.asar"]:
    p = DEST / "resources" / junk
    if p.exists():
        p.unlink()
        print(f"   - resources/{junk}")
    else:
        print(f"   （没有 resources/{junk}）")

print()
print("④ 验货：结构对不对")
for p in ["electron.exe", "resources/app/main.js", "resources/app/package.json",
          "resources/app/index.html", "resources/app/frame.css"]:
    full = DEST / p.replace("/", os.sep)
    print(f"   {'✓' if full.exists() else '✗'} {p}")

print()
print("⑤ 实测：能不能起来 + 画框")
env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
p = subprocess.Popen([str(DEST / "electron.exe")], env=env, cwd=str(DEST),
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
hwnd = port = 0
t0 = time.time()
while time.time() - t0 < 25:
    line = p.stdout.readline()
    if not line:
        if p.poll() is not None:
            print(f"   ✗ 进程退出了 exit={p.returncode}")
            break
        continue
    try:
        m = json.loads(line.strip())
    except Exception:
        continue
    if m.get("event") == "ready":
        hwnd = m.get("hwnd", 0)
    if m.get("event") == "listening":
        port = m.get("port", 0)
    if hwnd and port:
        break

if hwnd and port:
    print(f"   ✓ ready: hwnd={hwnd} port={port}")
    import ctypes
    import urllib.request
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    data = json.dumps({"cmd": "show", "x": 900, "y": 550, "w": 600, "h": 400}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        print(f"   show → {r.read().decode()}")
    time.sleep(1.2)
    rc = wintypes.RECT()
    u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    got = (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
    want = (900 - 44, 550 - 44, 600 + 88, 400 + 88)
    print(f"   窗口 {got}")
    print(f"   期望 {want}   {'✓ 误差 0' if got == want else '✗ 不一致'}")
    print(f"   可见 = {bool(u.IsWindowVisible(wintypes.HWND(hwnd)))}")
else:
    err = (p.stderr.read() or "").strip()
    print("   ✗ 没起来")
    for l in [x for x in err.splitlines() if "disk_cache" not in x][:8]:
        print(f"     ! {l.strip()[:120]}")

try:
    p.stdin.close()
    p.wait(timeout=5)
except Exception:
    p.kill()

print()
print("=" * 70)
print(f"便携版位置：{DEST}")
print(f"体积：{size_of(DEST):.1f} MB")
