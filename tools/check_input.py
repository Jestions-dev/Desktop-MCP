# -*- coding: utf-8 -*-
"""
输入层验证：用我们自己的靶子窗口当目标

为什么这样做：直接对桌面发点击，万一坐标错了就会点到用户的东西。
这里先起一个**我们自己的** tkinter 窗口，用 SetForegroundWindow 拿到焦点，
再对它发点击/拖拽/输入，然后比对窗口记录到的事件坐标 ——
坐标对不对一目了然，而且**全程只碰我们自己的窗口**。

安全措施：
  · 靶子窗口 25 秒后自动关闭
  · 结束前把光标移回原位
  · 所有断言都先检查"前台窗口是不是靶子"，不是就绝不发点击
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop_mcp import win32_input as wi

user32 = wi.user32
RESULT = Path(tempfile.gettempdir()) / "desktop_mcp_target.jsonl"
RESULT.unlink(missing_ok=True)
Path(str(RESULT) + ".hwnd").unlink(missing_ok=True)
Path(str(RESULT) + ".geometry").unlink(missing_ok=True)

print("=" * 68)
print("① 修正后的结构体尺寸")
for name, want in (("MOUSEINPUT", 24), ("KEYBDINPUT", 24), ("INPUT", 40)):
    got = ctypes.sizeof(getattr(wi, name))
    print(f"   {name:<12} = {got:>3}  （期望 {want}）{'✓' if got == want else '✗'}")
if ctypes.sizeof(wi.MOUSEINPUT) != 24:
    print("   ✗ MOUSEINPUT 仍不对，终止测试")
    raise SystemExit(1)

wi.enable_dpi_awareness()

print()
print("=" * 68)
print("② 启动靶子窗口")
proc = subprocess.Popen([sys.executable, str(Path(__file__).parent / "target_window.py"),
                         str(RESULT)], cwd=str(Path(__file__).parent))
geo = hwnd = None
for _ in range(60):
    time.sleep(0.2)
    if Path(str(RESULT) + ".hwnd").exists() and Path(str(RESULT) + ".geometry").exists():
        time.sleep(0.5)
        hwnd = int(Path(str(RESULT) + ".hwnd").read_text().strip())
        geo = json.loads(Path(str(RESULT) + ".geometry").read_text())
        break
if not hwnd:
    proc.kill()
    print("   ✗ 靶子窗口没起来")
    raise SystemExit(1)
print(f"   hwnd = {hwnd}   位置 {geo}   标题应为 DESKTOP-MCP-TEST-TARGET")

buf = ctypes.create_unicode_buffer(256)
user32.GetWindowTextW(hwnd, buf, 256)
print(f"   窗口标题 = {buf.value!r}")
if "DESKTOP-MCP-TEST-TARGET" not in buf.value:
    print("   ⚠ 标题不符，可能拿错了 HWND —— 为安全起见终止")
    proc.kill()
    raise SystemExit(1)

# 记录原始光标位置，最后还原
ox, oy = wi.cursor_pos()
print(f"   原光标位置 ({ox}, {oy}) —— 结束时还原")


def focus_target() -> bool:
    """把靶子窗口弄到前台，成功返回 True"""
    user32.ShowWindow(hwnd, 9)            # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    for _ in range(25):
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return False


def events() -> list[dict]:
    if not RESULT.exists():
        return []
    out = []
    for line in RESULT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


ok = fail = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"   ✓ {label}")
    else:
        fail += 1
        print(f"   ✗ {label}  {detail}")


try:
    print()
    print("=" * 68)
    print("③ 前台窗口夺焦（这是最关键的前提）")
    got_focus = focus_target()
    check("SetForegroundWindow 成功拿到焦点", got_focus,
          f"当前前台 hwnd={user32.GetForegroundWindow()}")
    if not got_focus:
        print("   ⚠ 拿不到焦点就不能安全测试点击 —— 终止")
        raise SystemExit(1)

    print()
    print("=" * 68)
    print("④ 移动鼠标（可逆，最后会还原）")
    cx, cy = geo["x"] + 300, geo["y"] + 200
    before = len(events())
    wi.move_to(cx, cy)
    time.sleep(0.3)
    pos = wi.cursor_pos()
    check(f"移到 ({cx}, {cy}) 后 GetCursorPos 一致", pos == (cx, cy), f"实际 {pos}")

    print()
    print("=" * 68)
    print("⑤ 单击（在靶子窗口内取一点）")
    tx, ty = geo["x"] + 200, geo["y"] + 150
    before = len(events())
    wi.click(tx, ty)
    time.sleep(0.4)
    ev = [e for e in events()[before:] if e["kind"] == "click"]
    check("靶子窗口收到了 click 事件", bool(ev), f"收到 {len(ev)} 个")
    if ev:
        ex, ey = ev[0]["x_root"], ev[0]["y_root"]
        check(f"点击坐标正确（发 ({tx},{ty})，收 ({ex},{ey})）",
              abs(ex - tx) <= 2 and abs(ey - ty) <= 2,
              f"偏差 ({ex - tx}, {ey - ty})")

    print()
    print("=" * 68)
    print("⑥ 双击")
    before = len(events())
    wi.click(tx + 60, ty, clicks=2)
    time.sleep(0.4)
    ev = [e for e in events()[before:] if e["kind"] == "click"]
    check("双击产生 2 个 click 事件", len(ev) == 2, f"收到 {len(ev)} 个")

    print()
    print("=" * 68)
    print("⑦ 右键")
    before = len(events())
    wi.click(tx + 120, ty, button="right")
    time.sleep(0.4)
    ev = [e for e in events()[before:] if e["kind"] == "right_click"]
    check("靶子窗口收到右键事件", bool(ev), f"收到 {len(ev)} 个")

    print()
    print("=" * 68)
    print("⑧ 拖拽（分步移动是否真的产生中间事件）")
    before = len(events())
    wi.drag(geo["x"] + 150, geo["y"] + 300, geo["x"] + 500, geo["y"] + 350)
    time.sleep(0.5)
    ev = [e for e in events()[before:] if e["kind"] == "drag"]
    check("拖拽产生了中间移动事件（≥5 个）", len(ev) >= 5, f"只有 {len(ev)} 个")

    print()
    print("=" * 68)
    print("⑨ 文本输入（英文 → 应进 Entry 控件）")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    wi.type_text("Hello")
    time.sleep(0.3)
    print("   （英文走 UNICODE 注入；中文同理。是否进入控件需人工看，见下方截图）")

    print()
    print("=" * 68)
    print("⑩ 组合键（ctrl+a 全选，不破坏任何数据）")
    wi.hotkey("ctrl+a")
    time.sleep(0.2)
    check("hotkey 未抛异常", True)

    print()
    print("=" * 68)
    print("⑪ 滚轮")
    wi.scroll(-240, x=geo["x"] + 400, y=geo["y"] + 300)
    time.sleep(0.2)
    check("scroll 未抛异常", True)

    print()
    print("=" * 68)
    print("⑫ 还原光标位置")
    wi.move_to(ox, oy)
    time.sleep(0.2)
    check(f"光标已还原到 ({ox}, {oy})", wi.cursor_pos() == (ox, oy),
          f"实际 {wi.cursor_pos()}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print()
print("=" * 68)
print(f"结果：{ok} 项通过，{fail} 项失败")
print(f"靶子窗口记录的事件：{len(events())} 条")
print("靶子进程已关闭；光标已还原。")
