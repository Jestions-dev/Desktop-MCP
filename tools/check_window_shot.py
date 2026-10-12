# -*- coding: utf-8 -*-
"""验证窗口截图：默认截前台窗口 / client_only / 指定窗口 / 整屏退化"""
import base64
import json
import subprocess
import sys
from pathlib import Path

_FAILED = False        # 任一检查失败就置 True（末尾据此设退出码）

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "_shots"
OUT.mkdir(exist_ok=True)

p = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", bufsize=1)
n = [0]


def call(m, pr=None):
    n[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": m,
                              "params": pr or {}}, ensure_ascii=False) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    if not line:
        raise RuntimeError("服务器无响应：" + (p.stderr.read() or "")[:400])
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a})["result"]
    c = r.get("content") or []
    text = "".join(x.get("text", "") for x in c if x.get("type") == "text")
    imgs = [x for x in c if x.get("type") == "image"]
    return text, bool(r.get("isError")), imgs


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


try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    cases = [
        ("默认（前台窗口）", {}, "win_foreground"),
        ("client_only（客户区）", {"client_only": True}, "win_client"),
        ("整屏（window=false）", {"window": False}, "win_screen"),
    ]
    for label, kwargs, fname in cases:
        print("=" * 68)
        print(f"① {label}")
        text, is_err, imgs = tool("screenshot", **kwargs)
        for line in text.splitlines()[:6]:
            print("   " + line[:110])
        check("没报错", not is_err, text[:120])
        check("带回了图像", len(imgs) == 1, f"{len(imgs)} 张")
        if imgs:
            raw = base64.b64decode(imgs[0]["data"])
            (OUT / f"{fname}.png").write_bytes(raw)
            print(f"   图像 {len(raw) // 1024} KB → {fname}.png")
            check("是合法 PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")

    print()
    print("=" * 68)
    print("② 按 hwnd 截指定窗口（Ableton，最小化状态）")
    text, _, _ = tool("list_windows", limit=20)
    target = None
    for line in text.splitlines():
        if "hwnd=" in line and "Ableton" in line:
            target = int(line.split("hwnd=")[1].split()[0])
            print("   目标：" + line.strip()[:100])
            break
    if target:
        t2, e2, imgs2 = tool("screenshot", hwnd=target)
        for line in t2.splitlines()[:5]:
            print("   " + line[:110])
        check("最小化窗口也能截到内容（PrintWindow 的意义）", not e2 and len(imgs2) == 1,
              t2[:150])
        if imgs2:
            raw = base64.b64decode(imgs2[0]["data"])
            (OUT / "win_ableton.png").write_bytes(raw)
            print(f"   图像 {len(raw) // 1024} KB → win_ableton.png")
    else:
        print("   （没找到 Ableton 窗口，跳过）")

    print()
    print("=" * 68)
    print("③ 按关键词截窗口（应能唯一定位或报歧义）")
    t3, e3, imgs3 = tool("screenshot", window="DeepSeek")
    check("关键词匹配成功", not e3 and len(imgs3) == 1, t3[:150])
    for line in t3.splitlines()[:4]:
        print("   " + line[:110])
    if imgs3:
        (OUT / "win_bykeyword.png").write_bytes(base64.b64decode(imgs3[0]["data"]))

    print()
    print("=" * 68)
    print("④ 不存在的窗口关键词 → 明确报错")
    t4, e4, _ = tool("screenshot", window="绝对不存在的窗口xyz")
    check("报 isError 且说明", e4 and "没找到" in t4, t4[:120])
    print("   " + t4[:100])

finally:
    p.stdin.close()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()

print()
print("=" * 68)
print(f"结果：{ok} 项通过，{fail} 项失败")


sys.exit(1 if _FAILED else 0)
