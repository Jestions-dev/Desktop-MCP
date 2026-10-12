# -*- coding: utf-8 -*-
"""
对比"拉"（朝左下）和"推"（朝右上）两种发力的手部特征。

如果两者统计上明显不同，就证明"旋转不能完全替代真录" —— 这正是要四象限
各录一组的原因。
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


def profile(d):
    pts = d["points"]
    t0 = pts[0][2]
    sp = []
    for i in range(1, len(pts)):
        dt = (pts[i][2] - pts[i - 1][2]) / 1000.0
        if dt <= 0:
            continue
        dist = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        sp.append((pts[i][2] - t0, dist / dt))
    if len(sp) < 8:
        return None
    speeds = [v for _, v in sp]
    n = len(speeds)
    seg = max(1, n // 5)
    fives = [sum(speeds[i * seg:(i + 1) * seg]) / max(1, len(speeds[i * seg:(i + 1) * seg]))
             for i in range(5) if speeds[i * seg:(i + 1) * seg]]
    peak = max(speeds)
    tail = sum(speeds[-seg:]) / max(1, len(speeds[-seg:]))
    return {
        "avg": sum(speeds) / n, "peak": peak,
        "tail": tail, "tail_ratio": tail / peak if peak else 0,
        "fives": fives, "n": n,
    }


groups = {"拉（朝左下）": [], "推（朝右上）": [], "其它方向": []}
for f in sorted(D.glob("traj_*.json"), key=lambda p: p.stat().st_mtime):
    d = json.loads(f.read_text(encoding="utf-8"))
    p0 = d["points"][0]
    vx, vy = -p0[0], -p0[1]
    pr = profile(d)
    if not pr:
        continue
    if vx < 0 and vy > 0 and abs(vx) > 100:
        groups["拉（朝左下）"].append((f.name, d, pr))
    elif vx > 0 and vy < 0 and abs(vx) > 100:
        groups["推（朝右上）"].append((f.name, d, pr))
    else:
        groups["其它方向"].append((f.name, d, pr))


def stat(group, key):
    vals = [g[2][key] for g in group]
    return sum(vals) / len(vals) if vals else 0


print("=" * 80)
print(f"{'指标':<24}{'拉（朝左下）':>16}{'推（朝右上）':>16}{'差异':>12}")
print("-" * 80)
for label, key, unit in [
    ("样本数", None, "条"),
    ("平均采样点数", "n", "点"),
    ("平均时长", None, "ms"),
    ("平均直线距离", None, "px"),
    ("平均速度", "avg", "px/s"),
    ("平均峰值速度", "peak", "px/s"),
    ("收尾/峰值比", "tail_ratio", ""),
]:
    if key is None:
        if label == "样本数":
            a, b = len(groups["拉（朝左下）"]), len(groups["推（朝右上）"])
        elif label == "平均时长":
            a = stat(groups["拉（朝左下）"], "n") and \
                sum(g[1]["duration_ms"] for g in groups["拉（朝左下）"]) / len(groups["拉（朝左下）"])
            b = sum(g[1]["duration_ms"] for g in groups["推（朝右上）"]) / len(groups["推（朝右上）"])
        else:
            a = sum(g[1]["straight_dist"] for g in groups["拉（朝左下）"]) / len(groups["拉（朝左下）"])
            b = sum(g[1]["straight_dist"] for g in groups["推（朝右上）"]) / len(groups["推（朝右上）"])
    else:
        a, b = stat(groups["拉（朝左下）"], key), stat(groups["推（朝右上）"], key)
    ratio = (b / a) if a else 0
    print(f"{label:<24}{a:>16.1f}{b:>16.1f}{ratio:>11.2f}×")

print()
print("=" * 80)
print("五段速度剖面对比（各段平均速度，看形状差异）")
for name in ("拉（朝左下）", "推（朝右上）"):
    g = groups[name]
    if not g:
        continue
    fives = [0.0] * 5
    for _, _, pr in g:
        for i, v in enumerate(pr["fives"][:5]):
            fives[i] += v / len(g)
    mx = max(fives) or 1
    print(f"\n  {name}（{len(g)} 条）")
    for i, v in enumerate(fives):
        lbl = ["起步", "加速", "最快", "减速", "收尾"][i]
        print(f"    {lbl} {v:>7.0f} px/s  {'█' * max(1, int(v / mx * 44))}")

print()
print("=" * 80)
print("判读：")
la, pu = groups["拉（朝左下）"], groups["推（朝右上）"]
if la and pu:
    d_ratio = (sum(g[1]["duration_ms"] for g in pu) / len(pu)) / \
              (sum(g[1]["duration_ms"] for g in la) / len(la))
    p_ratio = stat(pu, "peak") / stat(la, "peak")
    print(f"  · 推的平均时长是拉的 {d_ratio:.2f} 倍")
    print(f"  · 推的平均峰值速度是拉的 {p_ratio:.2f} 倍")
    if abs(d_ratio - 1) > 0.15 or abs(p_ratio - 1) > 0.15:
        print("  → 两种发力**统计上确实不同** —— 旋转替代不了真录，四象限各录是必要的")
    else:
        print("  → 两者接近，旋转也许够用（但样本还少，别急着下结论）")
