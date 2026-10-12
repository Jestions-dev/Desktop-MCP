# -*- coding: utf-8 -*-
"""
真人鼠标轨迹：读取与回放

为什么要它：`desktop_click` 是"起点 → 终点"一步到位，任何行为分析一眼就看得出
不是人手。人手移动有三个特征一条直线给不出来：
  · 轻微过冲后回调（overshoot → correct）
  · 速度剖面不对称（起步快、末端减速）
  · 微小抖动与不精确的落点

轨迹由**独立工具** `tools/record_trajectory.py` 采集（真人在那个窗口里按住鼠标
往按钮上拖，整段路径连同时间戳被记下来），生成 JSON 放进 `trajectories/`。
**本模块不含录制功能** —— 它只负责读和放，保持 MCP 服务器纯净。
"""
from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

# 轨迹存哪：工具自己的目录（运行时数据，工具必须找得到）。
# 可用环境变量 DESKTOP_MCP_TRAJECTORIES 指到别处。
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "trajectories"
ENV_DIR = "DESKTOP_MCP_TRAJECTORIES"

# 一条轨迹至少要有这么多点才认为可用（录制端也按这个卡）
MIN_POINTS = 12


def traj_dir() -> Path:
    d = os.environ.get(ENV_DIR)
    p = Path(d) if d else DEFAULT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_files() -> list[Path]:
    return sorted(traj_dir().glob("traj_*.json"))


def count() -> int:
    return len(list_files())


def load_all(exclude_bad: bool = True) -> list[dict]:
    """把所有轨迹读进来；坏文件跳过而不是让整个工具失败"""
    out = []
    for f in list_files():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        pts = d.get("points") or []
        if exclude_bad and len(pts) < MIN_POINTS:
            continue
        d["_file"] = f.name
        out.append(d)
    return out


def stats() -> str:
    """给工具返回值用的一句话摘要"""
    fs = list_files()
    if not fs:
        return (f"没有轨迹（目录 {traj_dir()}）—— "
                f"用 tools/record_trajectory.py 录几条")
    n = len(load_all())
    bad = len(fs) - n
    s = f"{n} 条可用轨迹（{traj_dir()}）"
    if bad:
        s += f"，另有 {bad} 个文件点数不足被忽略"
    return s


# ---------------------------------------------------------------- 回放
def plan_path(traj: dict, start_xy: tuple[int, int], end_xy: tuple[int, int],
              jitter_px: float = 2.0, seed=None,
              scale_time: bool = True) -> list[tuple[int, int, int]]:
    """
    把录下来的轨迹**套到新的起终点之间**。

    录的点是"相对松手处"的偏移。回放时三步变换：
      · 缩放：把录制时的直线距离缩放到这次的实际距离 —— 曲线形状（弯度、
        过冲、减速段）按比例保留，这是"像人"的关键
      · 旋转：录的方向和这次的方向通常不同，整条轨迹绕终点转过去
      · 抖动：每个点加一点点随机偏移，免得两次回放一模一样

    scale_time：**时间轴是否跟着路径一起缩放**（默认开）。

    ⚠ 为什么必须缩放时间（这是量出来的，不是猜的）：28 条真人轨迹里
      「时长 vs 直线距离」相关只有 r=+0.38，但
      「时长 vs **路径长度**」相关是 **r=+0.86**，且按距离分组后
      **平均速度基本恒定**（981 / 1006 / 916 px/s）。
      也就是说：**人手的速度大致是个常数，时长 = 路程 ÷ 速度。**
      不缩放的话，把一条 559px 的轨迹拉去走 2084px，时长仍是原值 ——
      速度降到 1/3.7；拿去走 100px 时更荒谬（3.2 秒挪 100 像素）。

    返回 [(screen_x, screen_y, t_ms), ...]，首点= start_xy，末点= end_xy。
    """
    rng = random.Random(seed)
    pts = traj.get("points") or []
    if len(pts) < 2:
        raise ValueError("轨迹点数不足")

    sx, sy = float(start_xy[0]), float(start_xy[1])
    ex, ey = float(end_xy[0]), float(end_xy[1])

    tx, ty = ex - sx, ey - sy
    target_dist = math.hypot(tx, ty)
    target_ang = math.atan2(ty, tx)

    # 录制时起点相对终点的向量：它指出"起点在终点的哪个方向"
    rx, ry = float(pts[0][0]), float(pts[0][1])
    rec_dist = math.hypot(rx, ry)
    if rec_dist < 1e-6:
        raise ValueError("轨迹的起点与终点重合，没法缩放（重录一条路长一点的）")
    rec_ang = math.atan2(ry, rx)

    scale = target_dist / rec_dist
    rot = target_ang - rec_ang
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    # 时间按**路径**缩放比走（不是直线比）—— 人的速度相对路程恒定
    t_scale = scale if (scale_time and scale > 1e-6) else 1.0

    out: list[tuple[float, float, float]] = []
    for (ox, oy, t) in pts:
        zx, zy = ox * scale, oy * scale
        wx = ex + (zx * cos_r - zy * sin_r)
        wy = ey + (zx * sin_r + zy * cos_r)
        if jitter_px > 0:
            wx += rng.uniform(-jitter_px, jitter_px)
            wy += rng.uniform(-jitter_px, jitter_px)
        out.append((wx, wy, float(t) * t_scale))

    # 残差修正：缩放旋转后首末点会有零点几像素的误差，按比例分摊掉，
    # 保证起点正好是 start_xy、终点正好落在 end_xy（否则点不准）
    n = len(out)
    dx0, dy0 = sx - out[0][0], sy - out[0][1]
    dx1, dy1 = ex - out[-1][0], ey - out[-1][1]
    fixed = []
    for i, (x, y, t) in enumerate(out):
        u = i / (n - 1) if n > 1 else 0.0
        fixed.append((int(round(x + dx0 * (1 - u) + dx1 * u)),
                      int(round(y + dy0 * (1 - u) + dy1 * u)),
                      int(round(t))))
    fixed[-1] = (int(round(ex)), int(round(ey)), fixed[-1][2])
    return fixed


def replay(move_fn, click_fn, path: list[tuple[int, int, int]],
           speed: float = 1.0, sleep=None, time_jitter: float = 0.15,
           seed=None) -> dict:
    """
    按轨迹的时间戳依次移动光标，最后点击。

    move_fn(x, y)  把光标移到绝对坐标
    click_fn()     在当前位置点击
    speed          整体节奏倍率：1.0 = 原速（真人的速度），2.0 = 慢一倍
    time_jitter    每段间隔的随机扰动比例（默认 ±15%）

    ⚠ 为什么需要 time_jitter：**时间也是行为特征**。
    严格照原时间戳的话，同一个目标点两次，节奏会一模一样 —— 路径有抖动、
    时间没有，一样可疑。加上小幅扰动后，每次的速度剖面都略有不同，
    但整体形状（起步、峰值、减速尾）仍然是人手那条。
    """
    import random
    import time as _time
    if sleep is None:
        sleep = _time.sleep
    rng = random.Random(seed)

    t_prev = path[0][2]
    for (x, y, t) in path:
        dt = (t - t_prev) / 1000.0 / max(speed, 1e-6)
        if dt > 0:
            if time_jitter > 0:
                dt *= 1.0 + rng.uniform(-time_jitter, time_jitter)
            sleep(max(0.0, dt))
        move_fn(x, y)
        t_prev = t
    sleep(0.02)
    click_fn()
    total = (path[-1][2] - path[0][2]) / max(speed, 1e-6)
    return {"moves": len(path), "duration_ms": int(total),
            "time_jitter": time_jitter}
