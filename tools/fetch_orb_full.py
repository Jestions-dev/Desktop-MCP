# -*- coding: utf-8 -*-
"""拉取 dsh-orb 的完整源码参考（要照抄它的做法）"""
import base64
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GH = r"C:\Program Files\GitHub CLI\gh.exe"
REPO = "mini-yifan/dsh-orb-cordis"
DEST = Path(r"C:\Users\Jestions\.dsh\desktop-mcp\参考_dsh-orb")

WANT = [
    # 框架的核心：建窗 + 定位 + 显示/隐藏
    "packages/helper/src/overlays.ts",
    "packages/helper/src/overlay-geometry.ts",
    "packages/helper/src/chrome-windows.ts",
    "packages/helper/src/cloak.ts",
    # 那个发光框本身
    "packages/helper/assets/observation-frame.html",
    "packages/helper/assets/observation-frame.css",
    # Electron 运行时怎么起的（进程管理）
    "packages/host/src/electron-runtime.ts",
    "packages/host/src/helper-path.ts",
    "packages/host/src/services.ts",
    "packages/host/src/index.ts",
]


def gh(args):
    r = subprocess.run([GH] + args, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return r.stdout


DEST.mkdir(parents=True, exist_ok=True)
for path in WANT:
    try:
        raw = gh(["api", f"repos/{REPO}/contents/{path}"])
        content = base64.b64decode(json.loads(raw)["content"])
        out = DEST / Path(path).name
        out.write_bytes(content)
        lines = content.decode("utf-8", "replace").count("\n") + 1
        print(f"  ✓ {Path(path).name:<28} {len(content):>7} 字节 / {lines:>4} 行")
    except Exception as e:
        print(f"  ✗ {path}  {e}")

print(f"\n都在 {DEST}")
