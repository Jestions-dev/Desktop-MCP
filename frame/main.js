/**
 * desktop-mcp observation frame renderer (Electron main process)
 *
 * 只干一件事：画一个发光边框，标出 agent 正在看的位置。
 *
 * 结构照抄 dsh-orb (MIT, github.com/mini-yifan/dsh-orb-cordis) 的 observation frame：
 *   · transparent: true   -> 真·逐像素 alpha，柔光能自然叠在桌面上
 *     （这正是换掉 Tk 的原因：Tk 只有颜色键透明，半透明像素会被 Windows
 *      与黑色预合成，于是辉光变成一圈黑色涂抹）
 *   · setContentProtection(true) -> 等价 WDA_EXCLUDEFROMCAPTURE，截图拍不到框
 *   · setIgnoreMouseEvents(true, { forward: true }) -> 点击穿透
 *   · setBounds() 直接设原生窗口，不经任何 UI 框架的坐标换算
 *
 * 两个必须遵守的启动条件（都踩过）：
 *   1. 环境里不能有 ELECTRON_RUN_AS_NODE —— DSH 带着它运行，继承下去
 *      会让 Electron 退化成纯 Node 模式，require('electron') 拿不到 API。
 *   2. 本目录的 node_modules 要指向一份 npm 装的 electron（它的 JS 包装需要它）。
 *
 * 与 Python 的协议（NDJSON，一行一条）：
 *   Python -> 本进程：{"cmd":"show","x":..,"y":..,"w":..,"h":..} | {"cmd":"hide"} | {"cmd":"quit"}
 *   本进程 -> Python：{"event":"ready","hwnd":123} | {"event":"shown",...} | {"event":"error",...}
 */
const { app, BrowserWindow, screen } = require('electron')
const path = require('node:path')
const http = require('node:http')

// 与 frame.css 里 #frame 的 inset 一致：窗口要比目标区域大出这个量，否则辉光被裁
const GLOW = 44

let win = null
let hwnd = 0

// Windows 的 HWND 是指针宽度；Electron 给的是小端 buffer
function nativeId(w) {
  try {
    const buf = w.getNativeWindowHandle()
    const id = buf.length >= 8 ? Number(buf.readBigUInt64LE(0)) : buf.readUInt32LE(0)
    return Number.isSafeInteger(id) && id > 0 ? id : 0
  } catch {
    return 0
  }
}

function send(obj) {
  try {
    process.stdout.write(JSON.stringify(obj) + '\n')
  } catch {
    // 父进程已经走了，忽略
  }
}

// 启动诊断走 stderr：stdout 是协议通道，不能混日志
function log(msg) {
  try {
    process.stderr.write('[frame] ' + msg + '\n')
  } catch {
    /* ignore */
  }
}

function createWindow() {
  const b = screen.getPrimaryDisplay().workArea
  win = new BrowserWindow({
    width: 32,
    height: 32,
    x: b.x,
    y: b.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    focusable: false,
    show: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    roundedCorners: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  win.setAlwaysOnTop(true, 'floating') // 浮在普通窗口之上，但不盖系统 UI
  // 采集排除：截图时拍不到自己的框（对应 Win32 的 WDA_EXCLUDEFROMCAPTURE）
  if (process.platform === 'win32') win.setContentProtection(true)
  // 点击穿透：鼠标事件穿过框，落到下面的窗口
  win.setIgnoreMouseEvents(true, { forward: true })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', (e) => e.preventDefault())

  win.loadFile(path.join(__dirname, 'index.html'))
  // hwnd 创建后立刻就有 —— 不等 did-finish-load。
  // 之前只在 did-finish-load 里报 hwnd，结果父进程可能在页面加载完成前就发
  // show 命令，那时窗口还没准备好、showInactive 无效，表现为"命令回了 ok
  // 但屏幕上什么都没有"（踩过，很隐蔽）。
  hwnd = nativeId(win)
  send({ event: 'ready', hwnd })
  win.webContents.once('did-finish-load', () => {
    log('did-finish-load')
    send({ event: 'loaded', hwnd })
  })
}

function handle(msg) {
  if (!win || win.isDestroyed()) return
  if (msg.cmd === 'show') {
    // 往外扩 GLOW，让辉光有地方铺开；超出屏幕的部分由系统裁掉即可，
    // 不做二次夹取（之前用错坐标系夹取，把 2612 夹成了 1707）
    const x = Math.round(msg.x - GLOW)
    const y = Math.round(msg.y - GLOW)
    const width = Math.max(2, Math.round(msg.w + GLOW * 2))
    const height = Math.max(2, Math.round(msg.h + GLOW * 2))

    // ⚠ 关键：Python 给的是**物理像素**，而 setBounds 收的是 **DIP**。
    // 150% 缩放的屏上两者差 1.5 倍 —— 不换算框就会跑到别处、还大一圈。
    // 实测：请求物理 (356,256) 888x588，结果落在 (534,384) 1332x882，
    // 正好 534/356=1.500、1332/888=1.5。之前一直没暴露，是因为我拿截图
    // 坐标去点击，两者同属一个坐标系，**自洽地错着**。
    const sf = screen.getPrimaryDisplay().scaleFactor || 1
    win.setBounds({
      x: Math.round(x / sf),
      y: Math.round(y / sf),
      width: Math.max(2, Math.round(width / sf)),
      height: Math.max(2, Math.round(height / sf)),
    })
    win.showInactive()
    send({ event: 'shown', hwnd, scaleFactor: sf,
           phys: { x, y, w: width, h: height },
           dip: { x: Math.round(x / sf), y: Math.round(y / sf),
                  w: Math.round(width / sf), h: Math.round(height / sf) } })
  } else if (msg.cmd === 'hide') {
    win.hide()
    send({ event: 'hidden' })
  } else if (msg.cmd === 'quit') {
    app.exit(0)
  }
}

app.on('window-all-closed', () => app.exit(0))

// 未捕获异常要报出来：静默退出会让人误以为是环境问题
process.on('uncaughtException', (e) => {
  send({ event: 'error', message: 'uncaught: ' + String((e && e.stack) || e) })
  app.exit(1)
})

app
  .whenReady()
  .then(() => {
    log('app ready')
    try {
      createWindow()
      log('createWindow 返回，等 did-finish-load')
    } catch (e) {
      send({ event: 'error', message: 'createWindow failed: ' + String((e && e.stack) || e) })
      log('createWindow 抛错: ' + String(e))
      app.exit(1)
      return
    }
    win.webContents.on('did-fail-load', (_e, code, desc) => {
      log(`did-fail-load ${code} ${desc}`)
      send({ event: 'error', message: `did-fail-load ${code} ${desc}` })
    })

    // ── 命令通道：本地 HTTP，不用 stdin ──
    // 为什么不用 stdin：Windows 上 Electron 的 stdin 读不到管道数据，
    // 会立刻触发 'end'，我们就会把"父进程还没说话"误判成"父进程走了"而自杀。
    // 实测：日志里 [frame] stdin end 出现在任何命令之前。
    // 只绑 127.0.0.1 + 随机端口，外部访问不到。
    const server = http.createServer((req, res) => {
      if (req.method !== 'POST') {
        res.writeHead(405).end()
        return
      }
      let body = ''
      req.on('data', (c) => {
        body += c
        if (body.length > 65536) req.destroy() // 防呆
      })
      req.on('end', () => {
        try {
          const msg = JSON.parse(body || '{}')
          log('收到命令: ' + JSON.stringify(msg).slice(0, 90))
          handle(msg)
          res.writeHead(200, { 'content-type': 'application/json' })
          res.end(JSON.stringify({ ok: true }))
        } catch (e) {
          res.writeHead(400).end(String(e))
        }
      })
    })
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      log('命令通道已监听 127.0.0.1:' + port)
      send({ event: 'listening', port })
    })
    server.on('error', (e) => {
      send({ event: 'error', message: 'http server: ' + String(e) })
      log('http server 错误: ' + String(e))
    })
  })
  .catch((e) => {
    send({ event: 'error', message: 'whenReady failed: ' + String((e && e.stack) || e) })
    log('whenReady 失败: ' + String(e))
    app.exit(1)
  })
