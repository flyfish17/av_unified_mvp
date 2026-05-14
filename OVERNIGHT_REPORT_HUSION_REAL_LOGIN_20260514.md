# husion HDC900 真登录 + 后台抓取报告
日期: 2026-05-14 (Sub-C 中午跟进)
设备: husion 一体机 HDC900 @ 192.168.5.253:80
凭据: admin / 123456

---

## 1. 登录是否成功

**成功**。

- 登录 URL: `POST http://192.168.5.253/api/login`
- 登录后跳转: `http://192.168.5.253/#/software-entrance`
- 页面 title: `可视化综合管理系统`
- 后端: nginx + Vue.js SPA + ElementUI

**关键发现**: 密码经前端 JS 加密后发送:
```json
{
  "username": "admin",
  "password": "aR7eWESkeD5swJMLDjQN4w==",    ← 浏览器内 JS 把 "123456" 加密成此密文
  "isadmin": true, "issso": true, "role": "admin",
  "is_admin": true, "is_sso": true
}
```
返回 JWT (`Authorization: Bearer <jwt>`)。**密文可直接重放** — 已实测脱离浏览器 curl 直登成功。

### 截图

| 路径 | 内容 |
|---|---|
| `/tmp/husion_login_filled.png` | 登录表单已填好 (登录前) |
| `/tmp/husion_dashboard.png` | 登录后主页 - 软件入口选择卡 |
| `/tmp/husion_visual_control.png` | 可视化交互页 (核心控制 UI) |
| `/tmp/husion_system_mgmt.png` | 系统管理页 (左侧导航) |
| `/tmp/husion_sys_设备列表.png` | 系统管理 → 设备列表 (xpanel_browser 体系) |
| `/tmp/husion_visual_edit.png` | 可视化编辑页 |

主页 HTML 大小 5.2 MB (Vue SPA 大量 inline + 加密 chunk) — 已落 `/tmp/husion_dashboard.html`。

---

## 2. 后台主页内容描述

登录后是 **软件入口选择页** (`#/software-entrance`),三张大卡:

1. **可视化编辑** (Visual Edit, 绿色)
2. **可视化交互** (Visual Control, 蓝色) ← **核心 — 视频墙 + 9 路设备控制都在这**
3. **系统管理** (System Management, 黄色)

### 可视化交互页面
- 顶部: 信号列表 / 输出列表 / 多视化 / 预设模式 / 显示模式 切换 tab
- 中间: 1×1 视频墙画面 (当前显示 "无纸化电脑1" + "无纸化电脑3" 两个窗口)
- 右侧: 显示输出树 (研发 → undefined → 9 路 RX)
- 底部: 9 张设备缩略图 ribbon: **无纸化电脑1/2/3, 桌插, Tx_5005, Tx_5006, Tx_5007, Tx_5008, Tx_5009** ← 完美匹配 5/12 husion_distributed 模块已知的 5001-5009 ID

### 系统管理页面
左侧菜单: 首页 / USB切换 / 设备配置 (含: 白鲨 RX 系列 / 白鲨 TX 系列 / 深编码系列 / 混合编码系列 / 浅编码系列 / 显示处理终端 / 应用服务器 / 流媒体 / IPC 管理 / 控制系统 / USB 发送/接收终端) / **设备列表** / 操作配置 / 账号管理 / 操作日志。设备列表页 (xpanel_browser 视角) 当前为空,与 9 路 husion 自有设备是两套数据源。

---

## 3. 9 设备 API ✅

**找到了, 而且不止一个**。

### `/api/get_all_equ` (GET, 推荐主用)
返回 9 设备完整状态:
```json
{"statusCode":200,"code":0,"data":[
  {"id":"5001","name":"无纸化电脑1","ip":"169.254.150.1",
   "dev_type":"RX-IMIS-MULTIv5-DL","online":"1G-M",
   "hls":"ws://192.168.150.1:15354/live/chn2_sub.flv","area":"server"},
  {"id":"5002","name":"无纸化电脑2","ip":"169.254.150.2", ...},
  {"id":"5003","name":"无纸化电脑3", ...},
  {"id":"5004","name":"桌插", ...},
  {"id":"5005","name":"Tx_5005", ...},
  ...
  {"id":"5009","name":"Tx_5009","ip":"169.254.150.9", ...}
]}
```
**重要发现**: 每个设备都暴露 `hls: "ws://192.168.150.X:15354/live/chn2_sub.flv"` — 可以**直接拉子码流 flv-over-websocket** (比走 husion 自己的 TCP :6000 转发更直接)。

### `/api/get_all_display` (GET)
返回 wall + RX 输出端 (10 条: 1 墙 + 9 RX), 字段更全 (含 wall_type / out_resolution "1920x1080p60" / decode_name "升降显示器1" 等)。

### `/api/wall/w?wall_id=1` (GET)
返回当前墙上窗口实时状态 + 输入源映射:
```json
{"data":[
  {"wall_id":"1","win_id":"1","pos_x":"844","pos_y":"248","win_w":"640","win_h":"362",
   "tx_id":"5001","tx_name":"无纸化电脑1","type":"rx",
   "hls":"ws://192.168.150.1:15354/live/chn2_sub.flv"},
  {"wall_id":"1","win_id":"2","tx_id":"5003","tx_name":"无纸化电脑3", ...}
]}
```

### `/api/wall/wall_details?idWall=1` (GET)
返回墙物理规格 (3840×2160, 1 行 1 列, 4 win 上限, 接 1 个 SP RX `10001`)。

---

## 4. 视频源切换接口

**已定位候选 endpoint, 但未实操验证 payload** (硬约束: 不真按"切换"按钮)。

JS 扫了 13 个 chunk 共 20 MB, 提取 **256 个 /api/ 端点**,落 `/tmp/husion_all_apis.json`。视频/墙/源相关 104 个。最可能的切换 endpoint:

| Endpoint | 推测语义 | 优先级 |
|---|---|---|
| `POST /api/wall/switch` | 切墙窗口信号源 | **A** |
| `POST /api/wall/editWin` | 改墙窗口 (含 tx_id) | A |
| `POST /api/wall/buildWin` | 新建墙窗口 | B |
| `POST /api/wall/delWin` | 删墙窗口 | B |
| `POST /api/wall/push_signal` | 推送信号 | B |
| `POST /api/equ/switch` | 设备级切换 | B |
| `POST /api/switch/wall` | 备选别名 | B |
| `POST /api/usb/switch` | USB 切换 | (USB 矩阵专用) |

辅助 endpoint:
- `GET /api/whiteshark/rx/all_tx_list` — 列某 RX 可接的所有 TX
- `GET /api/wall/preset`, `/api/wall/scene` — 预设场景一键切
- `GET /api/wall/list` — 墙列表
- `POST /api/wall/rx_scene`, `/api/wall/screen_switch` — 整屏切换

下次接入须按以下步骤实操确认 (5 min):
1. Playwright 开 listen，在 husion web 实际点一次某个窗口的信号源切换
2. 抓 `POST` 请求体 → 落 payload 模板
3. 写入 `_husion_switch_source` 的 NotImplementedError 替代实现

---

## 5. 模块框架补完

`modules/web_browser/main.py` 已更新 (+98 行,文件总长 ~200 行):

- 文件顶部 docstring 补 husion 接入备忘 (含 256 个 API 总数 + 关键 endpoint 索引)
- 新增常量 `HUSION_BASE` / `HUSION_LOGIN_PAYLOAD` (含已加密密文)
- 新增 4 个 method 到 `WebBrowserModule`:
  - `_husion_login() -> str` — 直 REST 登录返 JWT,已实测 ✅
  - `_husion_get(path, token) -> dict` — 通用 GET helper
  - `_husion_list_devices(token=None) -> list` — 9 路设备 (走 `/api/get_all_equ`),已实测 ✅
  - `_husion_get_wall_state(wall_id=1, token=None) -> dict` — 墙状态 + 详情,已实测 ✅
  - `_husion_switch_source(...)` — **占位 raise NotImplementedError**,含 docstring 列三个候选 endpoint
- MQTT cmd 路由暂未改 (等切换 payload 确认后再加 `action="husion_list_devices"` 等)

语法校验通过 (`python3 -c "import ast; ast.parse(...)" ` ok)。

---

## 6. 第三步 B 浏览器模块下一步建议

**优先级排序**:

### P0 · 切换 endpoint 实操确认 (5-10 min, 下次必做)
脚本: Playwright 启 → 登录 → 进可视化交互 → listen request → 点一次任意窗口的 TX 切换 → 落 payload → 写进 `_husion_switch_source`。**做这一步前**要先和 user 确认能不能在工作时间动 husion (5/12 user 强调过)。

### P1 · 直接拉 hls/flv 子码流 (5 min)
9 设备各暴露 `ws://192.168.150.X:15354/live/chn2_sub.flv`,可直接接入 `modules/video_input/` 或 `modules/husion_distributed/`,**比通过 husion :6000 TCP 转发省一跳**。但 169.254.150.X 网段在 husion 内网,本机能否直连待测 (可能需把测试机加进 husion 子网)。

### P2 · 接入到 av_unified_mvp 主消息总线
- `av/web_browser/cmd` 加 `action="husion_login" / "husion_list_devices" / "husion_get_wall_state"`
- 把 dry_run 默认值改成根据 target 决定 (husion 模式无需启 chromium)
- 把 JWT 缓存进 BaseModule (15 min 过期需测)

### P3 · 把 husion 设备元数据合并进 husion_distributed
- 现在 `modules/husion_distributed/` 是 5/12 写的 TCP :6000 协议侧,**只有协议没有元数据**
- 用 `_husion_list_devices()` 拉到的 name / dev_type / online / hls 字段填进它的设备 registry → 摆脱硬编码 ID 5001-5009 + name

### P4 · 探 xpanel_browser 体系
`/api/xpanel_browser/devices/list` 当前空,但 JS 里有完整 CRUD (含 `device_category/tree_list`),猜测是 husion 后续要把第三方设备 (非白鲨) 纳管的体系 — 长期可以把 b 项目的 Mac/3588/Jetson 通过该 API 注册进 husion 让 husion 反向了解我们,实现真"统一"。

### P5 · 别的"软件入口"
- 可视化编辑 (Visual Edit) — 估计是布局编辑,创建虚拟屏/虚拟墙,可能含离线 preset 编辑接口,P2 探
- 系统管理 → 操作日志 — 看 husion 历史切换日志,辅助回放/故障排查

---

## 7. 硬约束遵守情况 ✅

- ❌ 未真按"切换"按钮 (浏览菜单时跳过含"切换/应用/保存/确定/删除/重启/重置/退出/登出/新增/添加/修改/停止/启动" 的按钮文本)
- ❌ 未改密码,未点退出 (session 仍在,但浏览器进程已 close)
- ❌ 未动 3588 / Jetson / Mac mini
- ❌ 未 commit (modules/web_browser/main.py 是 unstaged 修改)
- ✅ Playwright 跑完都 `ctx.close() / browser.close()` (无残留 chromium 进程)
- ✅ 截图 + HTML 都落 /tmp

---

## 8. 关键产物清单

| 路径 | 用途 |
|---|---|
| `/tmp/husion_dashboard.png` | 后台主页截图 (软件入口) |
| `/tmp/husion_dashboard.html` | 主页 HTML 全文 |
| `/tmp/husion_visual_control.png` | 视频墙控制 UI 截图 (核心) |
| `/tmp/husion_system_mgmt.png` | 系统管理截图 |
| `/tmp/husion_sys_设备列表.png` | xpanel 设备列表页 |
| `/tmp/husion_xhr.jsonl` | 登录阶段 XHR 录制 |
| `/tmp/husion_xhr_explore.jsonl` | 浏览三个子模块时 XHR 录制 (含 9 设备/墙详情 JSON) |
| `/tmp/husion_all_apis.json` | JS 全量扫出的 256 个 API endpoint |
| `/tmp/husion_real_login.py` | 真登录脚本 (核心 reusable) |
| `/tmp/husion_explore.py` | 后台子模块浏览脚本 |
| `/tmp/husion_scan_js.py` | JS 全量 API 扫描脚本 |
| `/tmp/husion_capture_login.py` | 登录 payload + auth header 抓包脚本 |
| `/tmp/husion_rest_test2.py` | 脱离浏览器直 REST 验证 (核心证据) |
| `modules/web_browser/main.py` | 模块代码 (已加 4 个 husion handler,dry-run 默认) |
