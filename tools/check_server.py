# -*- coding: utf-8 -*-
"""
端到端检查：起服务器，调只读工具，重点验证 **image content 返回**。

只调不碰输入的工具（screenshot / list_windows / get_foreground_window /
measure_window）—— 全程不动鼠标键盘。
"""
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
proc = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
_n = [0]
shots = []


def call(method, params=None):
    _n[0] += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _n[0], "method": method,
                                 "params": params or {}}, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("服务器无响应")
    return json.loads(line.strip())


def tool(name, **args):
    r = call("tools/call", {"name": name, "arguments": args})
    res = r.get("result") or {}
    content = res.get("content") or []
    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    imgs = [c for c in content if c.get("type") == "image"]
    return text, bool(res.get("isError")), imgs


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
    print("=" * 70)
    print("① initialize / 能力声明")
    init = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    res = init["result"]
    print(f"   protocolVersion = {res['protocolVersion']}")
    print(f"   serverInfo      = {res['serverInfo']}")
    print(f"   capabilities    = {json.dumps(res['capabilities'], ensure_ascii=False)}")
    check("版本回显正确", res["protocolVersion"] == "2025-06-18")
    check("声明了 tools 能力", "tools" in res["capabilities"])
    check("未声明 resources（纯工具）", "resources" not in res["capabilities"])

    print()
    print("=" * 70)
    print("② tools/list")
    tl = call("tools/list")["result"]["tools"]
    names = [t["name"] for t in tl]
    print(f"   {len(tl)} 个工具：")
    for n in names:
        print(f"     · {n}")
    check("工具数 = 13", len(tl) == 13, f"实际 {len(tl)}")
    check("每个都有 description 和 schema",
          all(t.get("description") and t.get("inputSchema", {}).get("type") == "object" for t in tl))

    print()
    print("=" * 70)
    print("③ screenshot（整屏，缩到 1280 宽）—— 重点：图像能否返回")
    text, is_err, imgs = tool("screenshot", max_width=1280)
    print("   文本：")
    for line in text.splitlines():
        print("     " + line)
    check("没有报错", not is_err, text[:120])
    check("返回了 1 张图像", len(imgs) == 1, f"实际 {len(imgs)} 张")
    if imgs:
        raw = base64.b64decode(imgs[0]["data"])
        shots.append(("full", raw))
        print(f"   mimeType = {imgs[0]['mimeType']}   解码后 {len(raw) // 1024} KB")
        check("是合法 PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")
        check("非空", len(raw) > 5000, f"只有 {len(raw)} 字节")

    print()
    print("=" * 70)
    print("④ screenshot 只截一块（省上下文）")
    text, is_err, imgs = tool("screenshot", x=100, y=100, width=500, height=320)
    check("区域截图成功", not is_err and len(imgs) == 1, text[:120])
    if imgs:
        raw = base64.b64decode(imgs[0]["data"])
        shots.append(("region", raw))
        print(f"   区域图 {len(raw) // 1024} KB")
    print("   " + text.splitlines()[0])

    print()
    print("=" * 70)
    print("⑤ list_windows")
    text, is_err, _ = tool("list_windows", limit=12)
    check("没报错", not is_err, text[:120])
    for line in text.splitlines()[:8]:
        print("     " + line[:120])

    print()
    print("=" * 70)
    print("⑥ get_foreground_window（含截图）")
    text, is_err, imgs = tool("get_foreground_window")
    check("没报错", not is_err, text[:150])
    check("带回了截图", len(imgs) == 1)
    for line in text.splitlines()[:3]:
        print("     " + line[:120])

    print()
    print("=" * 70)
    print("⑦ measure_window（分数坐标换算）")
    text, is_err, _ = tool("list_windows", limit=1)
    first = [l for l in text.splitlines() if "hwnd=" in l]
    if first:
        hwnd = int(first[0].split("hwnd=")[1].split()[0])
        text, is_err, _ = tool("measure_window", hwnd=hwnd)
        check("量窗口成功", not is_err, text[:150])
        for line in text.splitlines():
            print("     " + line[:120])
    else:
        print("   （没有可用窗口，跳过）")

    print()
    print("=" * 70)
    print("⑧ highlight（未启用观察框时应给出明确错误，而不是崩）")
    text, is_err, _ = tool("highlight", x=200, y=200, width=300, height=200)
    check("未启用时返回 isError 且说明原因",
          is_err and "观察框未启用" in text, text[:120])
    print(f"     {text[:100]}")

    print()
    print("=" * 70)
    print("⑨ 未知工具 / 未知方法")
    text, is_err, _ = tool("no_such_tool")
    check("未知工具 → isError", is_err, text[:80])
    msg = call("prompts/list")
    check("未知方法 → -32601", (msg.get("error") or {}).get("code") == -32601)

finally:
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    se = proc.stderr.read()
    if se.strip():
        print()
        print("[服务器 stderr]")
        for line in se.strip().splitlines()[:6]:
            print("   " + line)

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")

# 把截图存下来，让人也能看
out = Path(__file__).resolve().parent / "_shots"
out.mkdir(exist_ok=True)
for name, raw in shots:
    p = out / f"{name}.png"
    p.write_bytes(raw)
    print(f"截图已存：{p}")


sys.exit(1 if _FAILED else 0)
