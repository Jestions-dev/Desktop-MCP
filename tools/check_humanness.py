# -*- coding: utf-8 -*-
"""
看录到的轨迹有没有"人味" —— 重点看**速度剖面**，不只是路径形状。

机器检测不只看你走到哪，还看**你怎么走**：人手的特征是起步加速、中段快、
末端明显减速（对数的减速尾），而且速度不是恒定的。两点一线或者匀速移动
一眼就能被分出来。这里把每条轨迹的速度曲线画成文本，让人直接看。
"""
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = Path(r"D:\ForDeepseek\DesktopMCP\trajectories")
files = sorted(D.glob("traj_*.json"))
print("=" * 78)
print(f"共 {len(files)} 条轨迹\n")

rows = []
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    pts = d["points"]
    # 绝对时间戳，转成"从第一个点起"的相对时间
    t0 = pts[0][2]
    samples = []
    for i in range(1, len(pts)):
        x0, y0, ta = pts[i - 1]
        x1, y1, tb = pts[i]
        dt = (tb - ta) / 1000.0
        if dt <= 0:
            continue
        dist = math.hypot(x1 - x0, y1 - y0)
        samples.append((tb - t0, dist / dt))          # (相对ms, 瞬时速度 px/s)
    if len(samples) < 5:
        continue
    speeds = [s for _, s in samples]
    n = len(speeds)
    # 分成五段看趋势（起步 / 中段 / 末端）
    seg = max(1, n // 5)
    profile = [sum(speeds[i * seg:(i + 1) * seg]) / len(speeds[i * seg:(i + 1) * seg])
               for i in range(5) if speeds[i * seg:(i + 1) * seg]]
    peak = max(speeds)
    tail = sum(speeds[-seg:]) / len(speeds[-seg:])
    rows.append({
        "file": f.name,
        "n": d["n"],
        "dur": d["duration_ms"],
        "dist": d["straight_dist"],
        "avg": sum(speeds) / n,
        "peak": peak,
        "tail_ratio": tail / peak if peak else 0,
        "profile5": profile,
        "ok": d.get("cursor_check", {}).get("delta") if d.get("cursor_check") else None,
    })

print(f"{'文件':<26}{'点':>5}{'时长ms':>8}{'直线px':>8}{'均速':>8}{'峰值':>8}{'尾/峰':>7}")
print("-" * 78)
for r in rows:
    print(f"{r['file']:<26}{r['n']:>5}{r['dur']:>8}{r['dist']:>8.0f}"
          f"{r['avg']:>8.0f}{r['peak']:>8.0f}{r['tail_ratio']:>7.2f}")

print()
print("=" * 78)
print("五段速度剖面（每格 = 那一段的平均速度，用字符长度表示相对快慢）")
print("人味的样子：起步偏慢 → 中段最快 → 末端**明显**掉下来\n")
for r in rows[:6]:
    print(f"  {r['file']}")
    mx = max(r["profile5"]) or 1
    for i, v in enumerate(r["profile5"]):
        bar = "█" * max(1, int(v / mx * 40))
        label = ["起步", "加速", "最快", "减速", "收尾"][i]
        print(f"    {label} {v:>7.0f} px/s  {bar}")
    print()

print("=" * 78)
print("判读：")
if rows:
    tr = [r["tail_ratio"] for r in rows]
    avg_tr = sum(tr) / len(tr)
    accel = sum(1 for r in rows if r["profile5"][0] < max(r["profile5"]))
    decel = sum(1 for r in rows if r["profile5"][-1] < max(r["profile5"]))
    print(f"  · 收尾速度 / 峰值速度 平均 = {avg_tr:.2f}"
          f"  （人通常 0.1~0.4；接近 1.0 说明是匀速 = 像机器）")
    print(f"  · {accel}/{len(rows)} 条有'起步不是最快'的特征")
    print(f"  · {decel}/{len(rows)} 条有'收尾减速'的特征")
    varied = sum(1 for r in rows if r["peak"] / max(1, r["avg"]) > 1.5)
    print(f"  · {varied}/{len(rows)} 条的峰值明显高于均值（速度有起伏，不是恒速）")
    bad = [r["file"] for r in rows if r["ok"] and max(abs(v) for v in r["ok"]) > 3]
    print(f"  · 坐标校验异常的：{bad if bad else '无（全部 ≤3px）'}")
