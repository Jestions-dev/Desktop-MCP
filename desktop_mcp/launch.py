# -*- coding: utf-8 -*-
"""
启动应用 —— **兜底工具，默认关闭**

平时不需要它：`win+r` → 打名字 → 回车，这条路自然、agent 自己也能摸出来。
它存在的理由是那两条路都不成立的场合：

  · 要 URL 直达（`https://…` 交给默认浏览器，不用先开浏览器再输地址）
  · 要**确定的返回值**（新窗口的 hwnd / 标题 / 矩形），而不是启动完再猜是哪一个
  · 名字在开始菜单里而不是可执行文件（Windows 的 App Paths 能解析，PATH 不能）

默认关闭：设环境变量 `DESKTOP_MCP_ENABLE_LAUNCH=1` 才会出现在工具表里。
关着的时候它连 schema 都不占 —— 模型看不见，就不会去试。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Optional

from . import win32_window as W

APPROX_TIMEOUT = 10.0


def enabled() -> bool:
    """工具要不要露出来。默认不露。"""
    value = str(os.environ.get("DESKTOP_MCP_ENABLE_LAUNCH", "")).strip().lower()
    return value in ("1", "true", "yes", "on")


def _window_set(limit: int = 300) -> set[int]:
    try:
        return {w.hwnd for w in W.list_windows(only_titled=False, limit=limit)}
    except Exception:                           # noqa: BLE001
        return set()


def _open_url(target: str) -> str:
    try:
        os.startfile(target)                    # ShellExecute：默认浏览器
        return "os.startfile(URL)"
    except OSError:
        import webbrowser
        webbrowser.open(target)
        return "webbrowser.open(URL)"


def _open_path(target: str, args: list[str], cwd: Optional[str]) -> Optional[str]:
    """路径存在就直接跑，返回用的方式；不存在返回 None。"""
    if not os.path.exists(target):
        return None
    subprocess.Popen([target, *args], cwd=cwd, close_fds=True)
    return "Popen(路径)"


def _open_which(name: str, args: list[str], cwd: Optional[str]) -> Optional[str]:
    found = shutil.which(name)
    if not found:
        return None
    subprocess.Popen([found, *args], cwd=cwd, close_fds=True)
    return f"Popen({found})"


def _open_shell(name: str) -> Optional[str]:
    """
    交给 Windows 自己解析 —— App Paths（msedge / notepad / explorer）、
    开始菜单里的显示名、应用执行别名都走这条路。
    """
    try:
        os.startfile(name)
        return "ShellExecute(名字)"
    except OSError:
        pass
    try:
        subprocess.Popen(["cmd", "/c", "start", "", name], close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "cmd start(名字)"
    except Exception:                           # noqa: BLE001
        return None


def launch(target: str, args: Optional[list[str]] = None, cwd: Optional[str] = None,
           wait: float = APPROX_TIMEOUT, expect: Optional[str] = None) -> str:
    """
    启动一个应用 / URL，然后等一个新窗口出现并回报它。

    target 可以是：URL（http/https/file）、exe 绝对路径、PATH 里的命令名、
    或开始菜单里的应用名（"notepad"、"msedge"、"计算器"）。
    expect：标题关键词，用来在多个新窗口里挑对那个。
    """
    target = str(target or "").strip()
    if not target:
        raise ValueError("target 不能为空")
    args = [str(a) for a in (args or [])]

    before = _window_set()

    lowered = target.lower()
    how: Optional[str] = None
    if lowered.startswith(("http://", "https://", "file://", "www.")):
        how = _open_url(target)
    else:
        how = (_open_path(target, args, cwd)
               or _open_which(target, args, cwd)
               or _open_shell(target))
    if how is None:
        raise ValueError(f"启动失败：既不是 URL、也不是存在的路径或可解析的名字（{target!r}）")

    deadline = time.time() + max(1.0, float(wait or APPROX_TIMEOUT))
    fresh: list[Any] = []
    while time.time() < deadline:
        now = [w for w in (_find_windows() or []) if w.hwnd not in before]
        if expect:
            fresh = [w for w in now if expect.lower() in (w.title or "").lower()]
        else:
            fresh = now
        if fresh:
            break
        time.sleep(0.2)

    head = f"已启动 {target!r}（{how}）"
    if not fresh:
        others = _find_windows() or []
        recent = [w for w in others if w.hwnd not in before]
        if recent:
            lines = [f"  {w.describe()}" for w in recent[:4]]
            return head + "\n  出现了新窗口（但没匹配 expect）：\n" + "\n".join(lines)
        return head + f"\n  {wait:.0f}s 内没看到新窗口（有些程序复用已有窗口，用 desktop_list_windows 确认）"

    win = fresh[0]
    body = [head, "  新窗口：" + win.describe()]
    if len(fresh) > 1:
        body.append("  还有几个同时出现的：" + ", ".join(
            f"0x{w.hwnd:X} {(w.title or '')[:24]}" for w in fresh[1:5]))
    body.append("  下一步：desktop_uia_snapshot 抓它的控件树，或 desktop_screenshot 看一眼")
    return "\n".join(body)


def _find_windows():
    try:
        return W.list_windows(only_titled=False, limit=300)
    except Exception:                           # noqa: BLE001
        return []
