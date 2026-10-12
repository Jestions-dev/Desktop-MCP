# -*- coding: utf-8 -*-
"""
验证「官方 Electron runtime + 我们的 app」能不能不依赖 node_modules 就跑起来

如果能，打包就很简单：拷 runtime + 把我们的 app 放进 resources/app/。
如果不能，就得保留 node_modules（那就不便携了）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUNTIME = Path(r"C:\Users\Jestions\.dsh\dsh-orb\electron-runtime")
OUR_FRAME = Path(r"C:\Users\Jestions\.dsh\desktop-mcp\frame")
APP_FILES = ["main.js", "package.json", "index.html", "frame.css"]


def build_portable(dest: Path) -> Path:
    """把 runtime 拷进 dest，并把我们的 app 放进 resources/app/"""
    if dest.exists():
        shutil.rmtree(dest)
    print(f"  复制 runtime → {dest}")
    shutil.copytree(RUNTIME, dest)
    app = dest / "resources" / "app"
    app.mkdir(parents=True, exist_ok=True)
    for f in APP_FILES:
        shutil.copy2(OUR_FRAME / f, app / f)
    print(f"  app 放进 {app}")
    return dest / "electron.exe"


def try_run(exe: Path, cwd: Path, env_clean: bool):
    """启动它，等 ready/超时，返回 (成功, 输出, 错误)"""
    env = dict(os.environ)
    if env_clean:
        env.pop("ELECTRON_RUN_AS_NODE", None)
    p = subprocess.Popen([str(exe)], env=env, cwd=str(cwd),
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
    hwnd = port = 0
    deadline = time.time() + 20
    out_lines = []
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        line = line.strip()
        if not line:
            continue
        out_lines.append(line)
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("event") == "ready":
            hwnd = m.get("hwnd", 0)
        if m.get("event") == "listening":
            port = m.get("port", 0)
        if hwnd and port:
            break
    ok = bool(hwnd and port)
    try:
        p.stdin.close()
        p.wait(timeout=5)
    except Exception:
        p.kill()
    err = (p.stderr.read() or "").strip()
    return ok, out_lines, err, hwnd, port


print("=" * 72)
print("① 搭一个便携目录（runtime + resources/app）")
tmp = Path(tempfile.gettempdir()) / "desktop_mcp_portable_test"
exe = build_portable(tmp)
size = sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file())
n = sum(1 for f in tmp.rglob("*") if f.is_file())
print(f"  大小 {size / 1024 / 1024:.1f} MB，{n} 个文件")

print()
print("② app 里**没有** node_modules —— 还能跑吗？")
print(f"   node_modules 存在: {(tmp / 'resources' / 'app' / 'node_modules').exists()}")
ok, out, err, hwnd, port = try_run(exe, tmp, env_clean=True)
print(f"   ready: hwnd={hwnd} port={port}  → {'✓ 能跑！' if ok else '✗ 起不来'}")
for l in out[:4]:
    print(f"     ← {l[:100]}")
if err:
    for l in [x for x in err.splitlines() if "disk_cache" not in x][:6]:
        print(f"     ! {l.strip()[:120]}")

print()
print("③ 既然能跑，再确认它能画框（发一条 show 指令）")
if ok:
    import urllib.request
    p = subprocess.Popen([str(exe)], env={k: v for k, v in os.environ.items()
                                          if k != "ELECTRON_RUN_AS_NODE"},
                         cwd=str(tmp), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
    h = pt = 0
    t0 = time.time()
    while time.time() - t0 < 20:
        line = p.stdout.readline()
        if not line:
            break
        try:
            m = json.loads(line.strip())
        except Exception:
            continue
        if m.get("event") == "ready":
            h = m.get("hwnd", 0)
        if m.get("event") == "listening":
            pt = m.get("port", 0)
        if h and pt:
            break
    if h and pt:
        data = json.dumps({"cmd": "show", "x": 800, "y": 500, "w": 500, "h": 350}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{pt}/", data=data,
                                     headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"   show → {r.read().decode()}")
        time.sleep(1.2)
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        rc = wintypes.RECT()
        u.GetWindowRect(wintypes.HWND(h), ctypes.byref(rc))
        got = (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
        want = (800 - 44, 500 - 44, 500 + 88, 350 + 88)
        print(f"   窗口 {got}  期望 {want}  {'✓' if got == want else '✗'}")
        print("   ★ 便携版能画框，说明打包方案成立")
    p.stdin.close()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()

print()
print("=" * 72)
print(f"结论：{'官方 runtime + resources/app 就够了，不需要 node_modules' if ok else '还需要别的依赖，得再查'}")
print(f"临时目录: {tmp}（测完可删）")
