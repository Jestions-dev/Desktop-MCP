# 第三方组件与致谢

本项目（Desktop-MCP）本体以 **MIT 许可证**发布，见 [LICENSE](LICENSE)。
以下是它用到或借鉴的第三方内容。

---

## Electron（观察框的渲染引擎）

`frame/` 是一个 Electron 应用，渲染屏幕上那个发光边框。
`runtime/`（**不进版本库**，按 README 用 `tools/build_portable.py` 生成）
内含 Electron 官方二进制及其自带的 Chromium / Node.js。

- **Electron** — MIT License — <https://github.com/electron/electron>
- **Chromium** — BSD 3-Clause 及若干其它许可证
- **Node.js** — MIT License

完整的许可证文本在运行时目录内：`runtime/LICENSE`、`runtime/LICENSES.chromium.html`。

发布二进制时（即分发 `runtime/`）请一并保留这些文件 —— 它们在 `build_portable.py`
复制运行时的时候已经一起带过去了。

---

## dsh-orb（观察框设计的来源）

观察框的**设计**借鉴自 [dsh-orb](https://github.com/mini-yifan/dsh-orb-cordis)
（作者 mini-yifan，**MIT License**，★217）：

- 透明分层窗口 + 采集排除（`WDA_EXCLUDEFROMCAPTURE`）+ 点击穿透
- "外扩 stroke+glow 再夹到工作区"的几何算法
- 渐变描边的视觉做法

**代码是独立写的**（Python + 自己的 Electron 主进程），没有复制它的 TypeScript 实现。
只有一件事值得单独说明：`desktop_mcp/electron_frame.py` 里"必须删掉环境变量
`ELECTRON_RUN_AS_NODE`"这条关键约束，是从它的 `open-main.ts` 注释里读出来的
（那是个会让人查很久的坑，公开致谢）。

---

## 用法声明

这个工具**真的会操作你的电脑**：点击、输入、按键都会作用到真实窗口上。
请自行确认使用场景的合规性 —— 包括但不限于目标软件的服务条款。
`desktop_click_human` 用真人录制的轨迹模拟人手移动，请只在你有权操作的环境里使用。
