# -*- coding: utf-8 -*-
"""
工具层 —— 暴露给 MCP 的桌面操作能力

设计原则（用户 2026-10-12 定）：**纯工具，不做软件**。
没有悬浮球、没有内置对话页、没有桌宠；一切通过 MCP 被 agent 调用。

坐标系（唯一的真相，写进每次截图说明里）：
  · 位置一律是**全屏物理像素**，原点在主屏左上角；多屏在左侧时 x 可为负
  · 也接受 0–1000 的分数坐标（`fx`/`fy`），按**整个虚拟桌面**换算 —— 这样模型
    只看缩略图也能估位置，不必知道真实分辨率
"""
from __future__ import annotations

import random
import time
from typing import Any, Optional

from . import screen as S
from . import win32_input as I
from . import win32_window as W
from . import electron_frame as EF
from . import trajectory as TJ


class ToolError(Exception):
    """工具执行失败（服务器会把它转成 MCP 的 isError:true）"""


# ---------------------------------------------------------------- 坐标解析
def _bounds() -> tuple[int, int, int, int]:
    return S.virtual_bounds()


def resolve_pos(args: dict, prefix: str = "") -> tuple[int, int]:
    """
    从参数里取一个位置。支持两种写法：
      · x / y              —— 全屏物理像素
      · fx / fy（加 prefix 后）—— 0–1000 的分数，按虚拟桌面换算
    """
    kx, ky = f"{prefix}x", f"{prefix}y"
    fx, fy = f"{prefix}fx", f"{prefix}fy"
    left, top, w, h = _bounds()
    if args.get(fx) is not None or args.get(fy) is not None:
        try:
            px = left + float(args.get(fx, 500)) / 1000.0 * w
            py = top + float(args.get(fy, 500)) / 1000.0 * h
        except (TypeError, ValueError):
            raise ToolError(f"{fx}/{fy} 必须是 0–1000 的数字")
        return int(round(px)), int(round(py))
    if args.get(kx) is None or args.get(ky) is None:
        raise ToolError(f"需要位置：给 `{kx}`/`{ky}`（像素）或 `{fx}`/`{fy}`（0–1000 分数）")
    try:
        return int(float(args[kx])), int(float(args[ky]))
    except (TypeError, ValueError):
        raise ToolError(f"{kx}/{ky} 必须是数字")


def _clamp_to_desktop(x: int, y: int) -> tuple[int, int]:
    left, top, w, h = _bounds()
    x = min(max(x, left), left + w - 1)
    y = min(min(max(y, top), top + h - 1), top + h - 1)
    return x, y


# ---------------------------------------------------------------- 截图说明
def _shot_note(extra: str = "") -> str:
    left, top, w, h = _bounds()
    fg = W.foreground()
    lines = [f"屏幕：虚拟桌面 ({left},{top}) {w}×{h}"
             f"{S.scale_note()}"]
    if fg:
        lines.append(f"前台窗口：{fg.title or '(无标题)'} [{fg.process}] "
                     f"hwnd={fg.hwnd} ({fg.rect[0]},{fg.rect[1]})-({fg.rect[2]},{fg.rect[3]})")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def _resolve_window_arg(args: dict):
    """
    从参数里解析出要截的窗口。默认**前台窗口** —— 因为 agent 要操作的就是
    "当前这个窗口"，截它语义最清楚，而且被挡住也能拿到完整内容。
    """
    if args.get("window") is False or str(args.get("window", "")).lower() in ("screen", "0"):
        return None
    if args.get("hwnd") is not None:
        return W.info(int(args["hwnd"]))
    q = args.get("window")
    if isinstance(q, str) and q.strip() and q.lower() not in ("foreground", "active"):
        hits = W.find(q, limit=2)
        if not hits:
            raise ToolError(f"没找到标题或进程名匹配 {q!r} 的窗口")
        if len(hits) > 1:
            listing = "\n".join("  " + w.describe() for w in W.find(q, limit=6))
            raise ToolError(f"{q!r} 匹配到多个窗口，请用 hwnd 指定：\n{listing}")
        return hits[0]
    return W.foreground()          # 默认：前台窗口


def _do_shot(args: dict, note: str = ""):
    """
    截图。三种模式，按优先级：
      1. region=[l,t,w,h]      —— 指定屏幕矩形
      2. x/y(+width/height)    —— 指定位置和大小
      3. 默认                  —— **前台窗口**（agent 要操作的就是它）
    传 window=false / window="screen" 或 monitor=n 则退化为屏幕截图。
    """
    # --- 1/2：显式给了区域
    region = None
    if args.get("region") is not None:
        r = args["region"]
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            raise ToolError("region 必须是 [left, top, width, height]")
        region = tuple(int(float(v)) for v in r)
    elif any(args.get(k) is not None for k in ("x", "y", "fx", "fy")):
        x, y = resolve_pos(args)
        w = int(float(args.get("width") or 400))
        h = int(float(args.get("height") or 300))
        region = (x, y, max(1, w), max(1, h))

    if region is not None:
        img = S.grab(region=region)
        png = S.to_png_bytes(img, max_width=int(args.get("max_width") or 1600))
        return (_shot_note(f"截取屏幕区域 {region}；图像 {img.width}×{img.height}"
                           + (f"\n{note}" if note else "")), png)

    # --- 3：窗口截图（默认）
    win = _resolve_window_arg(args)
    if win is not None:
        warn = ""
        if win.minimized:
            warn = ("\n⚠ **该窗口当前是最小化状态** —— Windows 下最小化窗口只能截到标题栏那一条，"
                    "画面里的内容不可用。要操作它就先用 focus_window 还原，再截图。")
        try:
            img = S.grab_window(win.hwnd, crop_client=bool(args.get("client_only")))
            st = S.content_stats(img)
            png = S.to_png_bytes(img, max_width=int(args.get("max_width") or 1600))
            l, t, r, b = win.rect
            extra = ""
            if st["blank"] and not win.minimized:
                extra = (f"\n⚠ 图像近乎纯色（标准差 {st['stddev']}）——可能没截到内容，"
                         f"试试 window=false 截整屏，或先 focus_window 把窗口调到前台。")
            return (_shot_note(
                f"窗口截图：{win.title or '(无标题)'} [{win.process}] hwnd={win.hwnd}\n"
                f"  窗口矩形 ({l},{t})-({r},{b}) {win.width}×{win.height}"
                f"{'（已裁成客户区）' if args.get('client_only') else ''}\n"
                f"  图像 {img.width}×{img.height}｜灰度均值 {st['mean']} 标准差 {st['stddev']}"
                + (f"\n{note}" if note else "") + extra + warn), png)
        except Exception as e:
            # 窗口截不了（少数程序禁止），退回屏幕截图而不是直接失败
            mon = 0
            img = S.grab(monitor=mon)
            png = S.to_png_bytes(img, max_width=int(args.get("max_width") or 1600))
            return (_shot_note(
                f"⚠ 窗口截图失败（{e}），已退回整屏截图。\n"
                f"目标窗口：{win.title or '(无标题)'} [{win.process}] hwnd={win.hwnd} "
                f"({win.rect[0]},{win.rect[1]})-({win.rect[2]},{win.rect[3]})"
                + (f"\n{note}" if note else "") + warn), png)

    # --- 显式要屏幕
    mon = int(args.get("monitor") or 0)
    img = S.grab(monitor=mon)
    png = S.to_png_bytes(img, max_width=int(args.get("max_width") or 1600))
    return (_shot_note(f"屏幕截图：显示器 {mon}（0=整个虚拟桌面）；"
                       f"图像 {img.width}×{img.height}"
                       + (f"\n{note}" if note else "")), png)


# ---------------------------------------------------------------- 工具实现
def t_screenshot(args: dict):
    text, png = _do_shot(args)
    return text, False, [png]


def t_click(args: dict):
    x, y = resolve_pos(args)
    x, y = _clamp_to_desktop(x, y)
    button = str(args.get("button") or "left").lower()
    clicks = int(args.get("clicks") or 1)
    I.move_to(x, y)
    time.sleep(0.03)
    pos = I.click(None, None, button=button, clicks=clicks)
    time.sleep(float(args.get("wait") or 0.35))
    text = f"已在 ({x}, {y}) {'双击' if clicks == 2 else f'{clicks} 连击'} {button} 键；光标现在 {pos}"
    if args.get("screenshot", True):
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_move(args: dict):
    x, y = resolve_pos(args)
    x, y = _clamp_to_desktop(x, y)
    I.move_to(x, y)
    return f"光标已移到 ({x}, {y})", False, []


def t_drag(args: dict):
    x1, y1 = resolve_pos(args, "from_")
    if args.get("from_x") is None and args.get("from_fx") is None:
        x1, y1 = resolve_pos(args, "")          # 也允许 x/y 作为起点
    x2, y2 = resolve_pos(args, "to_")
    button = str(args.get("button") or "left").lower()
    dur = float(args.get("duration") or 0.35)
    I.drag(x1, y1, x2, y2, button=button, duration=dur)
    time.sleep(float(args.get("wait") or 0.3))
    text = f"已从 ({x1}, {y1}) 拖到 ({x2}, {y2})（{button} 键，{dur}s）"
    if args.get("screenshot", True):
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_scroll(args: dict):
    amount = int(args.get("amount") or -360)
    x = y = None
    if args.get("x") is not None or args.get("fx") is not None:
        x, y = resolve_pos(args)
        x, y = _clamp_to_desktop(x, y)
        I.move_to(x, y)
    I.scroll(amount, horizontal=bool(args.get("horizontal")))
    time.sleep(float(args.get("wait") or 0.25))
    where = f"在 ({x}, {y})" if x is not None else "在当前位置"
    text = f"{where} 滚动 {amount}（{'右' if amount > 0 else '下' if amount < 0 else '无'}，"
    text += "水平" if args.get("horizontal") else "垂直"
    text += f"；一格=120）"
    if args.get("screenshot", False):
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_type(args: dict):
    text = args.get("text")
    if text is None:
        raise ToolError("需要 text 参数")
    text = str(text)
    if not text:
        raise ToolError("text 不能为空")
    if args.get("x") is not None or args.get("fx") is not None:
        cx, cy = resolve_pos(args)
        I.move_to(*_clamp_to_desktop(cx, cy))
        time.sleep(0.05)
        I.click()                                # 先点一下确保焦点落在目标上
        time.sleep(0.08)

    method = str(args.get("method") or "unicode")
    if method == "clipboard":
        I.set_clipboard_text(text)
        time.sleep(0.05)
        I.hotkey("ctrl+v")
        how = "剪贴板粘贴"
    else:
        # ⚠ 默认留一点字符间隔。全速注入时，记事本这类程序会把字符**顺序搞乱**、
        #   甚至与已有文本互相覆盖 —— 实测：62 个字符灌进去，结果绞成一团，
        #   而工具照样报"已输入 62 个字符"（静默出错，最难查）。
        #   中文尤其明显（一个字要走两趟消息）。0.006s 是速度与可靠性的折中：
        #   ASCII 基本瞬间打完，中文每字 12ms。要更快/更稳可用 per_char 覆盖。
        per_char = args.get("per_char")
        per_char = 0.006 if per_char is None else max(0.0, float(per_char))
        I.type_text(text, per_char=per_char)
        how = "UNICODE 注入"
    time.sleep(max(0.0, float(args.get("wait") or 0.25)))
    preview = text if len(text) <= 40 else text[:40] + "…"
    out = (f"已输入 {len(text)} 个字符（{how}）：{preview!r}\n"
           f"提示：{how} 对部分程序（游戏、某些 Electron）无效，"
           f"那种情况改用 method=\"clipboard\"（会覆盖用户剪贴板）")
    if args.get("screenshot", False):
        extra, png = _do_shot({}, out)
        return extra, False, [png]
    return out, False, []


def t_press_keys(args: dict):
    keys = args.get("keys")
    if keys is None:
        raise ToolError("需要 keys 参数，如 \"ctrl+s\" 或 [\"alt\",\"tab\"]")
    try:
        I.hotkey(keys, gap=0.01)
    except ValueError as e:
        raise ToolError(str(e))
    time.sleep(max(0.0, float(args.get("wait") or 0.2)))
    shown = keys if isinstance(keys, str) else "+".join(keys)
    return f"已按键：{shown}（keys={shown!r}）", False, []


def t_list_windows(args: dict):
    q = args.get("query")
    if q:
        wins = W.find(str(q), limit=int(args.get("limit") or 20))
        head = f"匹配 {q!r} 的窗口：{len(wins)} 个"
    else:
        wins = W.list_windows(only_titled=True, limit=int(args.get("limit") or 40))
        head = f"可见窗口：{len(wins)} 个（前台排最前）"
    if not wins:
        return head + "\n（没有匹配）", False, []
    return head + "\n" + "\n".join("  " + w.describe() for w in wins), False, []


def t_get_foreground(args: dict):
    fg = W.foreground()
    if not fg:
        return "当前没有前台窗口", False, []
    text = "前台窗口：\n  " + fg.describe()
    if args.get("screenshot", True):
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_focus_window(args: dict):
    """
    激活窗口，或改它的显示状态（最大化/最小化/还原）。

    合并在一个工具里是有意的：这几件事都需要先定位窗口（hwnd 或 query），
    再对一个窗口做动作 —— 拆成两个工具只会让调用方多绕一步。
    """
    hwnd = args.get("hwnd")
    query = args.get("query")
    action = str(args.get("action") or "activate").lower()
    if hwnd is None and not query:
        raise ToolError("需要 hwnd 或 query 指定窗口")
    title = ""
    if hwnd is None:
        hits = W.find(str(query), limit=5)
        if not hits:
            raise ToolError(f"没找到匹配 {query!r} 的窗口")
        if len(hits) > 1:
            listing = "\n".join("  " + w.describe() for w in hits)
            raise ToolError(f"{query!r} 匹配到 {len(hits)} 个窗口，请用 hwnd 指定：\n{listing}")
        hwnd, title = hits[0].hwnd, hits[0].title

    try:
        ok = W.set_state(int(hwnd), action)
    except ValueError as e:
        raise ToolError(str(e))
    if not ok:
        raise ToolError(f"对窗口 {hwnd} 执行 {action} 失败（窗口可能已关闭）")

    if action in ("activate", "focus", "show"):
        # 激活有前台锁定，可能静默失败 —— 复核一次再报结果
        time.sleep(0.25)
        if W.user32.GetForegroundWindow() != int(hwnd):
            raise ToolError(f"激活窗口 {hwnd} 失败（被前台锁定挡住）—— "
                            f"可以让用户手点一下该窗口，然后重试；别反复重试。")

    time.sleep(float(args.get("wait") or 0.3))
    state = W.state_of(int(hwnd))
    label = {"activate": "已激活", "maximize": "已最大化", "minimize": "已最小化",
             "restore": "已还原"}.get(action, f"已执行 {action}")
    text = f"{label}窗口 hwnd={hwnd}" + (f"「{title}」" if title else "") + f"（当前状态：{state}）"
    if args.get("screenshot", True) and action != "minimize":
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_measure_window(args: dict):
    hwnd = args.get("hwnd")
    query = args.get("query")
    if hwnd is None and not query:
        raise ToolError("需要 hwnd 或 query")
    if hwnd is None:
        hits = W.find(str(query), limit=2)
        if not hits:
            raise ToolError(f"没找到匹配 {query!r} 的窗口")
        hwnd = hits[0].hwnd
    w = W.info(int(hwnd))
    cl, ct, cw, ch = W.client_rect_screen(int(hwnd))
    x1, y1 = _clamp_to_desktop(w.rect[0], w.rect[1])
    x2, y2 = _clamp_to_desktop(w.rect[2] - 1, w.rect[3] - 1)
    text = "\n".join([
        f"窗口：{w.title or '(无标题)'} [{w.process}] hwnd={w.hwnd}",
        f"  整窗：({w.rect[0]},{w.rect[1]})-({w.rect[2]},{w.rect[3]})  {w.width}×{w.height}",
        f"  客户区：({cl},{ct}) {cw}×{ch}   ← 点控件用这个坐标系",
        f"  最小化：{'是' if w.minimized else '否'}｜前台：{'是' if w.foreground else '否'}",
        f"  分数位置换算（0–1000，相对虚拟桌面）：",
        f"    左上角 fx,fy = {_frac(x1, y1)}",
        f"    右下角 fx,fy = {_frac(x2, y2)}",
        f"    中心   fx,fy = {_frac((w.rect[0] + w.rect[2]) // 2, (w.rect[1] + w.rect[3]) // 2)}",
    ])
    return text, False, []


def _frac(x: int, y: int) -> str:
    left, top, w, h = _bounds()
    fx = round((x - left) / w * 1000)
    fy = round((y - top) / h * 1000)
    return f"{fx}, {fy}"


def t_wait(args: dict):
    secs = float(args.get("seconds") or 1)
    if secs < 0 or secs > 60:
        raise ToolError("seconds 需在 0–60 之间")
    time.sleep(secs)
    text = f"已等待 {secs}s"
    if args.get("screenshot", True):
        extra, png = _do_shot({}, text)
        return extra, False, [png]
    return text, False, []


def t_highlight(args: dict):
    """
    在屏幕上标出某个矩形（给人看）。这是唯一保留的"可见"功能：
    让用户看得见 agent 正在关注哪里。

    渲染交给 Electron 子进程（见 electron_frame.py）。框没起就自动起一个 ——
    用户不用先手动"打开框"，工具自己保证可用；想省资源可以用 desktop_frame_stop 收掉。
    """
    if args.get("hide"):
        f = EF.get_frame()
        if f is None or not f.running:
            return "观察框本来就没显示（也没在运行）", False, []
        try:
            f.hide()
        except Exception as e:
            raise ToolError(f"隐藏失败：{type(e).__name__}: {e}")
        return "观察框已隐藏（进程仍在运行；要收掉它用 desktop_frame_stop）", False, []

    # 算目标矩形
    region = args.get("region")
    if isinstance(region, (list, tuple)) and len(region) == 4:
        x, y, w, h = (int(float(v)) for v in region)
    elif args.get("hwnd") is not None or args.get("query"):
        hwnd = args.get("hwnd")
        if hwnd is None:
            hits = W.find(str(args["query"]), limit=2)
            if not hits:
                raise ToolError(f"没找到匹配 {args['query']!r} 的窗口")
            hwnd = hits[0].hwnd
        l, t, r, b = W.info(int(hwnd)).rect
        x, y, w, h = l, t, r - l, b - t
        if t < -1000:      # 最小化窗口的坐标是 (-32000,-32000)
            raise ToolError("该窗口是最小化的，框会画到屏幕外。先 desktop_focus_window 还原它。")
    else:
        x, y = resolve_pos(args)
        w = int(float(args.get("width") or 400))
        h = int(float(args.get("height") or 300))

    f = EF.get_frame()
    if f is None or not f.running:
        try:
            f = EF.start_frame()
        except Exception as e:
            raise ToolError(f"观察框启动失败：{e}")

    try:
        f.show_region(x, y, w, h)
    except Exception as e:
        raise ToolError(f"发指令失败（观察框可能已退出）：{type(e).__name__}: {e}")

    # 回包里的坐标要等 Electron 的下一条 stdout 事件，通常还没到 —— 所以只报我们确定的
    return ("已在屏幕上标出 "
            f"({x},{y}) {w}×{h}"
            f"\n  渲染窗口会外扩 {EF_frame_glow()}px 给辉光留空间"
            f"\n  渲染进程：{f.describe()}"), False, []


def EF_frame_glow() -> int:
    """frame.css 里 #frame 的 inset（窗口外扩量），只用于文案"""
    return 44


# ---------------------------------------------------------------- 观察框进程管理
def t_frame_start(args: dict):
    """启动观察框渲染进程（常驻，直到 stop）。"""
    if EF.get_frame() is not None and EF.get_frame().running:
        return f"观察框已在运行：{EF.get_frame().describe()}", False, []
    try:
        f = EF.start_frame()
    except Exception as e:
        raise ToolError(f"启动失败：{e}")
    return (f"观察框已启动：{f.describe()}\n"
            f"  用 desktop_highlight 标位置；desktop_frame_stop 收掉它"), False, []


def t_frame_stop(args: dict):
    """收掉观察框渲染进程（释放那个 Electron 进程）。"""
    f = EF.get_frame()
    if f is None or not f.running:
        return "观察框本来就没在运行", False, []
    desc = f.describe()
    stopped = EF.stop_frame()
    return (f"已收掉观察框（{desc}）" if stopped else "观察框未在运行"), False, []


def t_frame_status(args: dict):
    f = EF.get_frame()
    if f is None:
        return ("观察框：未启动\n"
                "  （desktop_highlight 会自动起它，也可以先 desktop_frame_start）"), False, []
    lines = [f"观察框：{f.describe()}"]
    if f.errors:
        lines.append("  最近错误：")
        lines += [f"    · {e[:160]}" for e in f.errors[-3:]]
    if f.logs:
        lines.append("  渲染进程日志（末尾）：")
        lines += [f"    · {l[:160]}" for l in f.logs[-3:]]
    return "\n".join(lines), False, []


# ---------------------------------------------------------------- 人味点击
def t_click_human(args: dict):
    """
    用**真人录制的轨迹**把光标移到目标再点击，而不是两点一线。

    轨迹由独立工具 tools/record_trajectory.py 采集（真人按住鼠标往按钮上拖），
    存在 trajectories/ 里。本工具只读、只放 —— 不参与录制。
    """
    tx, ty = resolve_pos(args)
    tx, ty = _clamp_to_desktop(tx, ty)

    trajs = TJ.load_all()
    if not trajs:
        raise ToolError(
            f"没有可用的鼠标轨迹（{TJ.traj_dir()}）。\n"
            f"  录制方法：python tools/record_trajectory.py\n"
            f"  窗口里按住鼠标朝按钮拖、松开，就录下一条。")

    # 起点：默认从当前位置出发（最自然 —— 人的手也总是从"现在在哪"出发）
    cur = I.cursor_pos()
    sx, sy = int(float(args.get("from_x", cur[0]))), int(float(args.get("from_y", cur[1])))
    sx, sy = _clamp_to_desktop(sx, sy)

    # 挑一条轨迹：默认随机，也可以指定文件名复现某条。
    want = args.get("trajectory")
    if want:
        picked = [t for t in trajs if t.get("_file") == want]
        if not picked:
            raise ToolError(f"没有叫 {want!r} 的轨迹")
        tr = picked[0]
        pick_why = "指定"
    else:
        # ⭐ 优先挑**原生方向就接近目标方向**的那条。
        # 为什么要这样：旋转虽然保住了路径形状，但**速度剖面是绑定在录制方向上的**
        # —— 实测"推"（朝右上）峰值 3512 px/s、"拉"（朝左下）只有 1984，
        # 收尾/峰值比 0.10 vs 0.30。旋转会把"推"的剖面用在"拉"的方向上，
        # 那就不像人了。四象限各录了样本之后，就能挑同向的，旋转角接近 0。
        import math as _m
        tvx, tvy = tx - sx, ty - sy
        tlen = _m.hypot(tvx, tvy) or 1.0
        ranked = []
        for t in trajs:
            p0 = t["points"][0]
            rvx, rvy = -float(p0[0]), -float(p0[1])      # 这条轨迹的原生方向
            rlen = _m.hypot(rvx, rvy) or 1.0
            cos = (tvx * rvx + tvy * rvy) / (tlen * rlen)
            ranked.append((cos, t))
        ranked.sort(key=lambda x: -x[0])
        # 从方向最接近的前几条里随机挑（保留变化，又避免挑到反向的）
        top = ranked[:max(1, min(4, len(ranked)))]
        if random.random() < 0.8:
            tr = random.choice(top)[1]
            pick_why = f"方向匹配（前列 {len(top)} 条中随机）"
        else:
            tr = random.choice(trajs)
            pick_why = "随机（保留变化）"

    speed = float(args.get("speed") or 1.0)
    jitter = float(args.get("jitter", 2.0))
    t_jitter = float(args.get("time_jitter", 0.15))

    try:
        path = TJ.plan_path(tr, (sx, sy), (tx, ty), jitter_px=jitter)
    except ValueError as e:
        raise ToolError(f"这条轨迹没法用：{e}")

    button = str(args.get("button") or "left")
    clicks = max(1, int(args.get("clicks") or 1))

    def do_click():
        I.click(button=button, clicks=clicks)

    info = TJ.replay(I.move_to, do_click, path, speed=speed, time_jitter=t_jitter)

    # 复核：计划末点 vs 点击后的实际光标。**立刻读**，中间不插 sleep ——
    # 插了的话用户一动鼠标就读到别处，会被误判成"没落准"（骗过自己一轮）。
    import ctypes

    class _PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    _p = _PT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(_p))
    actual = (int(_p.x), int(_p.y))
    planned_end = (int(path[-1][0]), int(path[-1][1]))
    landed = (abs(actual[0] - tx) <= 3 and abs(actual[1] - ty) <= 3)

    time.sleep(max(0.0, float(args.get("wait") or 0.25)))

    out = (f"已按真人轨迹点击 ({tx},{ty})"
           f"\n  轨迹：{tr.get('_file')}（录于 {tr.get('recorded_at', '?')}；{pick_why}）"
           f"\n  起点：({sx},{sy}) → 终点 ({tx},{ty})，直线距离 "
           f"{((tx - sx) ** 2 + (ty - sy) ** 2) ** 0.5:.0f}px"
           f"\n  过程：{info['moves']} 步 / 约 {info['duration_ms']}ms / 节奏倍率 {speed}"
           f" / 时间抖动 ±{t_jitter:.0%}"
           f"\n  落点复核：计划末点 {planned_end}，点击后光标 {actual}，"
           f"{'✓ 一致' if landed else f'✗ 差了 {abs(actual[0] - tx) + abs(actual[1] - ty)}px'}"
           f"\n  轨迹库：{TJ.stats()}")
    if args.get("screenshot", True):
        extra, png = _do_shot({}, out)
        return extra, False, [png]
    return out, False, []


# ---------------------------------------------------------------- 注册表
def _pos_props(prefix: str = "", label: str = "") -> dict:
    p = prefix
    return {
        f"{p}x": {"type": "number", "description": f"{label}全屏物理像素 X"},
        f"{p}y": {"type": "number", "description": f"{label}全屏物理像素 Y"},
        f"{p}fx": {"type": "number", "description": f"{label}分数 X（0–1000，按整个虚拟桌面）"},
        f"{p}fy": {"type": "number", "description": f"{label}分数 Y（0–1000）"},
    }


SHOT_PROPS = {
    "window": {"description": "截哪个窗口：省略=前台窗口（默认）；也可给标题/进程名关键词；"
                              "传 false 或 \"screen\" 则截整个屏幕"},
    "hwnd": {"type": "number", "description": "直接指定窗口句柄"},
    "client_only": {"type": "boolean", "description": "只截客户区（裁掉标题栏边框），点控件时坐标对得上"},
    "region": {"type": "array", "items": {"type": "number"},
               "description": "[left, top, width, height] 截屏幕上的这一块"},
    "monitor": {"type": "number", "description": "显示器序号，0=整个虚拟桌面，1..n=单个屏"},
    "max_width": {"type": "number", "description": "输出 PNG 的最大宽度，默认 1600"},
    **_pos_props(),
    "width": {"type": "number", "description": "配合 x/y 使用时截取区域的宽"},
    "height": {"type": "number", "description": "配合 x/y 使用时截取区域的高"},
}

# 坐标换算提醒：这段在几个工具里复用。它是实测吃过亏写下来的 ——
# 截图被 max_width 缩小后，从图上读到的坐标必须乘回去才能给点击工具，否则点偏。
_COORD_HINT = ("坐标是**全屏物理像素**（原点在主屏左上角），也给 fx/fy（0–1000 分数，"
               "按整个虚拟桌面换算）。⚠ 从截图预览上读坐标时，先按 原图宽÷预览宽 换算回原图，"
               "再乘 DPI 缩放（150% 就再乘 1.5）—— 直接用预览坐标点会偏（踩过）。")

TOOLS: list[dict] = [
    {
        "name": "desktop_screenshot",
        "description": "截屏并返回图像。**默认截当前前台窗口** —— agent 要操作的就是它，"
                       "而且窗口被挡住、或一部分在屏幕外，也能截到完整内容（PrintWindow 让窗口自己重绘）。\n"
                       "要看别的窗口：传 window=\"标题关键词\" 或 hwnd；要看整屏：window=false。\n"
                       "两个已知限制（不是 bug）：最小化窗口只能截到标题栏那一条（会明确警告）；"
                       "不渲染到屏幕的内容（硬件加速浮层等）任何 GDI 抓屏都拿不到。\n"
                       "返回文本里写明坐标系、窗口矩形、前台窗口，以及图像的灰度均值/标准差"
                       "（标准差接近 0 说明这张图没内容）。",
        "inputSchema": {"type": "object", "properties": SHOT_PROPS},
    },
    {
        "name": "desktop_click",
        "description": "点击。默认左键单击，完成后自动截屏返回结果。clicks=2 是双击。\n"
                       "它会先把鼠标移过去再点 —— 分步移动能触发悬停效果（下拉菜单、tooltip）。\n"
                       + _COORD_HINT,
        "inputSchema": {"type": "object", "properties": {
            **_pos_props(),
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "默认 left"},
            "clicks": {"type": "number", "description": "连击次数，默认 1"},
            "wait": {"type": "number", "description": "点完等待几秒再截图，默认 0.35。界面慢就调大"},
            "screenshot": {"type": "boolean", "description": "是否自动截屏返回，默认 true"},
        }},
    },
    {
        "name": "desktop_type",
        "description": "输入文字（**支持中文**，走 UNICODE 注入，绕过键盘布局）。"
                       "可选先点一下 x/y 确保焦点落在目标上。\n"
                       "⚠ 默认每个字符留 6ms 间隔。**去掉间隔会出事**：全速注入时记事本这类程序"
                       "会把字符顺序搞乱、甚至和已有文本绞在一起，而工具照样报成功（实测踩过）。"
                       "要更快就调小 per_char，要更稳就调大（0.02 对中文很安全）。\n"
                       "对游戏、部分 Electron 无效时改 method=\"clipboard\"（走剪贴板粘贴）—— "
                       "⚠ 那个方式会**覆盖用户剪贴板里原有的内容**，只在 unicode 失败时用。",
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要输入的文本"},
            "method": {"type": "string", "enum": ["unicode", "clipboard"], "description": "默认 unicode"},
            **_pos_props(),
            "per_char": {"type": "number",
                         "description": "每个字符的间隔秒数，默认 0.006。乱序就调大（0.02 稳）；追求快可设 0"},
            "wait": {"type": "number", "description": "输入后等待秒数"},
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 false"},
        }, "required": ["text"]},
    },
    {
        "name": "desktop_press",
        "description": "按组合键，如 \"ctrl+s\"、\"alt+tab\"、\"win+r\"、[\"ctrl\",\"shift\",\"esc\"]。"
                       "顺序按下、逆序抬起，和真人按键一致。\n"
                       "系统截图键（PrtScn、Win+Shift+S/3/4/5）**被主动拒绝** —— "
                       "它会拉起系统截图工具、把桌面搅乱，而需要截图时应该直接调 desktop_screenshot。",
        "inputSchema": {"type": "object", "properties": {
            "keys": {"description": "\"ctrl+s\" 这样的字符串，或 [\"ctrl\",\"s\"] 数组"},
            "wait": {"type": "number", "description": "按完等待秒数"},
        }, "required": ["keys"]},
    },
    {
        "name": "desktop_move",
        "description": "只移动光标，不点击 —— 用来触发悬停效果（展开菜单、显示 tooltip），"
                       "或把鼠标从挡视线的地方挪开。\n" + _COORD_HINT,
        "inputSchema": {"type": "object", "properties": _pos_props()},
    },
    {
        "name": "desktop_drag",
        "description": "按住并拖动（从 from_ 到 to_）。**分 20 步移动**，所以能触发画布、滑块、"
                       "拖放目标需要的中间事件 —— 一步跳过去它们收不到。\n"
                       "拖文件、拉滑块、框选文字、移动窗口都用它；duration 调大更像人手拖。\n"
                       + _COORD_HINT,
        "inputSchema": {"type": "object", "properties": {
            **_pos_props("from_", "起点"),
            **_pos_props("to_", "终点"),
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "duration": {"type": "number", "description": "拖动耗时秒数，默认 0.35"},
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 true"},
        }},
    },
    {
        "name": "desktop_scroll",
        "description": "滚轮。正数向上/向右，负数向下/向左，一格 = 120。"
                       "看网页一整屏大约 3 格（-360），翻一页文档多点几次。\n"
                       "传了 x/y 会先把光标移过去再滚 —— **要滚某个区域就必须给坐标**，"
                       "否则滚的是光标当前所在的那个窗口。",
        "inputSchema": {"type": "object", "properties": {
            "amount": {"type": "number", "description": "滚轮量，默认 -360"},
            "horizontal": {"type": "boolean", "description": "true 则水平滚动"},
            **_pos_props(),
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 false"},
        }},
    },
    {
        "name": "desktop_list_windows",
        "description": "列出可见窗口（前台排最前），或按关键词查。三个用途："
                       "① 操作某个窗口前拿到它的 hwnd；"
                       "② 确认某个程序/网页**有没有加载完**（标题变了就是加载完了）；"
                       "③ 没有 window_title 参数的工具用 query 定位目标。\n"
                       "输出每行含 hwnd、标题、进程名+PID、矩形、[前台]/[最小化] 标记。"
                       "最小化窗口的坐标是 (-32000,-32000)，别对它做点击或截图。",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "按标题或进程名模糊匹配，如 \"记事本\"、\"chrome\""},
            "limit": {"type": "number", "description": "最多返回几个，默认 40"},
        }},
    },
    {
        "name": "desktop_foreground_window",
        "description": "看当前哪个窗口在前台（含进程名、位置、尺寸），并截屏。"
                       "**输入之前先调它是个好习惯** —— 确认焦点真在你要操作的那个窗口上，"
                       "免得把字打到别处。",
        "inputSchema": {"type": "object", "properties": {
            "screenshot": {"type": "boolean", "description": "是否截屏，默认 true"},
        }},
    },
    {
        "name": "desktop_focus_window",
        "description": "定位一个窗口然后对它做动作（hwnd 或 query 指定）：\n"
                       "  action=\"activate\"（默认）切到前台，最小化的会自动还原\n"
                       "  action=\"maximize\" 最大化　action=\"minimize\" 最小化　action=\"restore\" 还原成普通大小\n"
                       "query 匹配到多个会报错并列出候选，让你改用 hwnd（不替你猜）。\n"
                       "Windows 有前台锁定：激活可能失败，那时提示里会说明 —— "
                       "**不要反复重试**，让用户手点一下那个窗口即可。",
        "inputSchema": {"type": "object", "properties": {
            "hwnd": {"type": "number", "description": "窗口句柄"},
            "query": {"type": "string", "description": "标题/进程名关键词"},
            "action": {"type": "string",
                       "enum": ["activate", "maximize", "minimize", "restore"],
                       "description": "默认 activate（切前台）"},
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 true（minimize 时不截）"},
        }},
    },
    {
        "name": "desktop_measure_window",
        "description": "量窗口：整窗/客户区在屏幕上的矩形，并直接给出左上角/右下角/中心的 0–1000 分数坐标。"
                       "**要用分数坐标点窗口里的控件时，先用这个换算** —— 比从截图肉眼估准。\n"
                       "注意统一坐标系：窗口矩形是物理像素，截图可能是缩放过的。",
        "inputSchema": {"type": "object", "properties": {
            "hwnd": {"type": "number"},
            "query": {"type": "string"},
        }},
    },
    {
        "name": "desktop_wait",
        "description": "等待若干秒（等界面加载/动画结束），可选截屏确认。\n"
                       "⚠ 它只是固定等待，没有\"等到某条件成立\"。要等某个窗口出现/标题变化，"
                       "用 desktop_list_windows 轮询（间隔 0.5s 左右，设个上限别死等）—— "
                       "比如启动程序后循环查它出现没有。",
        "inputSchema": {"type": "object", "properties": {
            "seconds": {"type": "number", "description": "0–60，默认 1"},
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 true"},
        }},
    },
    {
        "name": "desktop_highlight",
        "description": "在屏幕上画一个发光的框，标出正在关注的位置 —— **给人看的**："
                       "用户能看见 agent 在看哪一块，而不用猜。做连续操作、或在长任务中途时用它。\n"
                       "首次调用会自动启动渲染进程（约 0.1s）；支持 region / hwnd / query / x,y+width,height。"
                       "hide=true 收起框（进程留着，下次更快；彻底收掉用 desktop_frame_stop）。",
        "inputSchema": {"type": "object", "properties": {
            "region": {"type": "array", "items": {"type": "number"},
                       "description": "[left, top, width, height]"},
            "hwnd": {"type": "number"},
            "query": {"type": "string"},
            "hide": {"type": "boolean", "description": "true 则收起框"},
            **_pos_props(),
            "width": {"type": "number"},
            "height": {"type": "number"},
        }},
    },
    {
        "name": "desktop_click_human",
        "description": "用**真人录制的鼠标轨迹**把光标移到目标再点击 —— 不是两点一线。"
                       "轨迹里带着人手的过冲回调、不对称加减速和微小抖动，"
                       "行为分析上更像人（普通 desktop_click 是瞬移式直线，一眼假）。\n"
                       "每次随机挑一条轨迹、并加轻微抖动，所以重复调用不会一模一样。\n"
                       "起点默认是光标当前位置（人的手也总从「现在在哪」出发）；"
                       "要复现某条轨迹就传它的文件名。轨迹库为空时会提示怎么录。",
        "inputSchema": {"type": "object", "properties": {
            **_pos_props(),
            "from_x": {"type": "number", "description": "起点 X（默认=光标当前位置）"},
            "from_y": {"type": "number", "description": "起点 Y（默认=光标当前位置）"},
            "trajectory": {"type": "string", "description": "指定用哪条轨迹（文件名），默认随机"},
            "speed": {"type": "number", "description": "节奏倍率：1=原速（真人速度），2=慢一倍"},
            "jitter": {"type": "number", "description": "每个点的随机抖动像素，默认 2"},
            "time_jitter": {"type": "number",
                            "description": "每段间隔的随机扰动比例，默认 0.15（±15%）。"
                                           "**时间也是行为特征** —— 设为 0 则严格照录制的节奏，"
                                           "重复调用会一模一样"},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "默认 left"},
            "clicks": {"type": "number", "description": "连击次数，默认 1"},
            "wait": {"type": "number", "description": "点完等待秒数，默认 0.25"},
            "screenshot": {"type": "boolean", "description": "是否截屏返回，默认 true"},
        }},
    },
    {
        "name": "desktop_frame_start",
        "description": "启动观察框渲染进程（常驻，像浏览器 MCP 的浏览器那样）。"
                       "平时不用手动调 —— desktop_highlight 会自动起。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "desktop_frame_stop",
        "description": "收掉观察框渲染进程，释放那个 Electron 子进程。"
                       "想省资源时用；下次 highlight 需要时会自动重新启动。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "desktop_frame_status",
        "description": "看观察框渲染进程的状态：在不在跑、PID、窗口句柄、命令端口，"
                       "以及最近的错误和渲染日志。**框画不出来时先查这个** —— "
                       "常见原因是 node_modules 链接丢了或 Electron 找不到。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_DISPATCH = {
    "desktop_screenshot": t_screenshot,
    "desktop_click": t_click,
    "desktop_type": t_type,
    "desktop_press": t_press_keys,
    "desktop_move": t_move,
    "desktop_drag": t_drag,
    "desktop_scroll": t_scroll,
    "desktop_list_windows": t_list_windows,
    "desktop_foreground_window": t_get_foreground,
    "desktop_focus_window": t_focus_window,
    "desktop_measure_window": t_measure_window,
    "desktop_wait": t_wait,
    "desktop_highlight": t_highlight,
    "desktop_click_human": t_click_human,
    "desktop_frame_start": t_frame_start,
    "desktop_frame_stop": t_frame_stop,
    "desktop_frame_status": t_frame_status,
}


def list_tools() -> list[dict]:
    return TOOLS


def call_tool_ex(name: str, args: dict) -> tuple[str, bool, list[bytes]]:
    """
    执行工具，返回 (文本, 是否失败, 图片列表)。

    异常在这里收口，不抛给 JSON-RPC 层：MCP 规范要求工具**执行**失败用
    result.isError=true 表示，而不是 JSON-RPC error。
    """
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"未知工具：{name}（可用：{', '.join(_DISPATCH)}）", True, []
    if not isinstance(args, dict):
        return f"arguments 必须是对象，收到 {type(args).__name__}", True, []
    try:
        out = fn(args)
        if len(out) == 3:
            return out[0], bool(out[1]), list(out[2] or [])
        return out[0], bool(out[1]), []
    except ToolError as e:
        return str(e), True, []
    except Exception as e:
        return f"{type(e).__name__}: {e}", True, []
