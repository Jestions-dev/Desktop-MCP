# -*- coding: utf-8 -*-
"""
desktop-mcp —— 给 agent 用的桌面操作工具（Windows）

设计定位：**纯工具，不做软件**。
没有悬浮球、没有内置对话页、没有桌宠 —— 全部能力通过 MCP 暴露，由宿主 agent 驱动。

模块：
    win32_input.py     SendInput / 键盘鼠标注入（ctypes，零依赖）
    win32_window.py    窗口枚举 / 激活 / 度量
    screen.py          mss 截屏 + PrintWindow 窗口截图 + 缩放
    electron_frame.py  观察框：管理那个渲染它的 Electron 子进程
    tools.py           16 个工具的实现与注册表
    server.py          JSON-RPC over stdio（含 image content 返回）

观察框的渲染代码在 ../frame/（Electron 主进程 + HTML/CSS），不在这里 ——
Python 侧只负责起进程、发指令、收进程。

    overlay.py         已退休的 Tk 实现，仅作参考、不被引用
                       （Tk 只有颜色键透明，辉光会被预合成成黑色；且 geometry
                        受 DPI 缩放影响，实测要 830×530 得到 553×353）
"""

__version__ = "1.0.2"
__all__ = ["server", "tools", "screen", "electron_frame",
           "win32_input", "win32_window"]
