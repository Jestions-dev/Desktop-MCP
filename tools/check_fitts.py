# -*- coding: utf-8 -*-
"""
距离 vs 时长：人有"距离越远花时间越长"的规律吗？（Fitts 定律的味道）

如果 28 条数据里存在明显相关性，说明**回放时应该按时长缩放**；
如果几乎无关，说明时长主要取决于"你怎么动"而不是"动多远"，
照原时长播放就是对的。
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
rows = []
for f in sorted(D.glob("traj_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    pts = d["points"]
    # 真实路径长度（不是直线距离）
    plen = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
               for i in range(1, len(pts)))
    rows.append({
        "f": f.name, "dur": d["duration_ms"], "straight": d["straight_dist"],
        "path": plen, "n": d["n"],
    })

n = len(rows)
print("=" * 76)
print(f"{n} 条轨迹：距离 与 时长 的关系\n")
print(f"  {'文件':<26}{'直线':>7}{'路径':>7}{'时长':>7}{'速度':>9}")
print("  " + "-" * 60)
for r in sorted(rows, key=lambda r: r["straight"]):
    v = r["path"] / (r["dur"] / 1000) if r["dur"] else 0
    print(f"  {r['f']:<26}{r['straight']:>7.0f}{r['path']:>7.0f}{r['dur']:>7}{v:>9.0f}")


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (sx * sy) if sx and sy else 0


durs = [r["dur"] for r in rows]
strs = [r["straight"] for r in rows]
paths = [r["path"] for r in rows]

print()
print("=" * 76)
print("相关系数（1 = 完全正相关，0 = 无关）")
print(f"  时长 vs 直线距离   r = {pearson(strs, durs):+.3f}")
print(f"  时长 vs 路径长度   r = {pearson(paths, durs):+.3f}")
print(f"  直线 vs 路径长度   r = {pearson(strs, paths):+.3f}   ← 路径越绕，越长")

print()
print("=" * 76)
print("按距离分组的平均速度（如果时长随距离等比增长，速度应当恒定）")
rows_sorted = sorted(rows, key=lambda r: r["straight"])
groups = [rows_sorted[i::3] for i in range(3)]
labels = ["近（最短 1/3）", "中", "远（最长 1/3）"]
for lab, g in zip(labels, groups):
    avg_s = sum(r["straight"] for r in g) / len(g)
    avg_d = sum(r["dur"] for r in g) / len(g)
    avg_v = sum(r["path"] / (r["dur"] / 1000) for r in g) / len(g)
    print(f"  {lab:<16} 平均直线 {avg_s:>5.0f}px  平均时长 {avg_d:>6.0f}ms  "
          f"平均速度 {avg_v:>6.0f}px/s")

print()
print("=" * 76)
r_dur = pearson(strs, durs)
if abs(r_dur) > 0.6:
    print(f"  → 时长与距离**强相关**（r={r_dur:+.2f}）")
    print("    回放时应按时长缩放：短距离更快、长距离更慢")
elif abs(r_dur) > 0.3:
    print(f"  → 中等相关（r={r_dur:+.2f}）—— 有一定规律但不强")
    print("    可以加一个温和的时长缩放（开方级别），别太激进")
else:
    print(f"  → 几乎无关（r={r_dur:+.2f}）")
    print("    说明**时长主要取决于你怎么动，而不是动多远** —— 照原时长播放是对的")
