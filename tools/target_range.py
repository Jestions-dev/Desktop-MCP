# -*- coding: utf-8 -*-
"""
点击靶场：窗口里画 N 个随机位置的圆，记录点击命中情况

用法：python tools/target_range.py <结果文件.jsonl> [圆的数量]

设计要点（这个测试要能证伪，不能只是"看起来还行"）：
  · 圆的**屏幕坐标**写进 <结果文件>.circles，agent 照着它点
  · 每次点击记录**窗口收到的坐标**，与圆心算距离 → 判定命中/偏离多少像素
  · 命中后圆变绿、偏离显示偏差值，**截图就能看出打中没打中**
  · 顶部实时记分：命中 n / 总数，一目了然
"""
import ctypes
import json
import random
import sys

# ⚠ 必须最先做：声明进程 DPI 感知。
# 不声明的话，Tk 的 winfo_rootx()/屏幕尺寸都会返回**逻辑像素**，
# 而 SendInput 操作的是**物理像素** —— 150% 缩放下差 1.5 倍，
# 表现为"agent 明明按圆心坐标点了，窗口收到的坐标却偏了一大截"（踩过）。
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

import tkinter as tk

RESULT = sys.argv[1] if len(sys.argv) > 1 else "range_result.jsonl"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
RADIUS = 34                                   # 圆的半径（点它需要精度）
MIN_GAP = RADIUS * 2 + 26                     # 圆之间留的间隙
WIN_W, WIN_H = 1180, 720

state = {"hits": 0, "shots": 0}
circles = []


def log(obj: dict) -> None:
    with open(RESULT, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


root = tk.Tk()
root.title("CLICK-RANGE")
# 居中摆放，位置确定后写进文件，agent 用 measure_window 也能算
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
x0 = (sw - WIN_W) // 2
y0 = (sh - WIN_H) // 2
root.geometry(f"{WIN_W}x{WIN_H}+{x0}+{y0}")
root.configure(bg="#12141a")
root.attributes("-topmost", True)

score = tk.Label(root, text="准备开始", font=("Consolas", 20, "bold"),
                 bg="#12141a", fg="#5afaff")
score.pack(pady=10)

canvas = tk.Canvas(root, width=WIN_W - 40, height=WIN_H - 110,
                   bg="#0b0d12", highlightthickness=0)
canvas.pack(padx=20, pady=(0, 14))


def make_circles() -> None:
    """随机撒点，保证互不重叠、且离边缘够远"""
    cw = WIN_W - 40
    ch = WIN_H - 110
    tries = 0
    while len(circles) < N and tries < 20000:
        tries += 1
        cx = random.randint(RADIUS + 12, cw - RADIUS - 12)
        cy = random.randint(RADIUS + 12, ch - RADIUS - 12)
        if all((cx - c["cx"]) ** 2 + (cy - c["cy"]) ** 2 >= MIN_GAP ** 2 for c in circles):
            circles.append({"cx": cx, "cy": cy, "hit": False, "off": None})


make_circles()
ids = []          # [(oval_id, text_id, index)]
for i, c in enumerate(circles):
    oid = canvas.create_oval(c["cx"] - RADIUS, c["cy"] - RADIUS,
                             c["cx"] + RADIUS, c["cy"] + RADIUS,
                             outline="#5afaff", width=3, fill="#16202b")
    tid = canvas.create_text(c["cx"], c["cy"], text=str(i + 1),
                             fill="#d2aaff", font=("Consolas", 22, "bold"))
    ids.append((oid, tid, i))

# 圆心是画布坐标，转成屏幕坐标后写文件 —— agent 只能看到屏幕坐标。
# ⚠ 必须 update() 而不是 update_idletasks()：后者不处理窗口管理器那一侧的摆放，
#   winfo_rootx() 会返回 0，于是算出"画布在屏幕原点"这种离谱坐标（踩过）。
root.update()
canvas.update_idletasks()
root.update_idletasks()
root.update()
cvs_root = (canvas.winfo_rootx(), canvas.winfo_rooty())
screen_circles = [
    {"i": i + 1, "x": cvs_root[0] + c["cx"], "y": cvs_root[1] + c["cy"], "r": RADIUS}
    for i, c in enumerate(circles)
]
win_rect = {"x": root.winfo_rootx(), "y": root.winfo_rooty(),
            "w": root.winfo_width(), "h": root.winfo_height()}
# 自检：画布不可能在屏幕原点，也不该跑到窗口外
assert cvs_root[0] > win_rect["x"] and cvs_root[1] > win_rect["y"], \
    f"画布原点算错了：canvas={cvs_root} window={win_rect}"

with open(RESULT + ".circles", "w", encoding="utf-8") as f:
    json.dump({"window": win_rect,
               "canvas_origin": {"x": cvs_root[0], "y": cvs_root[1]},
               "circles": screen_circles}, f, ensure_ascii=False, indent=2)

cw, chh = WIN_W - 40, WIN_H - 110


def on_click(e) -> None:
    """e.x/e.y 是画布坐标（相对 canvas 左上角）"""
    state["shots"] += 1
    best, best_d = None, 1e9
    for i, c in enumerate(circles):
        d = ((e.x - c["cx"]) ** 2 + (e.y - c["cy"]) ** 2) ** 0.5
        if d < best_d:
            best, best_d = i, d

    rec = {"shot": state["shots"], "canvas_x": e.x, "canvas_y": e.y,
           "screen_x": cvs_root[0] + e.x, "screen_y": cvs_root[1] + e.y,
           "nearest": best + 1 if best is not None else None,
           "distance": round(best_d, 2), "radius": RADIUS,
           "hit": bool(best is not None and best_d <= RADIUS)}
    log(rec)

    if best is not None:
        oid, tid, _ = ids[best]
        c = circles[best]
        off = round(best_d, 1)
        if rec["hit"]:
            state["hits"] += 1
            # 画布坐标就是圆心，用 canvas 自己的坐标画反馈（不能混用屏幕坐标）
            canvas.itemconfig(oid, outline="#3ddc84", width=4, fill="#123322")
            canvas.itemconfig(tid, text=f"{best + 1}\n✓")
        else:
            canvas.itemconfig(oid, outline="#ff5f56", width=4, fill="#331416")
            canvas.itemconfig(tid, text=f"{best + 1}\n{off:.0f}px")
        c["hit"] = c["hit"] or rec["hit"]
        c["off"] = off

    score.config(text=f"命中 {state['hits']} / 点击 {state['shots']} / 共 {N} 个")
    if state["hits"] >= N:
        score.config(text=f"★ 全部命中 {N}/{N} ★", fg="#3ddc84")

    # 让 agent 能通过截图看到结果（画布自身重绘）
    canvas.update_idletasks()


canvas.bind("<Button-1>", on_click)
log({"event": "ready", "circles": screen_circles,
     "window": {"x": root.winfo_rootx(), "y": root.winfo_rooty(), "w": WIN_W, "h": WIN_H}})

root.after(120000, root.destroy)          # 保险：2 分钟后自杀，不留孤儿窗口
root.mainloop()
