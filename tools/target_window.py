# -*- coding: utf-8 -*-
"""
验证靶子：一个记录鼠标事件的 tkinter 窗口

用法：python tools/target_window.py <结果文件路径>
窗口出现后自己把 HWND 写进 <结果文件>.hwnd，把收到的鼠标事件追加进 <结果文件>。
主测脚本据此判断"点击到底落在哪"。
"""
import ctypes
import json
import os
import sys
import tkinter as tk

RESULT = sys.argv[1] if len(sys.argv) > 1 else "target_result.jsonl"
SIZE = (900, 600)

events = []


def record(kind: str, e) -> None:
    ev = {"kind": kind, "x": e.x, "y": e.y, "x_root": e.x_root, "y_root": e.y_root}
    events.append(ev)
    with open(RESULT, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


root = tk.Tk()
root.title("DESKTOP-MCP-TEST-TARGET")
root.geometry(f"{SIZE[0]}x{SIZE[1]}+80+60")
root.attributes("-topmost", True)

label = tk.Label(root, text="测试靶子窗口\n（会被自动关闭）", font=("Microsoft YaHei", 16))
label.pack(pady=20)

entry = tk.Entry(root, font=("Microsoft YaHei", 12), width=40)
entry.pack(pady=10)

for seq, kind in (("<Button-1>", "click"), ("<Button-3>", "right_click"),
                  ("<ButtonRelease-1>", "release"), ("<B1-Motion>", "drag")):
    root.bind_all(seq, lambda e, k=kind: record(k, e))


def dump_hwnd() -> None:
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    # 更可靠：直接问 tkinter 自己的窗口 id
    wid = root.winfo_id()
    parent = ctypes.windll.user32.GetParent(wid)
    with open(RESULT + ".hwnd", "w", encoding="utf-8") as f:
        f.write(str(parent or wid))
    with open(RESULT + ".geometry", "w", encoding="utf-8") as f:
        f.write(json.dumps({"x": root.winfo_rootx(), "y": root.winfo_rooty(),
                            "w": root.winfo_width(), "h": root.winfo_height()}))


root.after(600, dump_hwnd)
root.after(25000, root.destroy)          # 保险：25 秒后自杀，不留孤儿窗口
root.mainloop()
