# dsh-desktop-mcp

**先说明白它是什么**：本体是一个**标准 MCP 服务器**（[`desktop-mcp`](https://github.com/Jestions-dev/Desktop-MCP)），
任何 MCP 客户端都能直接用 —— Claude Desktop / Code、Cursor、以及 DSH。
本仓库这个 npm 包只是一个**配置型外壳**：不含业务代码，只负责把那台服务器挂进 DSH。

所以下面分两条路：**先讲通用 MCP，再讲 DSH 插件**。两条路装的是同一套引擎、同一批工具。

---

## 一、通用 MCP（任何客户端）

### 前置条件

```
系统      Windows（Win32 API + UIA，其他平台跑不了）
Python    3.10+，命令名 python 在 PATH 里
依赖      pip install mss pillow uiautomation
本体      pip install git+https://github.com/Jestions-dev/Desktop-MCP
```

验证（任意目录）：

```sh
python -m desktop_mcp.server
```

打印下面这行就成了，`Ctrl+C` 退出：

```
[desktop-mcp] v1.2.0 就绪（24 个工具）；观察框：按需启动（Electron 子进程）
```

### 接入客户端

任何支持 stdio 的 MCP 客户端，配置都长这样：

```json
{
  "mcpServers": {
    "desktop": {
      "command": "python",
      "args": ["-m", "desktop_mcp.server"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

- Claude Desktop 放 `claude_desktop_config.json`；Claude Code 用 `claude mcp add` 或 `~/.claude.json`
- `PYTHONIOENCODING` 别省 —— 默认 GBK 时 `tools/list` 会在「⚠」这类字符上崩
- 想用别的解释器就写绝对路径；**Windows 上建议用 `"command": "C:/Python313/python.exe"` 这种正斜杠写法**

---

## 二、DSH（插件版）

DSH 的内置 MCP 客户端只支持 stdio，所以插件壳走的是「启动一个 python 子进程」这条路。

```sh
dsh plugin --profile <你的 profile> add dsh-desktop-mcp
```

`<profile>`：`dsh web` 用 `web`，桌面应用用 `desktop`。装完**重启 DSH** —— 运行中的进程持有内存里的旧插件树。

### 缺依赖不会报错，只会静默没有工具

插件里 `failOnStartupError: false`：python 起不来、或者缺 `mss` / `pillow` / `uiautomation`
时，**DSH 照常启动，只是 `desktop_` 那些工具一个都不出现**。所以工具不见了先跑一次
`python -m desktop_mcp.server` 看真实报错，别在插件配置里找。

### 想换解释器 / 加参数

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

---

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
