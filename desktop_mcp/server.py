# -*- coding: utf-8 -*-
"""
desktop-mcp —— 纯桌面操作 MCP 服务器（Windows，纯标准库 + mss/Pillow）

定位（用户 2026-10-12 定）：**纯工具，不做软件**。
没有悬浮球、没有内置对话页、没有桌宠 —— 一切通过 MCP 被 agent 调用。

一眼看全：
    initialize / tools/list / tools/call / ping
    工具 13 个：screenshot click type_text press_keys move_mouse drag scroll
                list_windows get_foreground_window focus_window measure_window
                wait highlight
    screenshot 类工具返回 **MCP image content**，模型能直接看见屏幕。

启动：
    python -m desktop_mcp.server                     # 无框（默认，最轻）
    python -m desktop_mcp.server --show-frame        # 启用观察框（highlight 工具可用）

协议：JSON-RPC 2.0 over stdio，单行消息（与 music-mcp 同约定）
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

__version__ = "1.0.2"     # 1.0.1: 修 SendInput argtypes / 布局 / 绝对定位 / DPI 坐标
SERVER_NAME = "desktop-mcp"

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]


# ---------------------------------------------------------------- 启动参数
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="desktop-mcp",
        description="桌面操作 MCP 服务器（Windows，stdio）。")
    # 观察框现在是按需启动的独立 Electron 子进程，由 desktop_highlight 自动拉起，
    # 所以**不再需要任何启动参数** —— 这两个是 Tk 时代留下的，已废弃。
    # 保留为"静默接受但不做任何事"，免得旧配置里的 --show-frame 触发 argparse
    # 直接退出（那样表现为"工具全部消失"，极难查）。
    p.add_argument("--show-frame", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--frame-exclude-capture", action="store_true", default=True,
                   help=argparse.SUPPRESS)
    return p.parse_args(argv)


# ---------------------------------------------------------------- 基础
def write_msg(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(rid, result):
    write_msg({"jsonrpc": "2.0", "id": rid, "result": result})


def err(rid, code: int, message: str):
    write_msg({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def notify(method: str, params: dict | None = None) -> None:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    write_msg(msg)


# ---------------------------------------------------------------- 观察框
# 观察框现在由**独立的 Electron 子进程**渲染（见 electron_frame.py），
# 不再在本进程里建 Tk 窗口。它的生命周期由工具管理：
#   desktop_highlight    首次调用自动起
#   desktop_frame_start  显式起
#   desktop_frame_stop   收掉
# 所以启动时不需要做任何事 —— 想省资源就永远不碰 highlight。

def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from . import tools as T
    from . import electron_frame as EF

    # 收掉上次遗留的观察框（宿主异常退出时它会变成孤儿，继续在屏幕上画框）
    orphan = EF.kill_orphan()
    if orphan:
        print(f"[desktop-mcp] 清掉遗留的观察框进程 PID {orphan}", file=sys.stderr, flush=True)

    print(f"[desktop-mcp] v{__version__} 就绪（{len(T.list_tools())} 个工具）；"
          f"观察框：按需启动（Electron 子进程）", file=sys.stderr, flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # 规范：解析失败回 -32700。没有 id 就只能丢弃。
            continue

        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        is_notification = rid is None

        try:
            if method == "initialize":
                asked = str(params.get("protocolVersion") or "")
                ver = asked if asked in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
                ok(rid, {
                    "protocolVersion": ver,
                    "capabilities": {
                        "tools": {"listChanged": True},
                        # 本服务器不暴露 resources（纯工具），所以不声明该能力
                    },
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                })

            elif method in ("notifications/initialized", "initialized"):
                notify("notifications/tools/list_changed")
                continue

            elif method == "tools/list":
                ok(rid, {"tools": T.list_tools()})

            elif method == "tools/call":
                name = params.get("name", "")
                targs = params.get("arguments") or {}
                text, is_err, images = T.call_tool_ex(name, targs)
                content: list[dict] = [{"type": "text", "text": text}]
                for png in images:
                    content.append({
                        "type": "image",
                        "data": base64.b64encode(png).decode("ascii"),
                        "mimeType": "image/png",
                    })
                result = {"content": content}
                if is_err:
                    result["isError"] = True
                ok(rid, result)

            elif method == "ping":
                ok(rid, {})

            else:
                if not is_notification:
                    err(rid, -32601, "Method not found")

        except Exception as e:      # 内部异常回成 JSON-RPC 错误，别让服务器死掉
            if not is_notification:
                err(rid, -32603, f"{type(e).__name__}: {e}")

    # 退出前收掉观察框：它是独立进程，不清会留在屏幕上继续画框
    # （这里用 try 兜底 —— 哪怕 stop 抛异常也不能挡住退出）
    try:
        EF.stop_frame()
    except Exception:
        pass
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
