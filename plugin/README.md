# dsh-desktop-mcp

给 **DeepSeek Harness** 用的 Windows 桌面自动化：截屏、Win32 输入、窗口控制，
外加一条 **UIA 无障碍树**的路 —— 按控件点名操作，不用看图猜坐标。

这个包本身是一个**壳（配置型 bundle）**：它不含任何业务代码，只负责把
[`desktop-mcp`](https://github.com/Jestions-dev/Desktop-MCP) 这个 **标准 MCP 服务器**
挂进 DSH；工具由那边提供，协议是 MCP，所以同一套引擎 Claude Desktop / Code、Cursor 也能用。

## 装之前

目标机器上要有 **Python 3.10+**（命令名 `python` 在 PATH 里），然后：

```sh
pip install mss pillow uiautomation
pip install git+https://github.com/Jestions-dev/Desktop-MCP
```

验证一下（任意目录）：

```sh
python -m desktop_mcp.server
```

打印 `[desktop-mcp] v1.1.0 就绪（24 个工具）` 就成了，`Ctrl+C` 退出。

## 装插件

```sh
dsh plugin --profile <你的 profile> add dsh-desktop-mcp
```

`<profile>`：`dsh web` 用 `web`，桌面应用用 `desktop`。

装完**重启 DSH**——运行中的进程持有内存里的旧插件树。

## 想换解释器 / 加参数

**覆盖 bundle 里的行，直接写同 id 的行 —— 不要用 `insert`。**

```yaml
# ~/.dsh/profiles/<profile>/cordis.patch.yml
- id: desktop-mcp-bridge
  config:
    command: 'C:/Python313/python.exe'
    args: ['-m', 'desktop_mcp.server']
    env:
      PYTHONIOENCODING: 'utf-8'
```

patch 对同 id 是**整块替换 config**；写成 `insert:` 会再插一行，结果同一个 id 出现两次
（实测踩过：dump 出来两份，MCP 服务器被拉起两个）。

## 装完看到什么

工具表里多出 `desktop_` 开头的一批（serverName 是 `desktop`）：

```
看      desktop_foreground_window  desktop_list_windows  desktop_screenshot
        desktop_measure_window     desktop_uia_snapshot  desktop_monitors
动      desktop_click  desktop_move  desktop_drag  desktop_scroll
        desktop_type   desktop_press desktop_click_human
按控件  desktop_uia_click  desktop_uia_set_value  desktop_uia_focus  desktop_uia_wait_for
窗口    desktop_focus_window
观察框  desktop_highlight  desktop_frame_start/stop/status
杂项    desktop_wait  desktop_clipboard  desktop_launch（默认隐藏）
```

## 两条路，别用混

```
坐标路（截图 + 像素）      什么都看得见，但要眼睛估位置，窗口一动就得重看
控件路（UIA 树 + 索引）    纯文本、精确、不动鼠标，
                          但 Electron / Chromium（DSH 自己、VSCode、浏览器）
                          常常只给窗框几个按钮 —— 那种窗口继续用截图
```

完整用法见主仓库的 [README](https://github.com/Jestions-dev/Desktop-MCP#readme)。

## 出问题先看这两处

```
工具一个都没出现    python -m desktop_mcp.server 手动跑一下，看是不是缺依赖
                    （缺依赖不会拖垮 DSH：failOnStartupError 是关的）
点不动 / 坐标偏     DPI 缩放。desktop_measure_window 能给分数坐标，比肉眼估准
```

## 许可

MIT
