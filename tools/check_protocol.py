# -*- coding: utf-8 -*-
"""
desktop-mcp 的协议合规检查（只测这个服务器）

只查"接口返回对不对"，不查功能。重点：
  · initialize 的版本协商与能力声明
  · 消息形状：result vs error、id 回传、通知不产生响应
  · **image content 是否符合规范**（截图返回图像，这是它特有的）
  · 工具执行失败必须是 result.isError（不是 JSON-RPC error）
  · 未知方法 → -32601

⚠ 探针自己踩过的坑：服务器会主动发通知（没有 id）。读取必须**按 id 匹配**，
不能"读一行就当响应"，否则会把通知当成响应、后面全部错位。
"""
import base64
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = r"C:\Users\Jestions\.dsh\desktop-mcp"
PY = r"C:\Python314\python.exe"

ok = total = 0


def check(label, cond, detail=""):
    global ok, total
    total += 1
    if cond:
        ok += 1
    print(f"   {'✓' if cond else '✗'} {label}" + ("" if cond else f"\n        {detail}"))
    return bool(cond)


class Conn:
    def __init__(self):
        env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
        env["PYTHONIOENCODING"] = "utf-8"
        self.p = subprocess.Popen([PY, "-m", "desktop_mcp.server"], cwd=PKG, env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  bufsize=1)
        self.n = 0
        self.notifications = []

    def _send_raw(self, msg):
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def call(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self._send_raw(msg)
        if notify:
            return None
        return self.read(want_id=self.n)

    def read(self, want_id=None, max_lines=15):
        skipped = []
        for _ in range(max_lines):
            line = self.p.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in m:                       # 通知，不算响应
                skipped.append(m.get("method"))
                continue
            if want_id is None or m.get("id") == want_id:
                self.notifications.extend(skipped)
                return m
            skipped.append(f"id={m.get('id')}")
        return None

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


c = Conn()
try:
    print("=" * 74)
    print("① initialize / 生命周期")
    r = c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "probe", "version": "1"}})
    res = (r or {}).get("result") or {}
    caps = res.get("capabilities") or {}
    si = res.get("serverInfo") or {}
    check("返回 result（不是 error）", bool(res), str(r)[:140])
    check("jsonrpc = \"2.0\"", (r or {}).get("jsonrpc") == "2.0", str(r)[:100])
    check("id 原样回传", (r or {}).get("id") == 1, str(r)[:100])
    check(f"protocolVersion 合法（{res.get('protocolVersion')}）",
          res.get("protocolVersion") in ("2025-06-18", "2025-03-26", "2024-11-05"))
    check(f"声明了 tools 能力（{list(caps)}）", "tools" in caps)
    check("未声明 resources（纯工具服务器）", "resources" not in caps, str(list(caps)))
    check(f"serverInfo 完整（{si.get('name')} v{si.get('version')}）",
          bool(si.get("name") and si.get("version")))

    print()
    print("② 旧版客户端也应该被接受")
    r = c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    v = ((r or {}).get("result") or {}).get("protocolVersion")
    check(f"回显客户端支持的版本（{v}）", v == "2024-11-05", str(r)[:120])
    r = c.call("initialize", {"protocolVersion": "2099-01-01", "capabilities": {}})
    v = ((r or {}).get("result") or {}).get("protocolVersion")
    check(f"未知版本 → 回自己最新版（{v}）", v == "2025-06-18", str(r)[:120])

    print()
    print("③ 通知（没有 id）不该产生响应")
    before = len(c.notifications)
    c.call("notifications/initialized", notify=True)
    got = c.call("ping")
    check("下一条带 id 的消息就是 ping 的回包", (got or {}).get("id") == c.n,
          str(got)[:120])
    check("收到过服务器主动发的通知（list_changed 之类）",
          len(c.notifications) > before, str(c.notifications[:4]))

    print()
    print("④ tools/list")
    tools = ((c.call("tools/list") or {}).get("result") or {}).get("tools") or []
    check(f"返回工具数组（{len(tools)} 个）", bool(tools))
    check("每项有 name / description / inputSchema.type=object",
          all(t.get("name") and t.get("description") and
              (t.get("inputSchema") or {}).get("type") == "object" for t in tools),
          str([t.get("name") for t in tools if not t.get("description")])[:120])
    names = [t["name"] for t in tools]
    check("工具名唯一", len(names) == len(set(names)))
    check(f"全部带 desktop_ 前缀", all(n.startswith("desktop_") for n in names),
          str([n for n in names if not n.startswith("desktop_")]))

    print()
    print("⑤ tools/call 成功路径")
    r = c.call("tools/call", {"name": "desktop_list_windows", "arguments": {"limit": 2}})
    res = (r or {}).get("result") or {}
    cont = res.get("content")
    check("返回 result.content 数组", isinstance(cont, list) and bool(cont), str(r)[:140])
    check("每项都有 type", all(isinstance(x, dict) and x.get("type") for x in (cont or [])))
    check("text 项带 text 字段",
          all("text" in x for x in (cont or []) if x.get("type") == "text"))
    check("成功时**不带** isError", res.get("isError") in (None, False), str(res.get("isError")))

    print()
    print("⑥ image content 的形状（desktop-mcp 特有）")
    r = c.call("tools/call", {"name": "desktop_screenshot",
                              "arguments": {"window": False, "max_width": 400}})
    res = (r or {}).get("result") or {}
    cont = res.get("content") or []
    imgs = [x for x in cont if x.get("type") == "image"]
    check("截图返回 image content", len(imgs) == 1, str(cont)[:200])
    if imgs:
        im = imgs[0]
        check(f"mimeType = image/png（实为 {im.get('mimeType')}）", im.get("mimeType") == "image/png")
        data = im.get("data") or ""
        good = False
        try:
            good = base64.b64decode(data)[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception:
            pass
        check(f"data 是合法 base64 且解码后是 PNG（{len(data) // 1024} KB）", good)
        check("image 项没有多余字段（规范只认 type/data/mimeType）",
              set(im) <= {"type", "data", "mimeType"}, str(sorted(im)))
        check("图像和文本可以同时出现（截图工具就是）",
              any(x.get("type") == "text" for x in cont))
        check("**没有**把 base64 塞进 text 字段（那样模型看不到图）",
              all("data:image" not in (x.get("text") or "") for x in cont))

    print()
    print("⑦ 工具执行失败 → result.isError，而不是协议层 error")
    r = c.call("tools/call", {"name": "绝对不存在的工具", "arguments": {}})
    res = (r or {}).get("result") or {}
    check("未知工具 → isError = true", res.get("isError") is True, str(r)[:160])
    check("并且**没有** JSON-RPC error（否则客户端会当成协议故障）", "error" not in (r or {}))
    check("失败时 content 仍是数组（消息体在 text 里）",
          isinstance(res.get("content"), list) and bool(res["content"]))
    r = c.call("tools/call", {"name": "desktop_list_windows", "arguments": "字符串不是对象"})
    check("参数类型错也是 result.isError（不是协议 error）",
          ((r or {}).get("result") or {}).get("isError") is True, str(r)[:160])
    r = c.call("tools/call", {"name": "desktop_screenshot",
                              "arguments": {"window": "绝对不存在的窗口xyz"}})
    check("找不到窗口 → isError（工具层自己判定的失败）",
          ((r or {}).get("result") or {}).get("isError") is True, str(r)[:160])

    print()
    print("⑧ 协议层错误")
    r = c.call("prompts/list")
    e = (r or {}).get("error") or {}
    check(f"未知方法 → -32601（实得 {e.get('code')}）", e.get("code") == -32601, str(r)[:140])
    check("error 同时有 code 和 message", "code" in e and "message" in e)
    check("错误响应里没有 result", "result" not in (r or {}))

    print()
    print("⑨ 脏输入不能让服务器崩")
    c.p.stdin.write("这不是 JSON\n")
    c.p.stdin.flush()
    check("发一行坏 JSON 后服务器还活着", (c.call("ping") or {}).get("id") == c.n)

finally:
    c.close()

print()
print("=" * 74)
print(f"合计：{ok}/{total} 项符合规范" + ("　🎉" if ok == total else ""))
