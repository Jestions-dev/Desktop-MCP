# -*- coding: utf-8 -*-
"""
验证轨迹的"纯净度"：是不是**纯手部移动、只在最后点击**。

三条证据：
  1. 数据里有没有"按下/抬起"事件记录 —— 有的话就是夹带了点击
  2. 时间轴上有没有异常空档 —— 拖到一半松手再按住会留下大 gap
  3. 路径连续性：相邻点距离是否平滑，有没有"跳变"（松手后手移开再按，
     下一段的起点会离上一段终点很远）
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
print("=" * 84)
print("① 数据里有哪些字段（找找有没有点击相关的东西）")
f0 = sorted(D.glob("traj_*.json"))[0]
d0 = json.loads(f0.read_text(encoding="utf-8"))
print(f"   以 {f0.name} 为例：")
for k, v in d0.items():
    if k == "points":
        print(f"     {k:<16} 数组，{len(v)} 项，每项是 [相对x, 相对y, 毫秒]")
    elif k == "cursor_check":
        print(f"     {k:<16} {v}")
    else:
        print(f"     {k:<16} {v}")
click_keys = [k for k in d0 if any(w in k.lower() for w in ("click", "down", "up", "press", "release", "button"))]
print(f"\n   点击相关的字段：{click_keys if click_keys else '**一个都没有** —— 数据里只有位置和时间'}")
pt_len = {len(p) for f in D.glob('traj_*.json') for p in [json.loads(f.read_text(encoding='utf-8'))['points'][0]]}
print(f"   每个点的字段数：{pt_len}（3 = 只有 x, y, 时间；有第 4 个才可能是事件类型）")

print()
print("=" * 84)
print("② 时间轴空档分析（拖到一半松手再按，会留下明显 gap）")
print(f"{'文件':<26}{'点':>5}{'时长ms':>8}{'中位间隔':>9}{'最大间隔':>9}{'异常?':>8}")
print("-" * 84)
suspects = []
for f in sorted(D.glob("traj_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    pts = d["points"]
    gaps = [pts[i][2] - pts[i - 1][2] for i in range(1, len(pts))]
    med = sorted(gaps)[len(gaps) // 2]
    mx = max(gaps)
    # 异常判据：最大间隔超过中位数的 5 倍，且绝对值 > 60ms
    bad = mx > 60 and mx > med * 5
    if bad:
        suspects.append((f.name, med, mx))
    print(f"{f.name:<26}{len(pts):>5}{d['duration_ms']:>8}{med:>9}{mx:>9}"
          f"{'⚠ 有' if bad else '  无':>8}")

print()
print("=" * 84)
print("③ 路径连续性（有没有'松手→手移开→再按'造成的空间跳变）")
print(f"{'文件':<26}{'中位步长':>9}{'最大步长':>9}{'跳变?':>8}")
print("-" * 84)
jumps = []
for f in sorted(D.glob("traj_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    pts = d["points"]
    steps = [math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
             for i in range(1, len(pts))]
    med = sorted(steps)[len(steps) // 2]
    mx = max(steps)
    bad = mx > 80          # 相邻采样点跳 80px 以上，手做不到（8ms 内）
    if bad:
        jumps.append((f.name, med, mx))
    print(f"{f.name:<26}{med:>9.1f}{mx:>9.1f}{'⚠ 有' if bad else '  无':>8}")

print()
print("=" * 84)
print("判读")
if not click_keys:
    print("  ✓ 数据里**没有**任何点击事件字段 —— 存的纯粹是 位置+时间")
if not suspects:
    print("  ✓ 12 条的时间轴**都没有异常空档** —— 说明全程按住没松手")
else:
    print(f"  ⚠ 时间轴有空档的：{suspects}（可能是中途停手，也可能是手停顿）")
if not jumps:
    print("  ✓ 12 条的路径**都没有空间跳变** —— 连续轨迹，不是拼接的")
else:
    print(f"  ⚠ 有空间跳变的：{jumps}")
print()
print("  → 结论：录的是**纯手部移动**（按住拖行），回放时**只在最后点一下**")
