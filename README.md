# desktop-mcp

给 agent 用的**桌面操作** MCP 服务器（Windows）。看屏幕、点鼠标、敲键盘、管窗口。

**纯工具，不做软件** —— 没有悬浮球、没有内置对话页、没有桌宠。
一切能力通过 MCP 暴露，由宿主 agent（DSH / Claude Code / Cursor…）驱动。

```
agent ──stdio JSON-RPC──▶ desktop-mcp ──SendInput/PrintWindow──▶ 你的屏幕
                                     ├─MCP image content──────▶ 截图回到模型眼里
                                     └─本地 HTTP──▶ Electron 子进程 ──▶ 屏幕上的发光框
```

---

## 快速开始

```bash
# 直接跑（无需安装）
python -m desktop_mcp.server                  # 全部 16 个工具
```

观察框（`desktop_highlight`）**不用预先启用**：首次调用会自动拉起 Electron 渲染进程，
常驻到你用 `desktop_frame_stop` 收掉它为止 —— 想省资源就收，下次用时再自动起。

### 挂到 DSH

```yaml
# ~/.dsh/profiles/<profile>/cordis.patch.yml
- id: mcp-desktop
  name: "@deepseek-ai/dsh-mcp-client"
  config:
    serverName: desktop
    transport: stdio
    command: "C:/Python314/python.exe"
    args: ["-m", "desktop_mcp.server", "--show-frame"]
    cwd: "C:/Users/<你>/.dsh/desktop-mcp"
    env: { PYTHONIOENCODING: "utf-8" }
```

### 依赖

只用两个已经装好的库，**没有引入任何新依赖**：

| 用途 | 用什么 |
|---|---|
| 输入注入（鼠标/键盘） | `ctypes` 直调 `SendInput`（标准库） |
| 窗口枚举/激活/度量 | `ctypes` 直调 `EnumWindows` / `SetForegroundWindow`（标准库） |
| 截屏 | `mss` |
| 图像编码与缩略 | `Pillow` |
| 观察框窗口 | `tkinter`（标准库，仅 `--show-frame` 时用到） |

---

## 工具（17 个）

**全部带 `desktop_` 前缀** —— 裸名（`click`、`wait`）在客户端省略命名空间时无法自解释，
也容易和别的 MCP 服务器的同名工具混淆。这和 Playwright MCP 用 `browser_click` 是同一个理由。

### 看

| 工具 | 说明 |
|---|---|
| `desktop_screenshot` | **默认截当前前台窗口**。返回 MCP image content，模型直接看见 |
| `desktop_foreground_window` | 前台是哪个窗口 + 截屏 |
| `desktop_list_windows` | 枚举可见窗口（前台排最前），可按标题/进程名查 |
| `desktop_measure_window` | 量窗口：整窗/客户区矩形，**并直接给出 0–1000 分数坐标** |

### 动

| 工具 | 说明 |
|---|---|
| `desktop_click` | 左/右/中键，支持连击；完成后自动截屏 |
| `desktop_type` | 输入文字，**支持中文**；`method="clipboard"` 走剪贴板粘贴 |
| `desktop_press` | 组合键，如 `"ctrl+s"`、`["ctrl","shift","esc"]` |
| `desktop_move` | 只移动，不点击 |
| `desktop_drag` | 分步拖动，能触发画布/滑块的中间事件 |
| `desktop_scroll` | 滚轮，一格 = 120 |

### 控制流

| 工具 | 说明 |
|---|---|
| `desktop_focus_window` | 定位窗口后做动作：`activate`（默认，切前台、最小化的会自动还原）、`maximize`、`minimize`、`restore`。切前台含 `AttachThreadInput` 绕前台锁定 |
| `desktop_wait` | 等界面加载/动画结束，可选截屏确认（**固定等待**；要"等条件成立"用 `list_windows` 轮询） |
| `desktop_highlight` | 在屏幕上画发光框标出位置（给人看的）；`hide=true` 收起 |
| `desktop_frame_start` | 启动观察框渲染进程（常驻）。平时不用手动调，highlight 会自动起 |
| `desktop_frame_stop` | 收掉渲染进程、释放那个 Electron 子进程（省资源） |
| `desktop_frame_status` | 看渲染进程状态：在不在跑、hwnd、命令端口、报错。框画不出来先查这个 |

### 坐标系（唯一的真相）

- 位置一律是**全屏物理像素**，原点在主屏左上角；多屏在左侧时 x 可为负
- 也接受 **0–1000 分数**（`fx`/`fy`），按整个虚拟桌面换算 ——
  只看缩略图也能估位置，不必知道真实分辨率
- 进程启动时设 **per-monitor-v2 DPI 感知**，所以坐标就是物理像素，
  不会在 125%/150% 缩放的屏幕上偏移

---

## screenshot 为什么默认截窗口

用 `PrintWindow(PW_RENDERFULLCONTENT)`：让**窗口自己重绘**到内存 DC。

好处是普通抓屏做不到的：

- 窗口**被别的窗口挡住**，照样拿到完整内容
- 窗口**一部分在屏幕外**，照样拿到
- 拿到的就是"这个程序画的界面"，不掺杂桌面和其他窗口

`window=false` 或 `monitor=n` 时退化为屏幕抓取。

---

## 两个已知边界（不是 bug，别当 bug 查）

### 1. 最小化窗口只能截到标题栏一条

Windows 对最小化窗口没有"离屏渲染缓冲"，`PrintWindow` 只能给出一条标题栏
（实测：237×39、灰度标准差 0.0）。**工具会明确警告**，并提示先
`focus_window` 还原再截图 —— 因为不警告的话，模型会误判成"窗口里什么都没有"，
然后去点一堆不存在的控件。

### 2. 不渲染到屏幕的内容，任何 GDI 抓屏都拿不到

硬件加速浮层（某些加密视频、部分 GPU 合成的 UI 元素）不属于窗口绘制内容，
`PrintWindow` 和普通抓屏**都**拿不到。要抓这类内容只有
`Windows.Graphics.Capture` 那条路（本工具没做）。

> 踩过的坑记一笔：曾经看到微信头像区是空白方块，误判成"GPU 合成抓不到"。
> 真相是**头像还在加载**（占位底色），第二次截就有了。
> **先怀疑"它本来就没画"，再怀疑采集方式。**

---

## 观察框：为什么现在用 Electron

`desktop_highlight` 在屏幕上画一个青紫渐变 + 柔光的边框，标出 agent 正在看的位置。
**渲染交给一个独立的 Electron 子进程**（`frame/`），Python 侧通过本地 HTTP 发指令。

一开始我是用 tkinter 写的（`overlay.py` 保留作参考，但已不再被引用）。换掉它是因为
三件**在 Tk 里根本解决不了**的事：

| 需求 | Tk | Electron |
|---|---|---|
| 柔和辉光 | **做不到** —— Tk 只有颜色键透明，半透明像素被 Windows 与**黑色**预合成，辉光变成一圈"黑色涂抹"（用户原话：很重的黑色发散） | `transparent: true` 是真·逐像素 alpha，CSS `drop-shadow` 直接可用 |
| 精确位置 | `geometry()` 受 DPI 缩放影响：要 830×530 实际得到 553×353；还出现过 Tk 自认已设好、Win32 侧仍停在 `0x0` | `setBounds()` 直接设原生窗口，实测误差 **0** |
| 采集排除 | 手写 ctypes 设 `WDA_EXCLUDEFROMCAPTURE` | `setContentProtection(true)` 一行 |
| 点击穿透 | 手写一堆 `WS_EX_*` 扩展样式 | `setIgnoreMouseEvents(true, {forward:true})` 一行 |

### 两个必须遵守的启动条件（全是实测踩出来的）

1. **spawn 时必须删掉环境变量 `ELECTRON_RUN_AS_NODE`。**
   DSH 自己带着它运行，继承下去会让 Electron **退化成纯 Node 模式** ——
   `require('electron')` 只拿到一个字符串路径，`app` / `BrowserWindow` 全是 undefined。
   这条是从 dsh-orb 的 `open-main.ts` 注释里读出来的，省了大量试错。
2. **命令走本地 HTTP，不要用 stdin。** Windows 上 Electron 读不到管道 stdin，
   会立刻触发 `end`，于是我们把"父进程还没说话"误判成"父进程走了"而自杀。
   现在：Electron 监听 `127.0.0.1` 的**随机端口**并报给 Python，Python POST 指令过去。

> 还有一条**曾经**是硬性要求、现在已经被便携版消掉的：`frame/node_modules` 必须指向
> 一份 npm 装的 electron。那只是因为"裸运行时 + Node 模式"才需要它 —— 换成便携版
> （app 装在运行时自己的 `resources/app/` 里）之后就不需要了。见下一节。

### 便携版：渲染引擎怎么打包

观察框需要 Electron。为了不必在目标机器上装 node 环境，**把官方运行时和我们的
app 打在一起**，得到一个自包含、可直接拷走的目录：

```
runtime/                          365 MB（不进版本库）
├── electron.exe                  官方 Electron 44（Chromium + Node + V8）
├── *.dll / *.pak / locales/...   它自带的依赖，照抄
└── resources/app/                ← 我们的 4 个文件（共 9.6 KB）
    ├── main.js                   主进程：开窗、setBounds、命令通道
    ├── index.html
    ├── frame.css                 渐变描边 + 四层 drop-shadow 辉光
    └── package.json              main: main.js
```

**关键点**：Electron 启动时会自动加载 `resources/app/` 里的 app，
所以**不需要传任何参数、也不需要 node_modules**。
（同时要删掉官方的 `resources/default_app.asar`，否则它可能抢先加载。）

`desktop_mcp/electron_frame.py` 按这个顺序找引擎，找到哪个用哪个：

1. 环境变量 `DESKTOP_MCP_ELECTRON`（临时换引擎）
2. `D:\ForDeepseek\DesktopMCP\runtime\electron.exe` ← **便携版，推荐**
3. dsh-orb 自带的运行时（裸二进制，要配 `frame/node_modules`）
4. DesktopAi 里 npm 装的那份（同上）

**体积是 Electron 的固有代价**（自带一整个浏览器内核），压不下去。要重建便携版：

```cmd
python tools\build_portable.py
```
（脚本会复制运行时、放入 app、删掉 default_app、并实测能否起来+画框。）

### 另一个隐蔽的时序坑

`hwnd` 原来只在 `did-finish-load` 之后才报给 Python。结果首次 `highlight` 时，
Python 一拿到"就绪"就立刻发 `show`，而那时**页面还没加载完、窗口没准备好** ——
HTTP 回包是 `{"ok":true}`，但**屏幕上一片空白**，非常难查。

修法：**窗口一创建就报 hwnd**（不等页面加载），Python 拿到端口即算就绪。

### 与 dsh-orb 的关系

观察框的**设计**借鉴自 [dsh-orb](https://github.com/mini-yifan/dsh-orb-cordis)（MIT，★217）：
透明分层窗口、采集排除、点击穿透、以及"外扩 stroke+glow 再夹到工作区"的几何算法。
代码是独立写的（Python + 自己的 Electron 主进程）。
作者源码副本放在项目文件夹 `D:\ForDeepseek\DesktopMCP\参考_dsh-orb\`，只作参考。

> 顺带记一笔 Tk 时代的教训，免得以后重犯：那个 `_to_color_keyed()` 的阈值不能取大
> （取 8 会把光晕最外围 alpha 只有 8~20 的那圈整片削平）；而且转换后 alpha 已烘进颜色，
> **在深色背景下看会误以为"光晕没了"**，判断真实强度要看原始 alpha 通道 —— 我在这上面被自己误导了两轮。

---

## 人味点击：`desktop_click_human`

`desktop_click` 是"起点 → 终点"一步到位，任何行为分析一眼就看得出不是人手。
**人手的移动有三个特征，一条直线给不出来**：

- 轻微过冲后回调（overshoot → correct）
- 速度剖面不对称：起步加速、中段峰值、**末端明显减速**
- 微小抖动与不精确的落点

`desktop_click_human` 用**真人录制的轨迹**走完这段路再点击。轨迹由独立工具
`tools/record_trajectory.py` 采集（真人在窗口里按住鼠标朝按钮拖、松开），
**MCP 服务器不含录制功能** —— 它只读、只放。

### 数据格式

每个点存 `[相对x, 相对y, 毫秒]`（相对**松手处**的偏移），所以回放时能按目标
距离缩放、绕终点旋转，**路径形状和速度剖面都保留**。一条典型的：

```json
{"points": [[462,-343,0], [461,-343,8], ...],
 "n": 228, "duration_ms": 2096, "straight_dist": 575.4,
 "end_screen_xy": [1053,1012],
 "cursor_check": {"tk_release":[1053,1012], "win32_cursor":[1052,1011], "delta":[-1,-1]}}
```

`cursor_check` 是录制时的**坐标交叉校验**：Tk 报的松手位置 vs Win32 的光标位置。
两者一致才说明录到的是物理像素（实测全部 ≤1px）。

**纯净度**：录的是 `B1-Motion`（按住拖行），**中途不产生任何点击**，
数据里也没有任何按键事件字段；回放时走完全部点**才发一次按下+抬起**。
`tools/check_purity.py` 用三重证据（字段、时间轴空档、路径跳变）验证这一点。

### 按方向挑轨迹：为什么四象限都要录

回放时会**优先挑原生方向接近目标的轨迹**（cos 相似度前 4 条里随机 80%，
另 20% 完全随机以保留变化）。这不是优化，是**必要的**——实测两种发力的
手部特征完全不同：

| 指标 | 拉（朝左下） | 推（朝右上） | 差异 |
|---|---|---|---|
| 平均采样点数 | 116 | 63 | 0.54× |
| 平均时长 | 983 ms | 565 ms | **0.57×** |
| 平均峰值速度 | 1984 px/s | 3512 px/s | **1.77×** |
| 收尾/峰值比 | 0.30 | 0.10 | 收得更急 |

速度剖面的形状也不一样：**"推"起步最猛然后一路衰减**（像弹出去），
**"拉"速度平稳、尾部缓收**（像稳稳拖过来）。

**旋转能保住路径形状，但保不住速度剖面** —— 把"推"的节奏用在"拉"的方向上
就不像人了。所以四个象限各录一组，让旋转角接近 0。

### 节奏也要有变化，而且**时长随距离缩放**

`time_jitter`（默认 ±15%）给每段间隔加随机扰动。**时间也是行为特征**：
严格照原时间戳的话，同一个目标点两次的节奏会一模一样 —— 路径有抖动、时间
没有，一样可疑。

更重要的：**时间轴会跟着路径一起缩放**（`plan_path(scale_time=True)`）。
这是量出来的，不是猜的 —— 28 条真人轨迹里：

```
「时长 vs 直线距离」   r = +0.38   ← 弱
「时长 vs 路径长度」   r = +0.86   ← 强
按距离分组平均速度：近 981 / 中 1006 / 远 916 px/s   ← 基本恒定
```

也就是 **人手的速度大致是个常数，时长 = 路程 ÷ 速度**。不缩放的话，
把一条 559px 的轨迹拉去走 2084px，时长仍是原值（速度降到 1/3.7）；
拿去走 100px 时更荒谬 —— 3.2 秒挪 100 像素。

> **一个测量陷阱，别重犯**：不要用"速度守恒"去验证这件事。轨迹的**绕路比
> 不是常数**（实测某条：录制时 1.10，缩放到 640px 后 1.57），拿
> `路径长度 ÷ 时长` 算出来的"速度"会虚报几十个百分点，得出一堆假警报。
> 正确判据是 **回放时间/录制时间 == 目标直线距离/录制直线距离**
> （`tools/check_speed_preserve.py` 测 112 组，最大误差 1.02%）。

---

## 协议合规（34 项检查全过）

用 `tools/check_protocol.py` 跑出来的结论。**其中两条最容易做错，值得单独说**：

**① `image` content 必须是独立项，不能把 base64 塞进 `text`。**
塞进 text 的话客户端不会渲染成图，模型就"看不见"屏幕了 —— 工具照样报成功。

```json
{"type": "content", "content": [
  {"type": "text",  "text": "屏幕：虚拟桌面 (0,0) 2560×1600 ..."},
  {"type": "image", "data": "<base64>", "mimeType": "image/png"}
]}
```

**② 工具执行失败要用 `result.isError: true`，不能用 JSON-RPC error。**
用协议层 error 的话客户端会当成**协议故障**（可能断连或重试）；
规范要求 `isError` 是为了让模型知道"工具跑了但没成功"，可以换个方式再试。

检查覆盖面：

| 域 | 内容 |
|---|---|
| 生命周期 | `jsonrpc`/`id` 回传、版本协商（旧版回显、未知版本回最新）、能力声明、`serverInfo` |
| 通知 | 服务器主动发的 `list_changed` 不占响应位（客户端必须按 id 匹配响应，不能"读一行当响应"） |
| `tools/list` | 16 个工具、名字唯一、全带前缀、每项有 description 与 object schema |
| 成功路径 | `result.content` 数组、每项有 `type`、**不带** `isError` |
| `image` | `mimeType`/base64 合法性/无多余字段/图文共存/没塞进 text |
| 失败语义 | 未知工具、参数类型错、业务失败（找不到窗口）→ 全是 `result.isError`，且**没有** JSON-RPC error |
| 协议错误 | 未知方法 → `-32601`，error 含 code+message，且**不带** result |
| 健壮性 | 喂一行坏 JSON，服务器继续服务 |

启动参数：**不需要任何参数**。观察框按需启动，`desktop_highlight` 首次调用会自动拉起。
（`--show-frame` 等旧参数仍被静默接受，但已不做任何事 —— 保留只是为了旧配置不会因
argparse 报错而"工具全部消失"。）

---

## 安全说明

这个服务器**真的会操作你的电脑**：点击、输入、按键都会作用到真实窗口上。

- 它不做任何网络请求，不读凭据，不写项目外的文件
- 输入注入走 `SendInput`，和真实硬件事件同级 —— 操作系统不区分它们
- 它**主动拒绝**系统截图快捷键（`Win+Shift+S` 等）的组合键注入，
  避免误触系统 UI（这个保护借鉴自 dsh-orb）
- 观察框窗口是点击穿透的，不会挡住你自己的操作
- 装不装、什么时候装，由你决定；不想用时把 DSH 里那条配置删掉即可

## 许可

MIT
