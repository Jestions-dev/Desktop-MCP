# -*- coding: utf-8 -*-
"""
找出"转圈"的那条轨迹：看**转折程度**（相邻线段的方向变化）。

手画圈的特征：方向角持续同向变化（累计转过的总角度很大），
而且路径长度远大于直线距离（绕路）。直线移动的累计转角接近 0。
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
    pts = [(p[0], p[1]) for p in d["points"]]
    if len(pts) < 3:
        continue

    total_turn = 0.0          # 累计转角（绝对值，度）
    signed_turn = 0.0         # 带符号（正=逆时针，负=顺时针）
    path_len = 0.0
    segments = []
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        seg = math.hypot(dx, dy)
        path_len += seg
        if i >= 2:
            pdx = pts[i - 1][0] - pts[i - 2][0]
            pdy = pts[i - 1][1] - pts[i - 2][1]
            if math.hypot(pdx, pdy) > 0.5 and seg > 0.5:
                a1 = math.atan2(pdy, pdx)
                a2 = math.atan2(dy, dx)
                da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
                total_turn += abs(math.degrees(da))
                signed_turn += math.degrees(da)
                segments.append(abs(math.degrees(da)))

    straight = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    rows.append({
        "file": f.name, "n": d["n"], "straight": d["straight_dist"],
        "path": path_len,
        "detour": path_len / straight if straight > 1 else 0,
        "turn": total_turn, "signed": signed_turn,
        "max_seg_turn": max(segments) if segments else 0,
        "revs": abs(signed_turn) / 360.0,
    })

rows.sort(key=lambda r: -r["turn"])
print("=" * 84)
print(f"{'文件':<26}{'点':>5}{'直线':>7}{'路径':>7}{'绕路比':>7}{'累计转角':>9}{'净转':>9}{'圈数':>6}")
print("-" * 84)
for r in rows:
    print(f"{r['file']:<26}{r['n']:>5}{r['straight']:>7.0f}{r['path']:>7.0f}"
          f"{r['detour']:>7.2f}{r['turn']:>9.0f}°{r['signed']:>8.0f}°{r['revs']:>6.2f}")

print()
top = rows[0] if rows else None
if top:
    print("=" * 84)
    print(f"转折最多的：{top['file']}")
    print(f"  累计转角 {top['turn']:.0f}°（净 {top['signed']:.0f}° ≈ {top['revs']:.2f} 圈）")
    print(f"  路径长 {top['path']:.0f}px，直线只有 {top['straight']:.0f}px，绕路比 {top['detour']:.2f}")
    print(f"  单段最大转折 {top['max_seg_turn']:.0f}°")
    d = json.loads((D / top["file"]).read_text(encoding="utf-8"))
    pts = [(p[0], p[1], p[2]) for p in d["points"]]
    print(f"\n  采样密度：{len(pts)} 个点 / {d['duration_ms']}ms "
          f"= 平均每 {d['duration_ms'] / max(1, len(pts) - 1):.1f}ms 一个点")
    gaps = [pts[i][2] - pts[i - 1][2] for i in range(1, len(pts))]
    print(f"  时间间隔：最小 {min(gaps)}ms  最大 {max(gaps)}ms  中位 {sorted(gaps)[len(gaps) // 2]}ms")
    steps = [math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
             for i in range(1, len(pts))]
    print(f"  步长：最小 {min(steps):.1f}px  最大 {max(steps):.1f}px  "
          f"中位 {sorted(steps)[len(steps) // 2]:.1f}px")
    print("\n  前 30 个点（相对坐标，看有没有圆弧感）：")
    line = "    "
    for i, (x, y, t) in enumerate(pts[:30]):
        line += f"({x},{y}) "
        if (i + 1) % 5 == 0:
            print(line)
            line = "    "
    if line.strip():
        print(line)
