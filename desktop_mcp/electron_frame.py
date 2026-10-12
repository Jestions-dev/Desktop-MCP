# -*- coding: utf-8 -*-
"""
Electron 观察框的 Python 侧管理器

替换掉原来的 Tk 实现（overlay.py）。为什么换：
  · Tk 只有颜色键透明 → 柔和辉光被 Windows 与黑色预合成，变成一圈"黑色涂抹"
  · Tk 的 geometry() 在 DPI 缩放下会把窗口尺寸搞错（实测 830 → 553）
  · 采集排除/点击穿透要手写一堆 ctypes 扩展样式
Electron 版这三件事分别是 transparent:true、setBounds()、setContentProtection()、
setIgnoreMouseEvents() —— 各一行。

三条硬约束（全是实测踩出来的，别改）：
  1. spawn 时必须删掉环境变量 ELECTRON_RUN_AS_NODE。DSH 带着它运行，继承下去会让
     Electron 退化成纯 Node 模式，require('electron') 拿不到 API。
  2. frame/ 下必须有 node_modules（junction 指向一份 npm 装的 electron，Electron 的
     JS 包装需要它）。删了它 require('electron') 就找不到。
  3. 命令走**本地 HTTP**，不用 stdin —— Windows 上 Electron 读不到管道 stdin，
     会立刻 'end'，我们就会误判成父进程退出而自杀。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

FRAME_DIR = Path(__file__).resolve().parent.parent / "frame"

# 便携版运行时放在哪：跟 frame/ 同级（`<仓库根>/runtime/`），
# 也可以在 `runtime/` 里放个 runtime.json 指到别处（{"electron": "D:\\...\\electron.exe"}）。
# 这样分发出去别人放哪都行，不用改代码。
_RUNTIME_DIR = FRAME_DIR.parent / "runtime"


def _runtime_from_json() -> str:
    p = _RUNTIME_DIR / "runtime.json"
    try:
        import json as _json
        d = _json.loads(p.read_text(encoding="utf-8"))
        e = d.get("electron") or ""
        return e if e and Path(e).is_file() else ""
    except Exception:
        return ""


# Electron 可执行文件的候选位置，按优先级：
#   1. 环境变量 DESKTOP_MCP_ELECTRON（临时换引擎用）
#   2. 便携版：`<仓库根>/runtime/electron.exe`（**推荐** —— 自带 app，拷哪都能跑）
#   3. runtime.json 里指定的路径（把运行时放别处时用）
#   4. 几个常见位置（本机约定；别的机器上命中不了也无妨，会走 PATH）
#   5. 系统 PATH 里的 electron
#
# 便携版和"裸运行时"的区别：便携版把自己的 app 放在 `resources/app/` 里，
# 所以**不需要**启动参数、**不需要** node_modules；裸运行时得把 frame/ 当参数传。
_CANDIDATES = [
    os.environ.get("DESKTOP_MCP_ELECTRON", ""),
    str(_RUNTIME_DIR / "electron.exe"),
    _runtime_from_json(),
    # 本机约定：运行位置（~/.dsh）不一定带 runtime/，去项目区借一个
    r"D:\ForDeepseek\DesktopMCP\runtime\electron.exe",
    r"C:\Users\Jestions\.dsh\dsh-orb\electron-runtime\electron.exe",
    r"D:\ForClaude\ForFun\DesktopAi\node_modules\electron\dist\electron.exe",
]

_PORTABLE = str(_RUNTIME_DIR / "electron.exe")


def find_electron() -> Optional[str]:
    for c in _CANDIDATES:
        if c and Path(c).is_file():
            return c
    from shutil import which
    return which("electron")


def is_portable(exe: str) -> bool:
    """
    这个 exe 是不是自带 app 的便携版（是的话不用传 app 目录、不查 node_modules）。

    判据：它的**同级目录**里有 `resources/app/`（我们自己打进去的那个 app）。
    """
    try:
        e = Path(exe).resolve()
    except OSError:
        return False
    if (e.parent / "resources" / "app" / "main.js").is_file():
        return True
    return e == Path(_PORTABLE).resolve()


# ---------------------------------------------------------------- 孤儿进程
# 为什么需要这个：观察框是个**独立进程**，如果宿主（MCP 服务器、或某个调试脚本）
# 没走到 stop() 就退出了（异常、被杀、脚本自己崩），Electron 就成了孤儿 ——
# 它还会继续在屏幕上画框。实测踩过：一堆诊断脚本崩在 stop() 之前，
# 桌上留了 3 个叠在一起的框，看起来像"屏幕上有块青色的污渍"。
# 办法：启动时把上次记下的 PID 收掉。
_PID_FILE = Path(__file__).resolve().parent.parent / ".frame.pid"


def _write_pid(pid: int) -> None:
    try:
        _PID_FILE.write_text(str(int(pid)), encoding="utf-8")
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        _PID_FILE.unlink()
    except OSError:
        pass


def kill_orphan(verbose: bool = False) -> Optional[int]:
    """收掉上次遗留的观察框进程（如果还在）。返回被结束的 PID。"""
    try:
        pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    alive = False
    try:
        # Windows 上 os.kill(pid, 0) 不可靠，用 OpenProcess 探活
        import ctypes
        PROCESS_TERMINATE = 0x0001
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            alive = True
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        alive = False
    if alive:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
            if verbose:
                print(f"[desktop-mcp] 清掉遗留的观察框进程 PID {pid}", file=sys.stderr)
        except Exception:
            pass
    _clear_pid()
    return pid if alive else None


class ElectronFrame:
    """
    一个常驻的 Electron 子进程，负责画观察框。

    生命周期：start() 起进程 → show_region()/hide() 发指令 → stop() 收掉
    （用户在 MCP 那边可以随时开关它，就像浏览器 MCP 的浏览器一样）
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._port = 0
        self._hwnd = 0
        self._ready = threading.Event()
        self._errors: list[str] = []
        self._logs: list[str] = []
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None

    # ---------------- 进程
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def port(self) -> int:
        return self._port

    def start(self, timeout: float = 25.0) -> bool:
        if self.running:
            return True
        exe = find_electron()
        if not exe:
            self._errors.append("找不到 electron.exe（可用 DESKTOP_MCP_ELECTRON 指定）")
            return False

        portable = is_portable(exe)
        if portable:
            # 便携版：app 在它自己的 resources/app/ 里，直接启动即可
            cmd = [exe]
            cwd = str(Path(exe).parent)
        else:
            # 裸运行时：得把 app 目录当参数传，并且需要它的 node_modules
            # （Electron 的 JS 包装在那份 npm 包里；便携版不需要，因为它把
            #   app 装进了 resources/app/，走的是另一条加载路径）
            if not (FRAME_DIR / "node_modules").exists():
                self._errors.append(
                    f"{FRAME_DIR}\\node_modules 不存在 —— 用裸运行时需要它。"
                    f"建法：mklink /J \"{FRAME_DIR}\\node_modules\" "
                    f"\"D:\\ForClaude\\ForFun\\DesktopAi\\node_modules\""
                    f"（或者改用便携版 {_PORTABLE}，那份不需要）")
            cmd = [exe, str(FRAME_DIR)]
            cwd = str(FRAME_DIR)

        # ⚠ 约束 1：必须去掉这个标记，否则 Electron 退化成 Node 模式
        env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}

        try:
            self._proc = subprocess.Popen(
                cmd,
                env=env, cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self._errors.append(f"启动 Electron 失败：{type(e).__name__}: {e}")
            return False

        self._ready.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name="electron-frame-reader")
        self._reader.start()
        _write_pid(self._proc.pid)          # 记下 PID，供下次启动时清孤儿用

        if not self._ready.wait(timeout):
            self._errors.append(
                f"等 ready 超时（{timeout}s）。stderr 末尾：" + " | ".join(self._logs[-3:]))
            self.stop()
            return False
        return True

    def _read_loop(self) -> None:
        """读 Electron 的 stdout（NDJSON 事件）；stderr 当日志留一份"""
        proc = self._proc
        if proc is None:
            return

        def pump_err() -> None:
            try:
                for line in proc.stderr:                      # type: ignore[union-attr]
                    line = (line or "").strip()
                    if line and "disk_cache" not in line:
                        self._logs.append(line)
                        if len(self._logs) > 40:
                            del self._logs[:20]
            except Exception:
                pass

        threading.Thread(target=pump_err, daemon=True, name="electron-frame-stderr").start()

        try:
            for line in proc.stdout:                          # type: ignore[union-attr]
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev = msg.get("event")
                if ev == "ready":
                    self._hwnd = int(msg.get("hwnd") or 0)
                elif ev == "listening":
                    self._port = int(msg.get("port") or 0)
                    # 只要命令通道通了就算就绪 —— 不再等 hwnd：
                    # 实测 did-finish-load 有时不触发（窗口还没画完），
                    # 若把 hwnd 也算进就绪条件就会白等到超时。hwnd 后来会补上。
                    if self._port:
                        self._hwnd = self._hwnd or int(msg.get("hwnd") or 0)
                        self._ready.set()
                elif ev == "shown":
                    # show 的回包带 hwnd，正好补上
                    if msg.get("hwnd"):
                        self._hwnd = int(msg["hwnd"])
                elif ev == "error":
                    self._errors.append(str(msg.get("message"))[:300])
        except Exception:
            pass

    def stop(self, timeout: float = 5.0) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            self._post({"cmd": "quit"})          # 优雅退出
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        _clear_pid()
        self._port = 0
        self._hwnd = 0
        self._ready.clear()

    # ---------------- 指令
    def _post(self, payload: dict) -> dict:
        if not self._port:
            raise RuntimeError("命令通道还没就绪")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/", data=data,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def show_region(self, x: int, y: int, w: int, h: int) -> dict:
        res = self._post({"cmd": "show", "x": int(x), "y": int(y),
                          "w": int(w), "h": int(h)})
        self._last_reply = res
        return res

    def hide(self) -> dict:
        res = self._post({"cmd": "hide"})
        self._last_reply = res
        return res

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def logs(self) -> list[str]:
        return list(self._logs)

    def describe(self) -> str:
        if not self.running:
            return "未运行"
        return f"运行中（PID {self._proc.pid if self._proc else '?'}，hwnd={self._hwnd}，端口 {self._port}）"


# ---------------------------------------------------------------- 进程内单例
_frame: Optional[ElectronFrame] = None
_frame_lock = threading.Lock()


def get_frame() -> Optional[ElectronFrame]:
    """拿到当前框（没启动就返回 None）；配合 start_frame() 用"""
    return _frame


def start_frame() -> ElectronFrame:
    """启动（或复用）观察框进程"""
    global _frame
    with _frame_lock:
        if _frame is not None and _frame.running:
            return _frame
        f = ElectronFrame()
        if not f.start():
            _frame = f            # 留着，好让调用方读 errors
            raise RuntimeError("观察框启动失败：" + "；".join(f.errors[-2:]))
        _frame = f
        return f


def stop_frame() -> bool:
    """收掉观察框进程。返回是否真的停了一个"""
    global _frame
    with _frame_lock:
        if _frame is None:
            return False
        was = _frame.running
        _frame.stop()
        _frame = None
        return was
