# -*- coding: utf-8 -*-
"""按四个象限给轨迹分类（起点→终点的位移方向）"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = Path(r"D:\ForDeepseek\DesktopMCP\trajectories")


def quadrant(vx: float, vy: float) -> str:
    """屏幕坐标 y 向下：vy>0 表示终点在起点下方"""
    lr = "右" if vx >= 0 else "左"
    ud = "下" if vy >= 0 else "上"
    return f"朝{ud}{lr}"          # 例如 朝下左 = 往左下扫


rows = []
for f in sorted(D.glob("traj_*.json"), key=lambda p: p.stat().st_mtime):
    d = json.loads(f.read_text(encoding="utf-8"))
    p0 = d["points"][0]
    vx, vy = -p0[0], -p0[1]                    # 起点 → 终点
    ang = math.degrees(math.atan2(vy, vx))
    rows.append({
        "file": f.name, "n": d["n"], "dur": d["duration_ms"],
        "dist": d["straight_dist"], "ang": ang, "q": quadrant(vx, vy),
        "v": (round(vx), round(vy)), "mtime": f.stat().st_mtime,
    })

# 分两批：前 12 条是左下窗口录的，后 16 条是右上窗口录的
first12 = {r["file"] for r in rows[:12]}
cnt_all = Counter(r["q"] for r in rows)
cnt_old = Counter(r["q"] for r in rows if r["file"] in first12)
cnt_new = Counter(r["q"] for r in rows if r["file"] not in first12)

print("=" * 78)
print(f"共 {len(rows)} 条轨迹，按起点→终点的**象限**分类：\n")
print(f"  {'象限':<10}{'全部':>6}{'第一批(左下窗口)':>18}{'第二批(右上窗口)':>18}")
print("  " + "-" * 68)
for q in ("朝下左", "朝下右", "朝上左", "朝上右", "朝下", "朝上", "朝左", "朝右"):
    if cnt_all.get(q):
        print(f"  {q:<10}{cnt_all[q]:>6}{cnt_old.get(q, 0):>18}{cnt_new.get(q, 0):>18}")

print()
print("=" * 78)
print("明细（按录制时间）：")
print(f"  {'文件':<26}{'点':>5}{'时长':>7}{'直线':>7}{'角度':>8}  {'象限':<8}{'向量'}")
print("  " + "-" * 76)
for i, r in enumerate(rows):
    mark = "  ← 第一批" if i == 11 else ""
    print(f"  {r['file']:<26}{r['n']:>5}{r['dur']:>7}{r['dist']:>7.0f}"
          f"{r['ang']:>8.0f}°  {r['q']:<8}{r['v']}{mark}")

print()
print("=" * 78)
print("覆盖度判读：")
quads = {q: cnt_all.get(q, 0) for q in ("朝下左", "朝下右", "朝上左", "朝上右")}
for q, c in quads.items():
    bar = "█" * c
    print(f"  {q}  {c:>2} 条  {bar}")
missing = [q for q, c in quads.items() if c == 0]
print()
if not missing:
    print("  ✓ 四个象限**都有真实样本** —— 不用再靠旋转硬凑了")
else:
    print(f"  ⚠ 还缺：{missing}")
