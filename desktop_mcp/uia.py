# -*- coding: utf-8 -*-
"""
UIA 层 —— 无障碍树那条腿

为什么要有它：截屏只能"看图猜坐标"，花图片 token，窗口一动、DPI 一变、主题一换
就得重新看。UIA 树是**纯文本**，每个控件带类型、名字、可点/可写标志，
"点那个叫『保存』的按钮"能直接落到控件上，不用猜像素。

两条腿各自有用：
  · 原生 / WinUI 程序（资源管理器、设置、对话框）→ 树很全，优先用树
  · Electron / Chromium（DSH 自己、VSCode、浏览器）→ 树往往只有窗框几个按钮，
    网页内容要 Chromium 自己打开无障碍才给，实测经常拿不到 → 退回截图

坐标系与截图一致：**全屏物理像素，原点在主屏左上角**。
索引只在「同一份快照」里有效 —— 每次操作前按同样参数重走一遍树，
拿到新鲜控件再动手，避免用几秒前的缓存去点已经变了的位置。
"""
from __future__ import annotations

import ctypes
import time
from typing import Any, Optional

from . import win32_input as I
from . import win32_window as W


class UiaError(Exception):
    """UIA 不可用或操作失败。"""


try:                                            # pragma: no cover - 环境相关
    import uiautomation as auto
except Exception as exc:                        # noqa: BLE001
    auto = None
    _IMPORT_ERROR: Optional[BaseException] = exc
else:
    _IMPORT_ERROR = None


def available() -> tuple[bool, str]:
    """能不能用 UIA。返回 (可用, 说明)。"""
    if auto is None:
        return False, f"uiautomation 没装上（{_IMPORT_ERROR}）；pip install uiautomation"
    return True, "ok"


def _need() -> None:
    ok, why = available()
    if not ok:
        raise UiaError(why)


# ── 窗口解析 ────────────────────────────────────────────────────────────────

def _resolve_window(window: Any):
    """
    拿到目标窗口的 UIA 控件。

    window 可以是 hwnd（int）、标题关键词（str）、或 None / True（前台窗口）。
    """
    _need()
    hwnd: Optional[int] = None
    label = ""

    if isinstance(window, bool) or window is None:
        fg = W.foreground()
        if fg is None:
            raise UiaError("当前没有前台窗口")
        hwnd, label = fg.hwnd, fg.title
    elif isinstance(window, int):
        hwnd, label = window, W.info(window).title
    else:
        q = str(window).strip()
        if not q:
            raise UiaError("window 不能是空字符串")
        hits = W.find(q, limit=1)
        if hits:
            hwnd, label = hits[0].hwnd, hits[0].title
        else:
            # 有些窗口（任务栏、部分 UI 框架）Win32 标题是空的，只有 UIA 名字。
            # 那种只能用 UIA 自己找。
            root = auto.GetRootControl()
            for _, control in _walk(root, 2, 300, True):
                if q.lower() in _name_of(control).lower():
                    handle = _safe(lambda c=control: c.NativeWindowHandle, 0)
                    if handle:
                        return control, int(handle), _name_of(control)
            raise UiaError(f"没有标题或 UIA 名字匹配 {q!r} 的窗口")

    try:
        control = auto.ControlFromHandle(hwnd)
    except Exception as exc:                    # noqa: BLE001
        raise UiaError(f"拿不到 hwnd={hwnd} 的 UIA 控件：{exc}") from exc
    if control is None:
        raise UiaError(f"hwnd={hwnd} 没有 UIA 控件（可能窗口已关）")
    return control, hwnd, label


# ── 树遍历 ──────────────────────────────────────────────────────────────────

def _safe(fn, default):
    try:
        return fn()
    except Exception:                           # noqa: BLE001
        return default


def _type_of(control) -> str:
    name = _safe(lambda: control.ControlTypeName, "") or ""
    return name[:-7] if name.endswith("Control") else (name or "?")


def _name_of(control) -> str:
    return str(_safe(lambda: control.Name, "") or "")


def _rect_of(control) -> Optional[tuple[int, int, int, int]]:
    r = _safe(lambda: control.BoundingRectangle, None)
    if r is None:
        return None
    left, top = int(r.left), int(r.top)
    width, height = int(r.right) - left, int(r.bottom) - top
    if width < 0 or height < 0:
        return None
    return left, top, width, height


def _flags(control) -> str:
    """标出这个控件能干哪些事，方便模型挑。"""
    marks = []
    for mark, getter in (
        ("⚡", "GetInvokePattern"),            # 能按
        ("✎", "GetValuePattern"),              # 能写
        ("✔", "GetTogglePattern"),             # 能勾
        ("◎", "GetSelectionItemPattern"),      # 能选
    ):
        fn = getattr(control, getter, None)
        if fn is None:
            continue
        try:
            pattern = fn()
            if pattern is not None and not getattr(pattern, "IsNullPattern", False):
                marks.append(mark)
        except Exception:                       # noqa: BLE001
            continue
    if not marks and _type_of(control) in ("Button", "MenuItem", "Hyperlink", "ListItem", "TabItem"):
        marks.append("⚡")
    return "".join(marks)


def _walk(root, max_depth: int, max_nodes: int, include_offscreen: bool):
    """先把树走完，再建文本 —— 索引和顺序一次定死。"""
    out: list[tuple[int, Any]] = []
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack and len(out) < max_nodes:
        control, depth = stack.pop(0)
        out.append((depth, control))
        if depth >= max_depth:
            continue
        children = _safe(lambda c=control: list(c.GetChildren()), []) or []
        for child in reversed(children):
            if not include_offscreen and _safe(lambda c=child: c.IsOffscreen, False):
                continue
            stack.insert(0, (child, depth + 1))
    return out[:max_nodes]


def _label(text: str, limit: int = 52) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format(nodes, title: str, hwnd: int, limit: int, truncated: bool) -> str:
    lines = [
        f"UIA 快照 · 「{_label(title, 40)}」 hwnd=0x{hwnd:X} · {len(nodes)} 个节点"
        + ("（到上限截断，调大 max_nodes 看更多）" if truncated else ""),
        "坐标系：全屏物理像素，原点主屏左上角。索引只对这份快照有效。",
        "⚡可点 ✎可写 ✔可勾 ◎可选中",
    ]
    for index, (depth, control) in enumerate(nodes):
        ctype = _type_of(control)
        name = _label(_name_of(control))
        rect = _rect_of(control)
        where = f" @{rect[0]},{rect[1]},{rect[2]}x{rect[3]}" if rect else ""
        marks = _flags(control)
        suffix = f"  {marks}" if marks else ""
        lines.append(f"{'  ' * depth}[{index}] {ctype} {name!r}{where}{suffix}")
    return "\n".join(lines)


# ── 快照缓存 ────────────────────────────────────────────────────────────────

_LAST: dict[str, Any] = {"hwnd": None, "max_depth": 6, "max_nodes": 300, "offscreen": False}


def snapshot(window: Any = None, max_depth: int = 6, max_nodes: int = 300,
             include_offscreen: bool = False) -> tuple[str, int, str]:
    """抓一棵树。返回 (文本, hwnd, 标题)。"""
    root, hwnd, title = _resolve_window(window)
    max_depth = max(1, min(int(max_depth or 6), 16))
    max_nodes = max(10, min(int(max_nodes or 300), 2000))

    nodes = _walk(root, max_depth, max_nodes, bool(include_offscreen))
    _LAST.update(hwnd=hwnd, max_depth=max_depth, max_nodes=max_nodes,
                 offscreen=bool(include_offscreen), title=title)
    text = _format(nodes, title, hwnd, max_nodes, len(nodes) >= max_nodes)
    return text, hwnd, title


def _refind(index: int):
    """按上次快照的参数重走一遍，取第 index 个控件（拿新鲜的，不用旧缓存）。"""
    _need()
    if _LAST["hwnd"] is None:
        raise UiaError("还没有快照 —— 先调 desktop_snapshot")
    root = auto.ControlFromHandle(_LAST["hwnd"])
    nodes = _walk(root, _LAST["max_depth"], _LAST["max_nodes"], _LAST["offscreen"])
    if index < 0 or index >= len(nodes):
        raise UiaError(f"index {index} 超出范围（这份树有 {len(nodes)} 个节点，先重新快照）")
    return nodes[index][1]


def _center(control) -> tuple[int, int]:
    rect = _rect_of(control)
    if rect is None:
        raise UiaError("这个控件没有矩形，点不了")
    left, top, width, height = rect
    return left + width // 2, top + height // 2


# ── 动作 ────────────────────────────────────────────────────────────────────

def click_node(index: int, button: str = "left", clicks: int = 1) -> str:
    """
    点第 index 个控件。

    优先走 UIA 的 Invoke / DoDefaultAction —— 那等于"程序自己按"，不依赖像素，
    窗口被挡住也没关系。都不支持才退回鼠标点矩形中心。
    """
    control = _refind(int(index))
    name, ctype = _label(_name_of(control), 40), _type_of(control)

    if button == "left" and int(clicks or 1) == 1:
        try:
            pattern = control.GetInvokePattern()
            if pattern is not None and not getattr(pattern, "IsNullPattern", False):
                pattern.Invoke()
                return f"已点 [{index}] {ctype} {name!r}（Invoke 模式，没有动鼠标）"
        except Exception:                       # noqa: BLE001
            pass
        try:
            legacy = control.GetLegacyIAccessiblePattern()
            if legacy is not None and not getattr(legacy, "IsNullPattern", False):
                legacy.DoDefaultAction()
                return f"已点 [{index}] {ctype} {name!r}（DoDefaultAction，没有动鼠标）"
        except Exception:                       # noqa: BLE001
            pass

    x, y = _center(control)
    try:
        control.SetFocus()
        time.sleep(0.05)
    except Exception:                           # noqa: BLE001
        pass
    I.move_to(x, y)
    time.sleep(0.04)
    I.click(x, y, button=button, clicks=int(clicks or 1))
    return f"已点 [{index}] {ctype} {name!r} @{x},{y}（鼠标点击）"


def set_value(index: int, text: str) -> str:
    """往第 index 个控件写文字。优先 ValuePattern，写不了才点一下再敲键盘。"""
    control = _refind(int(index))
    name, ctype = _label(_name_of(control), 40), _type_of(control)

    try:
        pattern = control.GetValuePattern()
        if pattern is not None and not getattr(pattern, "IsNullPattern", False):
            pattern.SetValue(str(text))
            return f"已写入 [{index}] {ctype} {name!r}（ValuePattern）"
    except Exception:                           # noqa: BLE001
        pass

    x, y = _center(control)
    control.SetFocus()
    I.click(x, y)
    time.sleep(0.08)
    I.hotkey("ctrl+a")
    time.sleep(0.03)
    I.type_text(str(text))
    return f"已写入 [{index}] {ctype} {name!r}（点进去打字的）"


def focus_node(index: int) -> str:
    control = _refind(int(index))
    control.SetFocus()
    return f"已聚焦 [{index}] {_type_of(control)} {_label(_name_of(control), 40)!r}"


def wait_for(window: Any = None, name: Optional[str] = None, control_type: Optional[str] = None,
             timeout: float = 10.0, interval: float = 0.25) -> str:
    """
    等一个控件出现。比 sleep 固定秒数靠谱 —— 界面什么时候好，让它自己说。
    """
    _need()
    if not name and not control_type:
        raise UiaError("name 和 control_type 至少给一个")
    deadline = time.time() + max(0.5, float(timeout or 10.0))
    needle = (name or "").lower()
    want = (control_type or "").lower()
    last_error = ""
    while time.time() < deadline:
        try:
            root, hwnd, title = _resolve_window(window)
            nodes = _walk(root, 8, 800, False)
            for _, control in nodes:
                if needle and needle not in _name_of(control).lower():
                    continue
                if want and want != _type_of(control).lower():
                    continue
                rect = _rect_of(control)
                where = f" @{rect[0]},{rect[1]},{rect[2]}x{rect[3]}" if rect else ""
                return (f"等到了：「{_label(title, 30)}」里的 {_type_of(control)} "
                        f"{_label(_name_of(control), 40)!r}{where}（重新快照拿索引）")
        except UiaError as exc:
            last_error = str(exc)
        time.sleep(max(0.1, float(interval or 0.25)))
    tail = f"（最后一次错误：{last_error}）" if last_error else ""
    return f"等了 {timeout}s 没出现：name~{name!r} type={control_type!r}{tail}"


# ── 显示器 / 剪贴板 ─────────────────────────────────────────────────────────

def monitors_text() -> str:
    """枚举显示器（几何 + 物理尺寸），顺带说明虚拟桌面的范围。"""
    from . import screen as S

    items = S.monitors()
    left, top, right, bottom = S.virtual_bounds()
    # mss 偶尔把主屏报两次，去重
    seen, unique = set(), []
    for m in items:
        key = (m.left, m.top, m.width, m.height)
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    lines = [f"显示器 {len(unique)} 块；虚拟桌面 ({left},{top}) → ({right},{bottom})"
             f"  共 {right - left}x{bottom - top}"]
    for i, m in enumerate(unique):
        lines.append(f"  [{i}] {m.width}x{m.height} @{m.left},{m.top}"
                     + ("  （主屏）" if m.left == 0 and m.top == 0 else ""))
    return "\n".join(lines)


def clipboard_get() -> str:
    """读剪贴板文本（CF_UNICODETEXT）。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13

    # ⚠ 64 位上必须显式声明签名：默认按 32 位 int 传参，
    # HGLOBAL 一进去就被截断，报 "int too long to convert"（踩过）
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    if not user32.OpenClipboard(None):
        raise UiaError("打不开剪贴板（被别的程序占着？）")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return "（剪贴板里没有文本）"
        pointer = kernel32.GlobalLock(ctypes.c_void_p(handle))
        if not pointer:
            raise UiaError("GlobalLock 失败")
        try:
            text = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
        if not text:
            return "（剪贴板里没有文本）"
        return f"剪贴板（{len(text)} 字）：\n{text[:4000]}"
    finally:
        user32.CloseClipboard()


def clipboard_set(text: str) -> str:
    """写剪贴板文本。"""
    I.set_clipboard_text(str(text))
    return f"已写入剪贴板（{len(str(text))} 字）"
