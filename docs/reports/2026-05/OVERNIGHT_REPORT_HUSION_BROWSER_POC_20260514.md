# husion HDC900 浏览器模块 POC 报告

- 日期：2026-05-14
- 任务：av_unified_mvp §1.5 形态 C — 浏览器模块可行性（Playwright 验证）
- 目标：husion 一体机 web 后台 + 跨品牌 web 自动化

---

## 核心结论

| 项目 | 结论 |
|---|---|
| husion 是否有 web 后台 | **有**（nginx :80） |
| Playwright Mac 是否可装可跑 | **可**（pip3 --user + chromium headless） |
| POC 截图是否拿到 | **是**（`/tmp/husion_screenshot.png`，18 KB） |
| 模块框架是否完成 | **是**（`modules/web_browser/main.py`，98 行，含 dry-run） |
| 下一步建议 | **继续**——浏览器模块路径已验证可行 |

---

## Step 1 · husion 端口探活

针对 `192.168.5.253` 的 10 个常见 web 端口（80 / 443 / 8000 / 8080 / 8443 / 8888 / 9000 / 9090 / 5000 / 3000）逐个 `curl -sI -m 2`，结果：

- **80**：HTTP/1.1 200 OK，`Server: nginx/1.16.1`，Content-Type: text/html，Content-Length: 2707
- 其余 9 个端口：无响应（连接拒绝或超时）

主页是 Vue.js + ElementUI SPA：
```
<title></title> (HTML 静态壳)
<link ... rel=preload as=script  static/js/app.aab23244.js
<script src=js/liveplayer-lib.min.js>  ← 实时视频播放库
```

也就是说 husion **既有 TCP :6000 控制协议，也有 :80 web 管理后台**——浏览器模块对 husion 完全适用。

## Step 2 · Playwright 安装与 POC

### 安装

- `pip3 install playwright --user` → playwright 1.59.0（含 greenlet 3.5、pyee 13.0）
- `python3 -m playwright install chromium` → Chrome Headless Shell 147.0.7727.15 → `~/Library/Caches/ms-playwright/chromium_headless_shell-1217`
- Python 3.14.3，全部 user-mode，未污染系统。

### POC 脚本：`/tmp/husion_browser_poc.py`

- chromium headless，1366×900 viewport
- `page.goto(..., wait_until="domcontentloaded")`（最初用 networkidle 超时，liveplayer 长连接导致永远不 idle，已修正）
- 等 `#app *` 出现（Vue 挂载完成）
- 截图 + dump rendered HTML + 抓所有 input/button + 抓 body innerText

### POC 实测输出

```json
{
  "status": 200,
  "title": "可视化综合管理系统",
  "screenshot": "/tmp/husion_screenshot.png",
  "rendered_html": "/tmp/husion_rendered.html",
  "rendered_bytes": 5253788,
  "inputs": [
    {"name": "", "type": "text", "placeholder": "请选择"},
    {"name": "username", "type": "text", "placeholder": "请输入用户名"},
    {"name": "password", "type": "password", "placeholder": "请输入密码"}
  ],
  "buttons": ["登录", "重置"],
  "body_text_excerpt": "備\n登录\n重置"
}
```

**判定**：husion 进入即看到登录页（标准用户名/密码表单 + 登录/重置按钮），Playwright 可以无障碍渲染 + 截图 + 抓 DOM。**没真填密码**，符合"不真改 / 真操作"约束。

### 关键文件

- `/tmp/husion_browser_poc.py`（POC 脚本，~70 行）
- `/tmp/husion_screenshot.png`（登录页截图，18 KB）
- `/tmp/husion_rendered.html`（完整 Vue 渲染后 HTML，5.0 MB）
- `/tmp/husion_index.html`（裸 nginx 返回的静态壳，2.7 KB）

## Step 3 · 模块框架

`modules/web_browser/main.py`（98 行，含 docstring）+ `__init__.py`。

设计要点：
- 继承 `core.base_module.BaseModule`，与 husion_distributed / network_scanner 等同构
- 订 `av/web_browser/cmd`，payload 形如 `{action: screenshot|click|type|goto, target: <name>, params: {...}}`
- 发 `av/web_browser/state` 携带 `screenshot_b64` + `extract: {title}`
- **默认 `dry_run=True`**：只 log 不真启 chromium，避免任何模块自启后误点
- 设备清单走配置：`config["web_browser"]["targets"][<name>] = {url, login}`，把 url / 凭据从代码剥离
- Playwright 延迟 import（dry-run 时不强依赖，部署到无 playwright 的 box 也不崩）

未做（明确留给下一阶段）：
- 真实登录流程（需 husion 凭据，本次硬约束禁止操作）
- 截图缓存策略 / b64 体积限制（一张 18 KB 走 MQTT 没问题，但全页 5 MB 渲染版本要落盘 + 发路径）
- 多 target 并发（asyncio.run 当前是单次同步语义）
- 未挂入 supervisor / start.command（按"只 POC 不部署"约束）

## 硬约束执行情况

| 约束 | 状态 |
|---|---|
| 不动 3588 / Jetson / Mac mini | OK |
| 不真改密码 / 真操作设备 | OK（只截登录页，未填表单） |
| 不 commit 任何代码 | OK（未 git add） |
| POC 文件留 /tmp 或 modules/web_browser/ | OK |
| 模块框架 ≤ 100 行 | OK（98 行） |
| 报告 < 150 行 | OK |

## 下一步建议

1. **继续**——浏览器模块这条线路已闭环（husion 有 web、Playwright 跑通、模块框架就位）
2. 下次接手先做的事：
   - 在 `config/system_config.yaml` 加 `web_browser:` 段（targets + 凭据占位）
   - 写一个 husion **登录后**的截图测试（用户提供凭据后），看登录后看板是不是真能拿到 9 路设备列表 / 视频墙状态
   - hikvision IPC（财务室/办公室 192.168.5.181 等）作为第二个 target 测一遍，确认跨品牌都 OK
   - 把 dry_run=False 启用前，加一道"白名单 URL"防御（不在 targets 里的 URL 拒绝访问）
3. 关键风险：Vue SPA 的元素 selector 没有稳定 id（如 input 的 id="", name="username" 是 ElementUI 标准命名），登录脚本应优先用 `placeholder` / `name` 选择，避免哈希类名失效
