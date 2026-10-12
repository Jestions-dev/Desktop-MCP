# -*- coding: utf-8 -*-
"""
验证轨迹回放的数学：缩放 / 旋转 / 首末点精确 / 曲线形状保留

你还没录真轨迹，所以先用一条**合成的**（带明显弧度的人造曲线）来测算法。
测的是几何正确性，不是"像不像人" —— 后者得看你录的。
"""
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, r"C:\Users\Jestions\.dsh\desktop-mcp")
from desktop_mcp import trajectory as TJ

_FAILED = False        # 任一检查失败就置 True（末尾据此设退出码）

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
        print(f"   ✗ {label}   {detail}")


def make_curve(n=40, dist=600.0, curve=0.28, overshoot=0.06):
    """合成一条"像人"的轨迹：从 (-dist, 300) 弯到 (0,0)，末端带过冲"""
    pts = []
    for i in range(n):
        u = i / (n - 1)
        # 起点在左下，终点在原点；横向走 dist
        x = -dist * (1 - u)
        y = 300.0 * (1 - u)
        # 加弧度：垂直方向鼓出来一块（sin 在中段最大）
        y += dist * curve * math.sin(math.pi * u)
        # 末端过冲：最后 15% 冲过头一点再回来
        if u > 0.85:
            k = (u - 0.85) / 0.15
            x -= dist * overshoot * math.sin(math.pi * k)
        pts.append([round(x, 1), round(y, 1), int(u * 500)])
    return {"points": pts, "n": n, "duration_ms": 500,
            "straight_dist": round(math.hypot(pts[0][0], pts[0][1]), 1),
            "_file": "synthetic.json", "recorded_at": "合成"}


traj = make_curve()
print("=" * 72)
print(f"合成轨迹：{traj['n']} 点，起点偏移 {traj['points'][0][:2]}，"
      f"直线距离 {traj['straight_dist']}px，时长 {traj['duration_ms']}ms")

print()
print("① 套到不同的起终点：首末点必须精确")
cases = [
    ((100, 100), (1300, 900), "长距离、朝右下"),
    ((1300, 900), (100, 100), "反过来、朝左上"),
    ((1280, 800), (1300, 820), "很短的距离"),
    ((200, 1200), (2400, 300), "很长且陡"),
]
paths = {}
for (s, e, desc) in cases:
    p = TJ.plan_path(traj, s, e, jitter_px=0.0, seed=1)
    paths[desc] = p
    d = math.hypot(e[0] - s[0], e[1] - s[1])
    check(f"{desc}：首点=起点", p[0][:2] == s, f"{p[0][:2]} vs {s}")
    check(f"{desc}：末点=终点", p[-1][:2] == e, f"{p[-1][:2]} vs {e}")
    check(f"{desc}：点数保留（{len(p)}）", len(p) == traj["n"])
    # 路径长度应显著大于直线距离（说明曲线被保留了，不是被拉直）
    plen = sum(math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
               for i in range(len(p) - 1))
    ratio = plen / d if d > 1 else 0
    check(f"{desc}：路径是弯的（曲折比 {ratio:.2f} > 1.02）", ratio > 1.02,
          f"ratio={ratio:.3f}")

print()
print("② 曲线形状应当**与缩放无关**（这是「形状保留」的定义）")
# 同一形状，不同距离，归一化后应当几乎重合
p1 = TJ.plan_path(traj, (0, 0), (500, 0), jitter_px=0.0, seed=1)
p2 = TJ.plan_path(traj, (0, 0), (1500, 0), jitter_px=0.0, seed=1)


def normalized(p, s, e):
    """把路径按 起点→终点 归一化到单位长度，取垂直偏移序列"""
    sx, sy = s
    d = math.hypot(e[0] - sx, e[1] - sy)
    ux, uy = (e[0] - sx) / d, (e[1] - sy) / d
    out = []
    for (x, y, _t) in p:
        rx, ry = x - sx, y - sy
        along = rx * ux + ry * uy
        perp = -rx * uy + ry * ux
        out.append((along / d, perp / d))
    return out


n1, n2 = normalized(p1, (0, 0), (500, 0)), normalized(p2, (0, 0), (1500, 0))
maxdiff = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(n1, n2))
check(f"两种距离下形状一致（最大差 {maxdiff:.4f}）", maxdiff < 0.01, f"{maxdiff:.5f}")

print()
print("③ 旋转正确：无论朝哪个方向，形状相对朝向不变")
dirs = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1)]
shapes = []
for (dx, dy) in dirs:
    p = TJ.plan_path(traj, (1000, 1000), (1000 + dx * 400, 1000 + dy * 400),
                     jitter_px=0.0, seed=1)
    shapes.append(normalized(p, (1000, 1000), (1000 + dx * 400, 1000 + dy * 400)))
worst = 0.0
for s in shapes[1:]:
    worst = max(worst, max(math.hypot(a[0] - b[0], a[1] - b[1])
                           for a, b in zip(shapes[0], s)))
check(f"六个方向形状一致（最大差 {worst:.4f}）", worst < 0.01, f"{worst:.5f}")

print()
print("④ 抖动生效但幅度受控")
a = TJ.plan_path(traj, (0, 0), (600, 400), jitter_px=3.0, seed=7)
b = TJ.plan_path(traj, (0, 0), (600, 400), jitter_px=3.0, seed=8)
diff = max(math.hypot(x1 - x2, y1 - y2) for (x1, y1, _), (x2, y2, _) in zip(a, b))
check(f"不同种子会得到不同路径（最大差 {diff:.1f}px）", diff > 0.5)
check("但两条的末点都精确落在终点", a[-1][:2] == (600, 400) and b[-1][:2] == (600, 400))

print()
print("⑤ 回放：按时间戳走完，最后点击一次")
moves, clicked = [], []
t0 = [None]


def fake_sleep(dt):
    pass


def mv(x, y):
    moves.append((x, y))


def ck():
    clicked.append(len(moves))


info = TJ.replay(mv, ck, p1, speed=1.0, sleep=fake_sleep)
check(f"移动了 {len(moves)} 次（= 轨迹点数 {traj['n']}）", len(moves) == traj["n"])
check("最后落点 = 终点", moves[-1] == (500, 0), str(moves[-1]))
check("点击发生过且只有一次", clicked == [len(moves)], str(clicked))

# ⚠ 这里不要断言"时长不变" —— 时间轴会跟着路径一起缩放（见 plan_path 的
# scale_time 说明）。要断言的是**速度保持**，那才是人手的不变量：
# 28 条实测「时长 vs 路程」r=+0.86，按距离分组平均速度基本恒定（981/1006/916）。
# 录制时：路径 670.8px / 500ms。缩放后速度应当还是 ~1342 px/s。
# ⚠ 这里**不要**用"速度守恒"当判据 —— 那是错的，我一开始就这么写，跑出一堆
# 假警报（最大虚报 43%）。原因：轨迹的**绕路比不是常数**，一条弧线轨迹放大后
# 弧的相对大小会变，所以 路径长度/直线距离 会变，拿它算的"速度"自然对不上。
#   （实测某条：录制时绕路比 1.10，缩放到 640px 后成了 1.57。）
#
# 正确的判据：**回放时间 / 录制时间 应当等于 目标直线距离 / 录制直线距离**。
# 完整的 112 组测试见 tools/check_speed_preserve.py（最大误差 1.02%）。
_rec_dist = math.hypot(traj["points"][0][0], traj["points"][0][1])
_rec_t = (traj["points"][-1][2] - traj["points"][0][2]) / 1000.0
_rep_dist = 500.0                                     # p1 的目标距离
_rep_t = (p1[-1][2] - p1[0][2]) / 1000.0
_want = _rep_dist / _rec_dist
check(f"时间按距离比例缩放（{_rep_t / _rec_t:.3f} × vs 期望 {_want:.3f} ×）",
      abs(_rep_t / _rec_t - _want) / _want < 0.03)

# 再验一条：时间轴必须随距离缩放（否则短距离会慢得不像人）
short = TJ.plan_path(traj, (0, 0), (100, 0), jitter_px=0.0, seed=1)
long_ = TJ.plan_path(traj, (0, 0), (2000, 0), jitter_px=0.0, seed=1)
t_short = short[-1][2]
t_long = long_[-1][2]
check(f"时间随距离缩放（100px→{t_short}ms，2000px→{t_long}ms）",
      t_long > t_short * 5, f"{t_short} vs {t_long}")

print()
print("⑥ 异常输入要有清楚的报错（而不是崩）")
bad = {"points": [[0, 0, 0], [0, 0, 10]]}
try:
    TJ.plan_path(bad, (0, 0), (100, 100))
    check("起点=终点 应报错", False, "没报错")
except ValueError as e:
    check(f"起点=终点 → {str(e)[:40]}", "重合" in str(e))
try:
    TJ.plan_path({"points": [[0, 0, 0]]}, (0, 0), (100, 100))
    check("点数不足 应报错", False, "没报错")
except ValueError as e:
    check(f"点数不足 → {str(e)[:40]}", "不足" in str(e))

print()
print("=" * 72)
print(f"结果：{ok} 项通过，{fail} 项失败")


sys.exit(1 if _FAILED else 0)
