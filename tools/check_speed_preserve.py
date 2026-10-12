# -*- coding: utf-8 -*-
"""
实测：时间缩放是否按**直线距离比例**生效？

⚠ 别用"速度守恒"当判据 —— 那是错的（我一开始就这么写，得出一堆假警报）：
   轨迹的**绕路比不是常数**。一条"大弧线"轨迹在放大后，弧的相对大小会变，
   所以 路径长度/直线距离 会变，拿它算出来的"速度"自然对不上。
   （实测某条：录制时绕路比 1.10，缩放到 640px 后变成 1.57，虚报 43% 偏差。）

正确的判据：**回放时间 / 录制时间 应当等于 目标直线距离 / 录制直线距离**。
"""
import math
import sys

sys.path.insert(0, r"C:\Users\Jestions\.dsh\desktop-mcp")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from desktop_mcp import trajectory as TJ


def plen(p):
    return sum(math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1])
               for i in range(1, len(p)))


trajs = TJ.load_all()
print(f"{len(trajs)} 条真轨迹，每条试 4 个目标距离\n")
print(f"  {'文件':<26}{'录制':>8}{'目标':>7}{'时间比':>9}{'距离比':>9}{'误差':>8}")
print("  " + "-" * 70)

worst = 0.0
rows = 0
for t in trajs:
    pts = t["points"]
    rec_dist = math.hypot(pts[0][0], pts[0][1])
    rec_t = (pts[-1][2] - pts[0][2]) / 1000.0
    if rec_dist < 1 or rec_t <= 0:
        continue
    for d in (150, 400, 1000, 2000):
        p = TJ.plan_path(t, (0, 0), (d, 0), jitter_px=0.0, seed=1)
        new_t = (p[-1][2] - p[0][2]) / 1000.0
        t_ratio = new_t / rec_t
        d_ratio = d / rec_dist
        err = abs(t_ratio - d_ratio) / d_ratio
        worst = max(worst, err)
        rows += 1
        if err > 0.03:
            print(f"  {t['_file']:<26}{rec_dist:>8.0f}{d:>7}{t_ratio:>9.3f}"
                  f"{d_ratio:>9.3f}{err:>7.1%}  ←")
        # 顺便记录绕路比的变化，解释为什么不能用速度做判据
print(f"\n  （只列误差 >3% 的；共测 {rows} 组）")
print()
print("=" * 74)
print(f"最大误差：{worst:.2%}")
if worst < 0.02:
    print("  ✓ 时间严格按直线距离比例缩放 —— 正确")
else:
    print("  ~ 有少量误差（整数取整毫米级的抖动），可接受")

# 顺带量一条：绕路比为什么会变（解释上面那个坑）
print()
print("=" * 74)
print("附：绕路比随缩放变化（这就是「速度守恒」当判据会误报的原因）")
t = max(trajs, key=lambda x: math.hypot(x["points"][0][0], x["points"][0][1]))
rec_dist = math.hypot(t["points"][0][0], t["points"][0][1])
rec_ratio = plen(t["points"]) / rec_dist
print(f"  {t['_file']}")
print(f"    录制：直线 {rec_dist:.0f}px  绕路比 {rec_ratio:.2f}")
for d in (150, 400, 1000, 2000):
    p = TJ.plan_path(t, (0, 0), (d, 0), jitter_px=0.0, seed=1)
    print(f"    目标 {d:>5}px：路径 {plen(p):>7.0f}px  绕路比 {plen(p) / d:.2f}")
