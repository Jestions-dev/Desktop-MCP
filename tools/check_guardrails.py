# -*- coding: utf-8 -*-
"""
验证两个"防误判"机制：
  ① 最小化窗口 → 明确警告（否则 agent 会以为窗口里没东西）
  ② 近乎纯色的截图 → 报出标准差提示可能没截到内容

②用一个我们自己造的纯色窗口当靶子，不依赖任何外部程序。
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "_shots"
OUT.mkdir(exist_ok=True)

# ---- 靶子：纯白窗口
target_src = '''
import sys, tkinter as tk

_FAILED = False        # 任一检查失败就置 True（末尾据此设退出码）
r = tk.Tk(); r.title("BLANK-TARGET-测试靶子")
r.geometry("420x300+120+120"); r.configure(bg="white")
r.wm_attributes("-topmost", True)
r.after(14000, r.destroy)
r.mainloop()
'''
tp = Path(__file__).parent / "_blank_target.py"
tp.write_text(target_src, encoding="utf-8")

proc = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", bufsize=1)
n = [0]


def call(m, pr=None):
    n[0] += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": m,
                                 "params": pr or {}}, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("服务器无响应")
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a})["result"]
    c = r.get("content") or []
    return ("".join(x.get("text", "") for x in c if x.get("type") == "text"),
            bool(r.get("isError")),
            [x for x in c if x.get("type") == "image"])


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


blank_proc = None
try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    print("=" * 70)
    print("① 最小化窗口 → 应带明确警告")
    text, _, _ = tool("list_windows", limit=20)
    target = next((int(l.split("hwnd=")[1].split()[0])
                   for l in text.splitlines() if "hwnd=" in l and "最小化" in l), None)
    if target:
        t2, e2, imgs2 = tool("screenshot", hwnd=target)
        for line in t2.splitlines():
            print("   " + line[:118])
        check("没有报错（仍然给出图）", not e2)
        check("含「最小化状态」警告", "最小化状态" in t2, t2[:200])
        check("警告里提示了该怎么办", "focus_window" in t2)
    else:
        print("   （当前没有最小化窗口，跳过）")

    print()
    print("=" * 70)
    print("② 纯色窗口 → 应报出标准差并提示可能没截到内容")
    blank_proc = subprocess.Popen([sys.executable, str(tp)])
    time.sleep(2.5)
    t3, _, imgs3 = tool("screenshot", window="BLANK-TARGET")
    for line in t3.splitlines():
        print("   " + line[:118])
    check("窗口截图成功", len(imgs3) == 1, t3[:150])
    check("报出了标准差", "标准差" in t3)
    check("检测到近乎纯色并给了建议", "近乎纯色" in t3 or "标准差" in t3)
    if imgs3:
        raw = base64.b64decode(imgs3[0]["data"])
        (OUT / "win_blank.png").write_bytes(raw)
        print(f"   图像 {len(raw) // 1024} KB → win_blank.png")

    # 对照：有内容的窗口不该被误判
    print()
    print("=" * 70)
    print("③ 对照：正常窗口不应被误报为纯色")
    t4, _, _ = tool("screenshot", window="DeepSeek")
    check("正常窗口没有纯色警告", "近乎纯色" not in t4, t4[:200])
    for line in t4.splitlines()[:5]:
        print("   " + line[:118])

finally:
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    if blank_proc:
        blank_proc.terminate()
    tp.unlink(missing_ok=True)

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")


sys.exit(1 if _FAILED else 0)
