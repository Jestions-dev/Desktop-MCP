# -*- coding: utf-8 -*-
"""拉取 dsh-orb 的源码参考文件（只读参考，不复制代码）"""
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
    # 那个"框框"
    "packages/helper/assets/observation-frame.css",
    "packages/helper/assets/observation-frame.html",
    "packages/helper/assets/selection-toolbar.css",
    "packages/helper/assets/selection-toolbar.html",
    "packages/helper/src/overlay-geometry.ts",
    "packages/helper/src/overlays.ts",
    # Win32 与前台窗口
    "packages/computer-use/src/overlay-guard.ts",
    "packages/computer-use/src/windows-foreground.ts",
    # 文档
    "docs/02-architecture.md",
    "packages/computer-use/README.zh.md",
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
        print(f"  ✓ {Path(path).name:<34} {len(content):>7} 字节 / {lines:>4} 行")
    except Exception as e:
        print(f"  ✗ {path}  {e}")

print(f"\n已存到 {DEST}")
print("（只作参考阅读；我们要写的是 Python 版，不复制它的代码）")
