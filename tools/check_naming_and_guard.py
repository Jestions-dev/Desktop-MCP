# -*- coding: utf-8 -*-
"""
验证工具改名 + 截图快捷键拦截（把 2026-10-12 这两处改动固化下来）

改名理由：裸名 click/wait 在客户端省略命名空间时无法自解释。
拦截理由：注入 Win+Shift+S 会拉起系统截图 UI，和"agent 自己截图"语义冲突。
"""
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))

EXPECTED = [
    "desktop_screenshot", "desktop_click", "desktop_type", "desktop_press",
    "desktop_move", "desktop_drag", "desktop_scroll", "desktop_list_windows",
    "desktop_foreground_window", "desktop_focus_window", "desktop_measure_window",
    "desktop_wait", "desktop_highlight",
]

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


print("=" * 70)
print("① 工具名全部带 desktop_ 前缀，且与分发表一致")
from desktop_mcp import tools as T

names = [t["name"] for t in T.list_tools()]
check("13 个工具", len(names) == 13, f"实际 {len(names)}")
check("名字与预期完全一致", names == EXPECTED,
      f"差集 {set(names) ^ set(EXPECTED)}")
check("全部以 desktop_ 开头", all(n.startswith("desktop_") for n in names))
check("分发表键与工具名一致", set(T._DISPATCH) == set(names),
      f"差集 {set(T._DISPATCH) ^ set(names)}")
check("每个工具都有描述和 object schema",
      all(t.get("description", "").strip() and
          t.get("inputSchema", {}).get("type") == "object" for t in T.list_tools()))

print()
print("=" * 70)
print("② 截图快捷键拦截")
from desktop_mcp import win32_input as I

_FAILED = False        # 任一检查失败就置 True（末尾据此设退出码）

BLOCK = ["win+shift+s", "win+shift+3", "win+shift+4", "win+shift+5",
         "printscreen", "snapshot", "lwin+shift+s"]
ALLOW = ["ctrl+s", "alt+tab", "ctrl+shift+esc", "win+r", "win+d",
         "ctrl+c", "shift+3", "win+shift+t"]

for chord in BLOCK:
    try:
        I.reject_screenshot_chord(chord.replace("+", " ").split())
        check(f"{chord:16} 应被拦", False, "却放过了")
    except ValueError:
        check(f"{chord:16} 被拦", True)

for chord in ALLOW:
    try:
        I.reject_screenshot_chord(chord.replace("+", " ").split())
        check(f"{chord:16} 放过", True)
    except ValueError as e:
        check(f"{chord:16} 应放过", False, str(e)[:60])

print()
print("=" * 70)
print("③ 端到端：服务器报新名字，旧名字失效")
p = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"], cwd=str(PKG),
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", bufsize=1)
n = [0]


def call(m, pr=None):
    n[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": m,
                              "params": pr or {}}, ensure_ascii=False) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline().strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return ("".join(x.get("text", "") for x in c if x.get("type") == "text"),
            bool(r.get("isError")), len([x for x in c if x.get("type") == "image"]))


try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    listed = [t["name"] for t in call("tools/list")["result"]["tools"]]
    check("tools/list 报 13 个新名", listed == EXPECTED)

    t, e, imgs = tool("desktop_list_windows", limit=3)
    check("desktop_list_windows 可调用", not e, t[:80])

    t, e, _ = tool("click")                      # 旧名
    check("旧名 click 报未知工具", e and "未知工具" in t, t[:80])

    t, e, _ = tool("desktop_press", keys="win+shift+s")
    check("注入 Win+Shift+S 被拒（isError）", e and "不允许" in t, t[:100])
    print(f"      → {t.splitlines()[0][:90]}")

    t, e, _ = tool("desktop_press", keys="ctrl+a")
    check("正常组合键仍可用", not e, t[:80])
finally:
    p.stdin.close()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")


sys.exit(1 if _FAILED else 0)
