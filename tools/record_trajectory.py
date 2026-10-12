# -*- coding: utf-8 -*-
"""
鼠标轨迹录制器（独立工具，**不属于 MCP**）

MCP 服务器只负责"用轨迹点击"，不含录制 —— 录制是要人参与的、一次性的活，
放在这里手动跑就行。

用法：
    python tools/record_trajectory.py              # 存到 ~/.dsh/desktop-mcp/trajectories/
    python tools/record_trajectory.py --out D:\\ForDeepseek\\DesktopMCP\\trajectories

窗口里：**按住鼠标 → 朝按钮移动 → 松开**，就录下一条。
多录几条 —— 每条手的走法都不一样，回放时才有变化。

录出来的 JSON 长这样（点坐标是**相对松手处**的偏移，回放时按目标距离缩放）：
    {"points": [[-580,-310,0], [-541,-289,16], ...],
     "n": 34, "duration_ms": 412, "straight_dist": 655.2,
     "end_screen_xy": [1200, 800], "recorded_at": "2026-10-12 16:30:00"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "trajectories"
ENV_DIR = "DESKTOP_MCP_TRAJECTORIES"

# 采样阈值：位移太小且间隔太短的移动点不记（避免记一堆原地抖动）
MIN_STEP_PX = 2
MIN_STEP_MS = 8
# 一条轨迹至少这么多点才算有效（防止手滑一下就存下垃圾）
MIN_POINTS = 12
# 前后各丢几个点：按下瞬间和松开瞬间容易有杂点
TRIM = 2

# DPI 感知设置的结果（"per-monitor-v2" 才对；其它值会导致窗口被缩放）
_DPI_LEVEL = "未设置"

# 角落 → 中文说明（写进窗口标题，提醒这次录的是哪个方向）
_CORNER_LABEL = {
    "left-bottom": "朝左下",
    "right-top": "朝右上",
    "left-top": "朝左上",
    "right-bottom": "朝右下",
}

BG = "#1e1e24"
FG = "#e8e8ef"
DIM = "#9a9aa8"
ACCENT = "#5afaff"
OK = "#7ee787"
BAD = "#ff7b72"


def resolve_dir(cli: str | None) -> Path:
    if cli:
        p = Path(cli)
    elif os.environ.get(ENV_DIR):
        p = Path(os.environ[ENV_DIR])
    else:
        p = DEFAULT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_dpi_aware() -> None:
    """
    必须在建任何窗口之前调用 —— 否则 Tk 报的是**逻辑像素**（150% 缩放下
    2560×1600 会读成 1707×1067），于是"居中"算出来的位置是错的，
    而且窗口尺寸也会被系统缩放（要 720×470 得到 736×509）。

    这和 desktop_click 点偏 1.5 倍是同一个根因，栽过一次了。
    """
    result = "?"
    try:
        import ctypes
        from ctypes import wintypes
        # 用显式 argtypes/restype 的调用方式 —— 之前用 windll 的隐式方式
        # 虽然返回 1（成功），但窗口仍被系统按 2/3 缩放（位置和尺寸同一个系数），
        # 说明实际没生效。显式声明类型能避免 CTypes 把 HANDLE 参数截断。
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        u32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if u32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4)):
            result = "per-monitor-v2"
        else:
            sh = ctypes.WinDLL("shcore", use_last_error=True)
            if sh.SetProcessDpiAwareness(2) == 0:
                result = "per-monitor"
            else:
                u32.SetProcessDPIAware()
                result = "system"
    except Exception as e:
        result = f"失败({type(e).__name__}: {e})"
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="鼠标轨迹录制器（人手动录）")
    ap.add_argument("--out", help=f"轨迹输出目录，默认 {DEFAULT_DIR}")
    ap.add_argument("--corner", default="left-bottom",
                    choices=["left-bottom", "right-top", "left-top", "right-bottom"],
                    help="按钮放哪个角 —— 决定你朝哪个方向扫（默认 left-bottom）")
    args = ap.parse_args(argv)
    out_dir = resolve_dir(args.out)

    # ⚠ 只调一次！这个 API 在进程生命周期内**只能成功一次**，第二次会因为
    # "已经设过"而失败，然后降级链会把结果误报成 "system"（我就这么被自己的
    # 诊断骗了一轮）。所以把结果存进模块变量，别重复调用。
    global _DPI_LEVEL
    _DPI_LEVEL = make_dpi_aware()
    import tkinter as tk

    root = tk.Tk()
    root.title(f"desktop-mcp 轨迹录制器（{_CORNER_LABEL.get(args.corner, args.corner)}）")
    root.configure(bg=BG)
    root.resizable(False, False)
    # ⚠ 不要强制 tk scaling！
    # 曾经设成 1.0 想让"1 单位 = 1 像素"，结果把 Tk 的 DPI 模型钉死在 72 DPI，
    # 于是 geometry 的尺寸被系统按 2 倍关系缩放：要 720x470 实际给 495x351，
    # 而且 winfo_fpixels('1i') 报 72（正常应是 144）。让 Tk 自己按屏幕 DPI 算。
    #
    # 录制本身不受影响：鼠标坐标来自 event.x_root（屏幕物理像素），
    # 与 canvas 的坐标系无关。窗口大小只影响"好不好按"。

    W, H = 720, 470
    canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # ⚠ 顺序很重要：**先 pack，再 geometry**。
    # 反过来会被 pack 的尺寸协商盖掉 —— 实测 geometry("720x470+920+565") 之后
    # Tk 自报的仍是 "200x200+920+565"（位置生效、尺寸丢了），窗口小得可笑。
    # 而且必须 update() 一次让请求真正落到窗口上，否则读到的还是旧值。
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = max(0, (sw - W) // 2)
    y = max(0, (sh - H) // 2)
    root.geometry(f"{W}x{H}+{x}+{y}")
    root.update_idletasks()
    root.update()

    # ⚠ 界面按**实际拿到的尺寸**等比缩排放，不按请求的尺寸。
    #
    # 这台机器上系统只给 495x351（我请求 720x470）—— 位置和尺寸被同一个系数
    # 缩放，典型的"进程被当成不感知 DPI"。试过显式 argtypes、试过不强制
    # tk scaling，都没改观。
    #
    # 但**录制数据本身是准的**：鼠标坐标来自 event.x_root（屏幕物理像素），
    # 与 canvas 坐标系无关，已用 Win32 GetCursorPos 交叉校验 ≤1px。
    # 所以不跟 DPI 较劲了 —— 改成一个缩放系数 S，所有界面坐标乘它。
    # 这样系统给多大窗口，界面都刚好铺满、按钮都在看得见的位置。
    root.update_idletasks()
    root.update()

    def _client_size() -> tuple[int, int]:
        """从 Win32 拿窗口客户区的**实际像素**尺寸"""
        try:
            import ctypes

            class _R(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]

            r = _R()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r))
            return (r.r - r.l, r.b - r.t)
        except Exception:
            return (0, 0)

    real_w, real_h = _client_size()
    tk_w = max(1, root.winfo_width())
    # 客户区像素 / canvas 单位 = 缩放系数（取小的那个方向，保证内容不出界）
    S = 1.0
    if real_w > 0 and real_h > 0:
        S = min(real_w / tk_w, real_h / max(1, root.winfo_height()), 1.0)
    # 界面实际可用的 canvas 单位
    CW = max(320, int(tk_w * S)) if S < 1 else tk_w
    CH = max(240, int(root.winfo_height() * S)) if S < 1 else root.winfo_height()

    # 诊断（排查"窗口尺寸和请求不一致"用）：写进文件，不打断界面
    # 位置偏了或尺寸不对时看这个文件，就知道是 Tk 没设对还是被系统缩放了。
    def _dump_geom(tag: str) -> None:
        try:
            import json
            info = {
                "tag": tag,
                "dpi_level": _DPI_LEVEL,
                "screen": [root.winfo_screenwidth(), root.winfo_screenheight()],
                "requested": [W, H, x, y],
                "winfo": [root.winfo_width(), root.winfo_height(),
                          root.winfo_x(), root.winfo_y()],
                "geometry": root.geometry(),
                "tk_scaling": root.tk.call("tk", "scaling"),
                "px_per_inch": root.winfo_fpixels("1i"),
                "client_pixels": [real_w, real_h],
                "layout_scale": round(S, 4),
                "layout_canvas": [CW, CH],
            }
            (Path(__file__).resolve().parent.parent / ".recorder_geom.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    _dump_geom("after-geometry")

    # 关键自检：Tk 报的屏幕尺寸 vs mss 报的（后者一定是物理像素）。
    # 两者不一致说明本进程的 DPI 感知没生效 —— 那 event.x_root 可能也是缩放过的，
    # 录出来的坐标就不能直接用于回放。写进诊断文件，录第一条时就能看出来。
    try:
        import json
        import mss
        with mss.mss() as _s:
            phys = (_s.monitors[0]["width"], _s.monitors[0]["height"])
        j = json.loads((Path(__file__).resolve().parent.parent
                        / ".recorder_geom.json").read_text(encoding="utf-8"))
        j["mss_physical"] = list(phys)
        j["tk_screen"] = [root.winfo_screenwidth(), root.winfo_screenheight()]
        j["scale_x"] = phys[0] / max(1, root.winfo_screenwidth())
        j["scale_y"] = phys[1] / max(1, root.winfo_screenheight())
        j["coord_ok"] = abs(j["scale_x"] - 1) < 0.01 and abs(j["scale_y"] - 1) < 0.01
        (Path(__file__).resolve().parent.parent
         / ".recorder_geom.json").write_text(json.dumps(j, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    except Exception:
        pass

    # 按钮放哪个角：由 --corner 决定。**录的方向很重要** ——
    # 旋转虽然能保住路径形状，但会丢掉手腕的发力差异（往左下是"拉"，
    # 往右上是"推"，右撇子两种发力不一样）。四个象限各录一组最真实。
    BW, BH = 168, 64
    M = 48                                        # 距边缘的留白
    if args.corner == "left-bottom":
        BX, BY = M, CH - BH - M
    elif args.corner == "right-top":
        BX, BY = CW - BW - M, M
    elif args.corner == "left-top":
        BX, BY = M, M
    else:                                         # right-bottom
        BX, BY = CW - BW - M, CH - BH - M

    st = {"recording": False, "points": [], "t0": 0.0, "last": None, "offset": (0, 0)}

    def count_files() -> int:
        return len(list(out_dir.glob("traj_*.json")))

    def draw_static():
        canvas.delete("all")
        canvas.create_text(28, 26, anchor="nw", fill=FG,
                           font=("Microsoft YaHei UI", 15, "bold"), text="轨迹录制器")
        canvas.create_text(28, 56, anchor="nw", fill=DIM,
                           font=("Microsoft YaHei UI", 10),
                           text="按住鼠标 → 朝按钮移动 → 松开，就录下一条\n"
                                "多录几条：每条手的走法都不一样，回放时才有变化")
        canvas.create_rectangle(BX, BY, BX + BW, BY + BH,
                                outline=ACCENT, width=3, fill="#23232c", tags="btn")
        canvas.create_text(BX + BW / 2, BY + BH / 2, fill=ACCENT, tags="btn",
                           font=("Microsoft YaHei UI", 14, "bold"), text="移到这松手")
        canvas.create_text(BX + BW / 2, BY - 26, fill=FG, tags="count",
                           font=("Microsoft YaHei UI", 11), text=f"已录 {count_files()} 条")
        canvas.create_text(28, CH - 34, anchor="nw", fill=DIM, tags="status",
                           font=("Microsoft YaHei UI", 10), text=f"输出：{out_dir}")

    def status(text, color=DIM):
        canvas.itemconfigure("status", text=text, fill=color)

    def redraw_path():
        canvas.delete("path")
        pts = st["points"]
        if len(pts) < 2:
            return
        ox, oy = st["offset"]
        flat = []
        for (x, y, _t) in pts[-400:]:
            flat += [x - ox, y - oy]
        canvas.create_line(*flat, fill=OK, width=2, tags="path")
        canvas.create_oval(flat[-2] - 3, flat[-1] - 3, flat[-2] + 3, flat[-1] + 3,
                           fill=OK, outline="", tags="path")
        canvas.tag_raise("btn")

    def on_press(e):
        if st["recording"]:
            return
        st.update(recording=True, points=[], t0=time.perf_counter(), last=None,
                  offset=(e.x_root - e.x, e.y_root - e.y))
        status("● 录制中 —— 朝按钮移动，然后松开", ACCENT)

    def on_move(e):
        if not st["recording"]:
            return
        now = (time.perf_counter() - st["t0"]) * 1000.0
        x, y = e.x_root, e.y_root
        last = st["last"]
        if last is not None:
            dx, dy, dt = x - last[0], y - last[1], now - last[2]
            if abs(dx) + abs(dy) < MIN_STEP_PX and dt < MIN_STEP_MS:
                return                                   # 原地抖动，不记
        st["points"].append((x, y, round(now, 1)))
        st["last"] = (x, y, now)
        if len(st["points"]) % 3 == 0:
            redraw_path()

    def on_release(e):
        if not st["recording"]:
            return
        st["recording"] = False
        pts = st["points"]
        redraw_path()
        need = MIN_POINTS + TRIM * 2
        if len(pts) < need:
            status(f"✗ 太短了（{len(pts)} 个点，至少要 {need}）—— 再试一次，"
                   f"慢一点、路走长一点", BAD)
            st["points"] = []
            return

        core = pts[TRIM:-TRIM]
        end_x, end_y = core[-1][0], core[-1][1]          # 以松手处为终点
        # 存相对终点的偏移：回放时按目标距离缩放，曲线形状原样保留
        rel = [[x - end_x, y - end_y, int(t)] for (x, y, t) in core]
        dist = (rel[0][0] ** 2 + rel[0][1] ** 2) ** 0.5

        # 交叉验证：Tk 报的松手位置 vs Win32 的光标位置。
        # 两者一致（偏差几像素内）说明 Tk 的 x_root/y_root 就是物理像素，
        # 录出来的轨迹可以直接用于回放。不一致就得换算 —— 别猜，量。
        cursor_check = None
        try:
            import ctypes
            class _PT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = _PT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cursor_check = {"tk_release": [end_x, end_y],
                            "win32_cursor": [pt.x, pt.y],
                            "delta": [pt.x - end_x, pt.y - end_y]}
        except Exception:
            pass

        obj = {
            "points": rel,
            "n": len(rel),
            "duration_ms": int(core[-1][2] - core[0][2]),
            "straight_dist": round(dist, 1),
            "end_screen_xy": [end_x, end_y],
            "cursor_check": cursor_check,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        path = out_dir / f"traj_{int(time.time() * 1000)}.json"
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        n = count_files()
        canvas.itemconfigure("count", text=f"已录 {n} 条")
        canvas.delete("path")
        extra = ""
        if cursor_check:
            dx, dy = cursor_check["delta"]
            extra = ("　坐标校验 ✓" if abs(dx) <= 3 and abs(dy) <= 3
                     else f"　⚠ 坐标偏差 ({dx},{dy})")
        status(f"✓ 已保存第 {n} 条（{obj['n']} 点 / {obj['duration_ms']}ms / "
               f"直线 {obj['straight_dist']:.0f}px）{extra}", OK)
        st["points"] = []

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.destroy())

    draw_static()
    root.mainloop()
    print(f"窗口已关闭。轨迹在 {out_dir}，共 {count_files()} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
