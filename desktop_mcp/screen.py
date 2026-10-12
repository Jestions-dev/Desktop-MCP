# -*- coding: utf-8 -*-
"""
截屏层：拿屏幕图像，并支持"标记观察区域"

用 mss（已在环境里）抓屏。返回 PNG 字节或 PIL 图像。
坐标系：全屏物理像素，原点在主屏左上角（overlay/win32_input 同约定）。
"""
from __future__ import annotations

import ctypes
import io
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

IS_WINDOWS = sys.platform == "win32"


def _ensure_dpi_aware() -> None:
    """
    任何截图/量窗口的代码路径都要先保证 DPI 感知。

    ⚠ 这个坑我踩了四次（观察框位置、录制器窗口、光标落点、截图尺寸），
    每次现象不同、根因相同：**验证的进程不感知 DPI，读到虚拟化坐标**
    （150% 屏上是真实值的 2/3）。典型症状是"明明该对却差 1.5 倍"。

    正常情况走 win32_input 的 import 副作用就够了（它会设一次）；
    这里是兜底 —— 有些脚本只 import 本模块，不碰 win32_input。
    """
    if not IS_WINDOWS:
        return
    try:
        from .win32_input import _DPI_LEVEL  # noqa: F401  已被 import 侧设过
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


_ensure_dpi_aware()


@dataclass
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool


def _sct():
    import mss
    return mss.mss()


def monitors() -> list[Monitor]:
    """列出所有显示器（索引 0 是"整个虚拟桌面"，1..n 是各个屏幕）"""
    with _sct() as s:
        out = []
        for i, m in enumerate(s.monitors):
            out.append(Monitor(i, m["left"], m["top"], m["width"], m["height"], i == 1))
        return out


def virtual_bounds() -> tuple[int, int, int, int]:
    """整个虚拟桌面的 (left, top, width, height)"""
    with _sct() as s:
        m = s.monitors[0]
        return m["left"], m["top"], m["width"], m["height"]


def _cloak_frame(region: Optional[tuple[int, int, int, int]]) -> None:
    """
    截图前的"斗篷"—— 曾经用来把观察框挪出画面，免得 agent 看见自己的框。

    **现在不需要了**：观察框由 Electron 渲染，带 setContentProtection(true)
    （等价 WDA_EXCLUDEFROMCAPTURE），我截图本来就拍不到它。
    保留这个空函数是为了不动调用点，也留个位置说明这件事的来龙去脉 ——
    Tk 时代必须手动挪（Tk 没有采集排除），换 Electron 之后这条自动消失。
    """
    return


def grab(monitor: int = 0, region: Optional[tuple[int, int, int, int]] = None,
         hide_frame: bool = True):
    """
    截屏，返回 PIL.Image（RGB）。

    monitor: 0 = 整个虚拟桌面；1..n = 单个显示器
    region:  可选 (left, top, width, height)，全屏物理像素；给了就优先用它
    hide_frame: 截图前把观察框移出画面（只在它会入画时才动）
    """
    from PIL import Image

    if hide_frame:
        area = region
        if area is None:
            try:
                with _sct() as s:
                    m = s.monitors[monitor]
                    area = (m["left"], m["top"], m["width"], m["height"])
            except Exception:
                area = None
        _cloak_frame(area)

    try:
        with _sct() as s:
            if region is not None:
                left, top, w, h = region
                area = {"left": int(left), "top": int(top),
                        "width": max(1, int(w)), "height": max(1, int(h))}
            else:
                idx = int(monitor)
                if idx < 0 or idx >= len(s.monitors):
                    raise ValueError(f"monitor 越界：{idx}（共 {len(s.monitors)} 个，0=整个桌面）")
                area = s.monitors[idx]
            shot = s.grab(area)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    finally:
        # 观察框不用再"放回去"了：Electron 版带采集排除，截图拍不到它，
        # 也就不需要先挪开（Tk 时代那套 cloak/resume 已随 overlay.py 一起退休）
        pass
    return img


def to_png_bytes(img, max_width: int = 0, quality_scale: float = 1.0) -> bytes:
    """
    转成 PNG 字节。max_width > 0 时按比例缩小（省 token）。

    图像走 MCP 的 image content 返回给模型，所以尺寸直接决定成本：
    2560×1600 的原图会让上下文吃紧，缩到 1280 宽足够看清界面结构。
    """
    if max_width and img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, int(img.height * ratio))), 1)   # LANCZOS
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def content_stats(img) -> dict:
    """
    粗略判断截图里有没有"真内容"。

    为什么需要：最小化的窗口用 PrintWindow 只能截到标题栏一条（几百字节、
    近乎纯色），agent 看到会误判成"窗口里什么都没有"，然后去点不存在的控件。
    PNG 体积不可靠 —— 一张纯色 2560×1600 也能压到几 KB，所以要看像素统计。
    """
    try:
        from PIL import ImageStat
        st = ImageStat.Stat(img.convert("L"))
        mean = st.mean[0]
        stddev = st.stddev[0]
        return {"mean": round(mean, 1), "stddev": round(stddev, 1),
                "blank": stddev < 3.0}
    except Exception:
        return {"mean": -1, "stddev": -1, "blank": False}


def scale_note():
    """DPI 缩放说明（写进工具输出，帮模型换算坐标）"""
    if not IS_WINDOWS:
        return ""
    import ctypes
    u = ctypes.windll.user32
    dpi = u.GetDpiForSystem() if hasattr(u, "GetDpiForSystem") else 96
    if dpi and dpi != 96:
        return f"（系统 DPI {dpi}，缩放 {dpi / 96:.0%}；截图为物理像素）"
    return ""


# ---------------------------------------------------------------- 窗口截图
PW_RENDERFULLCONTENT = 0x00000002      # 让窗口把完整内容（含 DirectComposition）画进来
BI_RGB = 0
DIB_RGB_COLORS = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _gdi():
    import ctypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    u.PrintWindow.restype = wintypes.BOOL
    return u, g


def grab_window(hwnd: int, crop_client: bool = False):
    """
    截取指定窗口。

    走 `PrintWindow(PW_RENDERFULLCONTENT)`：让窗口**自己重绘**到内存 DC。
    所以即使窗口被别的窗口挡住、或一部分在屏幕外，也能拿到完整内容 ——
    普通抓屏做不到，而 agent 操作窗口时恰恰需要这个。

    crop_client=True 时按客户区裁掉标题栏和边框（点控件时坐标对得上）。
    少数老程序不支持 PrintWindow，会抛 OSError，由调用方决定是否退回屏幕截图。
    """
    import ctypes
    from PIL import Image

    from .win32_window import client_rect_screen, info as win_info

    u, g = _gdi()
    w = win_info(int(hwnd))
    x1, y1, x2, y2 = w.rect
    width, height = max(1, x2 - x1), max(1, y2 - y1)

    hdc_screen = u.GetDC(None)
    hdc_mem = g.CreateCompatibleDC(hdc_screen)
    if not hdc_mem:
        u.ReleaseDC(None, hdc_screen)
        raise OSError("CreateCompatibleDC 失败")

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height          # 负数 = 自上而下，省一次翻转
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    hbmp = g.CreateDIBSection(hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS,
                              ctypes.byref(bits), None, 0)
    if not hbmp or not bits:
        g.DeleteDC(hdc_mem)
        u.ReleaseDC(None, hdc_screen)
        raise OSError("CreateDIBSection 失败")

    old = g.SelectObject(hdc_mem, hbmp)
    try:
        got = u.PrintWindow(wintypes.HWND(int(hwnd)), hdc_mem, PW_RENDERFULLCONTENT)
        if not got:
            got = u.PrintWindow(wintypes.HWND(int(hwnd)), hdc_mem, 0)
        if not got:
            raise OSError(f"PrintWindow 失败（hwnd={hwnd}）—— 该程序可能禁止被截取")
        raw = ctypes.string_at(bits, width * height * 4)
        img = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        if old:
            g.SelectObject(hdc_mem, old)
        g.DeleteObject(hbmp)
        g.DeleteDC(hdc_mem)
        u.ReleaseDC(None, hdc_screen)

    if crop_client:
        cx, cy, cw, ch = client_rect_screen(int(hwnd))
        left = max(0, cx - x1)
        top = max(0, cy - y1)
        right = min(width, left + max(1, cw))
        bottom = min(height, top + max(1, ch))
        if right > left and bottom > top:
            img = img.crop((left, top, right, bottom))
    return img
