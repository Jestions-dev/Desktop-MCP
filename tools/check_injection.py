# -*- coding: utf-8 -*-
"""
注入验证：鼠标移动/点击/拖拽、键盘按键/中文输入 —— 全部用我们自己的窗口当靶子

为什么必须做这一步：
  之前只测了"结构体尺寸对不对"，结果 MOUSEINPUT/KEYBDINPUT 构造时传了 None，
  **所有注入其实都是坏的**，测试却全绿。尺寸对 ≠ 能用。
  这里的每条断言都要求"靶子真的收到/系统状态真的变了"。
"""
import ctypes
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
from desktop_mcp import win32_input as I

user32 = I.user32
I.enable_dpi_awareness()

RESULT = Path(tempfile.gettempdir()) / "desktop_mcp_inject.jsonl"
for suf in ("", ".hwnd", ".geometry", ".text"):
    Path(str(RESULT) + suf).unlink(missing_ok=True)

# --- 靶子：窗口记录鼠标事件；一个 Entry 用来接收按键
target_src = '''
import ctypes, json, sys, tkinter as tk
RESULT = sys.argv[1]
def rec(kind, e=None, extra=None):
    d = {"kind": kind}
    if e is not None:
        d.update({"x": e.x, "y": e.y, "x_root": e.x_root, "y_root": e.y_root})
    if extra: d.update(extra)
    open(RESULT, "a", encoding="utf-8").write(json.dumps(d, ensure_ascii=False) + "\\n")
root = tk.Tk(); root.title("INJECT-TEST-TARGET"); root.geometry("760x420+120+100")
root.attributes("-topmost", True)
lbl = tk.Label(root, text="注入测试靶子", font=("Microsoft YaHei", 14)); lbl.pack(pady=8)
ent = tk.Entry(root, font=("Microsoft YaHei", 13), width=46); ent.pack(pady=6)
ent.focus_set()
def on_key(e):
    rec("key", extra={"keysym": e.keysym, "char": e.char})
ent.bind("<Key>", on_key)
for seq, kind in (("<Button-1>","click"), ("<Button-3>","rclick"), ("<B1-Motion>","drag")):
    root.bind_all(seq, lambda e, k=kind: rec(k, e))
def dump():
    root.update_idletasks()
    wid = root.winfo_id(); parent = ctypes.windll.user32.GetParent(wid)
    open(RESULT + ".hwnd","w").write(str(parent or wid))
    open(RESULT + ".geometry","w").write(json.dumps(
        {"x": root.winfo_rootx(), "y": root.winfo_rooty(),
         "w": root.winfo_width(), "h": root.winfo_height()}))
root.after(500, dump)
root.after(40000, root.destroy)
root.mainloop()
'''
tp = Path(__file__).parent / "_inject_target.py"
tp.write_text(target_src, encoding="utf-8")
tp.unlink(missing_ok=True)
tp.write_text(target_src, encoding="utf-8")

proc = subprocess.Popen([sys.executable, str(tp), str(RESULT)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"   ✓ {label}")
    else:
        fail += 1
        print(f"   ✗ {label}  {detail}")


def events():
    if not RESULT.exists():
        return []
    return [json.loads(l) for l in RESULT.read_text(encoding="utf-8").splitlines() if l.strip()]


geo = hwnd = None
for _ in range(60):
    time.sleep(0.2)
    if Path(str(RESULT) + ".hwnd").exists() and Path(str(RESULT) + ".geometry").exists():
        time.sleep(0.4)
        hwnd = int(Path(str(RESULT) + ".hwnd").read_text().strip())
        geo = json.loads(Path(str(RESULT) + ".geometry").read_text())
        break

ox, oy = I.cursor_pos()
try:
    if not hwnd:
        print("✗ 靶子没起来")
        raise SystemExit(1)
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    print("=" * 70)
    print(f"靶子 hwnd={hwnd} 标题={buf.value!r} 位置={geo}")
    if "INJECT-TEST-TARGET" not in buf.value:
        print("✗ 拿错窗口，中止")
        raise SystemExit(1)

    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    for _ in range(30):
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            break
    check("拿到前台焦点", user32.GetForegroundWindow() == hwnd)

    print()
    print("─" * 70)
    print("① 鼠标：移动（只读校验）")
    tx, ty = geo["x"] + 300, geo["y"] + 200
    try:
        I.move_to(tx, ty)
        time.sleep(0.25)
        check(f"移动后光标 = ({tx},{ty})", I.cursor_pos() == (tx, ty), f"实际 {I.cursor_pos()}")
    except Exception as e:
        check("移动鼠标", False, f"{type(e).__name__}: {e}")

    print()
    print("② 鼠标：单击（靶子必须记录到）")
    n0 = len(events())
    try:
        I.click(geo["x"] + 180, geo["y"] + 260)
        time.sleep(0.35)
        ev = [e for e in events()[n0:] if e["kind"] == "click"]
        check("靶子收到 click", bool(ev), f"收到 {len(ev)} 个")
        if ev:
            check(f"坐标正确（发 {geo['x']+180},{geo['y']+260} → 收 {ev[0]['x_root']},{ev[0]['y_root']}）",
                  abs(ev[0]["x_root"] - (geo["x"] + 180)) <= 2 and
                  abs(ev[0]["y_root"] - (geo["y"] + 260)) <= 2)
    except Exception as e:
        check("点击", False, f"{type(e).__name__}: {e}")

    print()
    print("③ 鼠标：右键 + 拖拽")
    n0 = len(events())
    try:
        I.click(geo["x"] + 240, geo["y"] + 260, button="right")
        time.sleep(0.3)
        check("靶子收到右键", any(e["kind"] == "rclick" for e in events()[n0:]))
        n0 = len(events())
        I.drag(geo["x"] + 150, geo["y"] + 330, geo["x"] + 520, geo["y"] + 360)
        time.sleep(0.4)
        drags = [e for e in events()[n0:] if e["kind"] == "drag"]
        check(f"拖拽产生中间事件（{len(drags)} 个 ≥5）", len(drags) >= 5)
    except Exception as e:
        check("右键/拖拽", False, f"{type(e).__name__}: {e}")

    print()
    print("④ 键盘：组合键（靶子收到 ctrl+a）")
    n0 = len(events())
    try:
        I.hotkey("ctrl+a")
        time.sleep(0.35)
        keys = [e for e in events()[n0:] if e["kind"] == "key"]
        check(f"靶子收到按键（{len(keys)} 个）", bool(keys), "一个都没收到")
        if keys:
            print(f"      收到：{[(k.get('keysym'), k.get('char')) for k in keys[:6]]}")
    except Exception as e:
        check("组合键", False, f"{type(e).__name__}: {e}")

    print()
    print("⑤ 键盘：普通按键（应能在 Entry 里累积出字符）")
    n0 = len(events())
    try:
        I.type_text("abc")
        time.sleep(0.35)
        chars = "".join(e.get("char", "") for e in events()[n0:] if e["kind"] == "key")
        check(f"靶子收到字符 {chars!r}（期望 'abc'）", chars == "abc", f"实际 {chars!r}")
    except Exception as e:
        check("普通按键", False, f"{type(e).__name__}: {e}")

    print()
    print("⑥ 键盘：中文（UNICODE 注入）")
    n0 = len(events())
    try:
        I.type_text("中文")
        time.sleep(0.35)
        chars = "".join(e.get("char", "") for e in events()[n0:] if e["kind"] == "key")
        check(f"靶子收到中文 {chars!r}（期望 '中文'）", chars == "中文", f"实际 {chars!r}")
        if chars != "中文":
            print("      说明：UNICODE 注入对 tkinter Entry 可能不生效，真实程序里可用剪贴板兜底")
    except Exception as e:
        check("中文输入", False, f"{type(e).__name__}: {e}")

    print()
    print("⑦ 滚轮与还原")
    try:
        I.scroll(-240, x=geo["x"] + 380, y=geo["y"] + 300)
        check("滚轮未抛异常", True)
    except Exception as e:
        check("滚轮", False, f"{type(e).__name__}: {e}")
    I.move_to(ox, oy)
    time.sleep(0.2)
    check(f"光标已还原 ({ox},{oy})", I.cursor_pos() == (ox, oy), f"实际 {I.cursor_pos()}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    tp.unlink(missing_ok=True)

print()
print("=" * 70)
print(f"结果：{ok} 项通过，{fail} 项失败")
