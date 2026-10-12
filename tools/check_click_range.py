# -*- coding: utf-8 -*-
"""
点击靶场测试：agent 视角的完整闭环

流程：启动靶场 → 截图看 → 读圆心坐标 → 逐个点击 → 靶场回报"打中没有/偏多少" → 再截图确认

关键：**部分点击故意加偏移**（±10~22px），用来验证靶场的判定确实分得清
"命中圆心"和"差一点"—— 全都精准命中反而说明不了判定是可用的。
"""
import base64
import json
import random
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
RESULT = OUT / "range_result.jsonl"
for suf in ("", ".circles"):
    Path(str(RESULT) + suf).unlink(missing_ok=True)

N = 5
range_proc = subprocess.Popen([sys.executable, str(Path(__file__).parent / "target_range.py"),
                               str(RESULT), str(N)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        raise RuntimeError("服务器无响应")
    return json.loads(line.strip())


def tool(name, **a):
    r = call("tools/call", {"name": name, "arguments": a}).get("result") or {}
    c = r.get("content") or []
    return ("".join(x.get("text", "") for x in c if x.get("type") == "text"),
            bool(r.get("isError")),
            [x for x in c if x.get("type") == "image"])


def save(imgs, name):
    if imgs:
        raw = base64.b64decode(imgs[0]["data"])
        (OUT / name).write_bytes(raw)
        return len(raw)
    return 0


def shots():
    if not RESULT.exists():
        return []
    return [json.loads(l) for l in RESULT.read_text(encoding="utf-8").splitlines() if l.strip()]


ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"   ✓ {label}")
    else:
        fail += 1
        print(f"   ✗ {label}  {detail}")


try:
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

    print("=" * 74)
    print("① 等靶场窗口就绪")
    info = None
    for _ in range(40):
        time.sleep(0.25)
        p = Path(str(RESULT) + ".circles")
        if p.exists():
            try:
                info = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                pass
    if not info:
        print("   ✗ 靶场没起来")
        raise SystemExit(1)
    w = info["window"]
    print(f"   窗口 ({w['x']},{w['y']}) {w['w']}×{w['h']}")
    print(f"   画布原点 ({info['canvas_origin']['x']},{info['canvas_origin']['y']})")
    print(f"   圆心（屏幕坐标）：")
    for c in info["circles"]:
        print(f"      #{c['i']}  ({c['x']}, {c['y']})  r={c['r']}")

    print()
    print("=" * 74)
    print("② 先截图看一眼（确认我能看到靶场长什么样）")
    text, err, imgs = tool("desktop_screenshot", window="CLICK-RANGE")
    print("   " + text.splitlines()[0][:100])
    print(f"   {text.splitlines()[-1][:100] if len(text.splitlines())>1 else ''}")
    n = save(imgs, "range_before.png")
    check("截图拿到靶场", not err and n > 0, f"{n} 字节")

    print()
    print("=" * 74)
    print("③ 逐个点击（部分故意加偏移，验证判定分得清）")
    random.seed(7)
    plan = []                     # (圆心, 实际点击点, 备注)
    for idx, c in enumerate(info["circles"]):
        if idx % 2 == 0:
            plan.append((c, (c["x"], c["y"]), "正中圆心"))
        else:
            dx = random.choice([-1, 1]) * random.randint(10, 22)
            dy = random.choice([-1, 1]) * random.randint(10, 22)
            plan.append((c, (c["x"] + dx, c["y"] + dy), f"偏移 ({dx:+d},{dy:+d})"))

    results = []
    for c, (tx, ty), note in plan:
        before = len(shots())
        tool("desktop_click", x=tx, y=ty, screenshot=False)
        time.sleep(0.5)
        got = [s for s in shots()[before:] if "shot" in s]
        rec = got[-1] if got else None
        results.append((c, tx, ty, note, rec))
        if rec:
            print(f"   #{c['i']} 目标({c['x']},{c['y']}) 点击({tx},{ty}) "
                  f"{note:14} → 窗口收到({rec['screen_x']},{rec['screen_y']}) "
                  f"距圆心 {rec['distance']:5.1f}px  {'✓命中' if rec['hit'] else '✗未中'}")
        else:
            print(f"   #{c['i']} 点击({tx},{ty}) → 靶场没记录到！（说明点击没送达）")

    print()
    print("=" * 74)
    print("④ 判定核对")
    print("   期望：正中圆心的 3 次全中；偏移 >34px 的必不中，偏移 <34px 的视距离而定")
    exact = [r for r in results if r[3] == "正中圆心"]
    offs = [r for r in results if r[3] != "正中圆心"]
    check("正中圆心的都命中",
          all(r[4] and r[4]["hit"] for r in exact),
          str([(r[0]["i"], r[4]["distance"] if r[4] else None) for r in exact]))
    check("窗口收到的坐标与发出的坐标一致（偏差 ≤2px）",
          all(r[4] and abs(r[4]["screen_x"] - r[1]) <= 2 and abs(r[4]["screen_y"] - r[2]) <= 2
              for r in results if r[4]),
          str([(r[0]["i"], (r[4]["screen_x"] - r[1], r[4]["screen_y"] - r[2]) if r[4] else None)
               for r in results]))
    for r in offs:
        if r[4]:
            expect_hit = r[4]["distance"] <= 34
            check(f"偏移点击 #{r[0]['i']} 判定正确（距心 {r[4]['distance']:.0f}px → "
                  f"{'命中' if r[4]['hit'] else '未中'}）",
                  r[4]["hit"] == expect_hit)

    print()
    print("=" * 74)
    print("⑤ 再截一张，看靶场自己的记分与变色")
    time.sleep(0.4)
    text, err, imgs = tool("desktop_screenshot", window="CLICK-RANGE")
    n = save(imgs, "range_after.png")
    check("拿到最终截图", not err and n > 0, f"{n} 字节")

    ready = [s for s in shots() if s.get("event") == "ready"]
    clickeds = [s for s in shots() if "shot" in s]
    hits = [s for s in clickeds if s["hit"]]
    print(f"   靶场记录：点击 {len(clickeds)} 次，命中 {len(hits)} 次")

finally:
    srv.stdin.close()
    try:
        srv.wait(timeout=5)
    except subprocess.TimeoutExpired:
        srv.kill()
    range_proc.terminate()
    try:
        range_proc.wait(timeout=5)
    except Exception:
        range_proc.kill()

print()
print("=" * 74)
print(f"结果：{ok} 项通过，{fail} 项失败")
print(f"截图：range_before.png（点之前）／range_after.png（点之后）")
