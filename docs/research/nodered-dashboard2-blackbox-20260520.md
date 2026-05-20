# Node-RED 中控帧黑框 "Cannot GET /dashboard/" 根因诊断（5/20）

## 现象

5/20 上午 user 演示截图：dashboard 总览页第一块"Node-RED 中控"嵌入帧显示黑底白字：

```
Cannot GET /dashboard/
```

## 现场快速诊断（5/20 02:15）

| 端点 | HTTP | 说明 |
|---|---|---|
| `GET http://192.168.5.6:1880/` | 200 | Node-RED 编辑器主页 OK |
| `GET http://192.168.5.6:1880/ui/` | 200 | dashboard **1.x** OK（`node-red-dashboard` 3.6.6） |
| `GET http://192.168.5.6:1880/dashboard/` | **404** | dashboard **2.0** 路由没注册 |
| `GET http://192.168.5.6:1880/red/` | 404 | 不存在（路径假设错） |

`/flows` 返回 59 节点 2 tabs，其中包含：
- `type=ui_tab` "指挥中心控制端"（dashboard 1.x 页面）
- `type=ui-page` "AI 看板"（dashboard 2.0 页面，`ui_base=11692f75b65a4c92`，`path: /dashboard`）

## 根因

3588 上 Node-RED userDir 是 `/home/firefly/av_unified_mvp/node-red/`（不是默认的 `~/.node-red/`）。

- `package.json`（userDir 下）声明：
  ```json
  "@flowfuse/node-red-dashboard": "^1.30.2"   ← dashboard 2.0 plugin
  "node-red-dashboard": "^3.6.6"              ← dashboard 1.x plugin
  ```
- 实际 `node_modules/` 里只装了 `node-red-dashboard` 1.x；`@flowfuse/` 整个 scope 目录不存在
- `~/.node-red/node_modules/@flowfuse/node-red-dashboard/` 装了，但 Node-RED 跑的是 userDir 不读这里

**启动日志确认**（`/home/firefly/av_unified_mvp/node-red/node-red.log`）：

```
20 May 01:55:11 - [info] Dashboard version 3.6.6 started at /ui      ← 1.x 启动成功
20 May 01:55:11 - [info] Waiting for missing types to be registered:
20 May 01:55:11 - [info]  - ui-base
20 May 01:55:11 - [info]  - ui-theme
20 May 01:55:11 - [info]  - ui-page
20 May 01:55:11 - [info]  - ui-group
20 May 01:55:11 - [info]  - ui-template
```

→ dashboard 2.0 的 5 个核心 node type 永远等不到注册，因为 plugin 没装到 userDir。
→ flows 里那个 ui-base 配置（`path: /dashboard`）不被启用 → express 没挂 `/dashboard/` 路由 → 404。

## 前端为何踩坑

`web/static/dashboard.js` 的 `buildOverviewNodeRedSelector` 排序规则：
```js
(a.type === "ui-page") === (b.type === "ui-page") ? 0 : (a.type === "ui-page" ? -1 : 1)
```
ui-page 排第一。selector 默认选中后调 `navigateNodeRed`，`pageUrlPath` 对 ui-page 返回 `/dashboard/` → iframe src → 404 黑框。

## 修复（已在 experiment/node-red-polish 分支落地）

前端兜底，不动 3588 任何包：

1. 新增 `probeDashboard2()`，在 selector build 前 `GET /dashboard/` 探活，结果缓存
2. `detectNodeRedPages` 在 d2 不可达时把 `ui-page` 从 `rawPages` 过滤掉，selector 只显示 `ui_tab`
3. `loadOverviewNodeRed` 5 秒兜底 src 按 d2 探活结果切 `/dashboard/` 或 `/ui/`

效果：dashboard 2.0 plugin 装好则正常用，没装就自动降级到 1.x 的 `/ui/` 路径（指挥中心控制端 tab），不再黑框。

## 后续 user 决策点

A. **彻底修**（推荐）：在 3588 上补装 plugin

```bash
ssh firefly@192.168.5.6
cd /home/firefly/av_unified_mvp/node-red/
npm install @flowfuse/node-red-dashboard@1.30.2
# 等 Node-RED 重启（supervisor 会自动）或 systemctl restart node-red
curl -sI http://192.168.5.6:1880/dashboard/   # 应 200
```

B. **不装**（当前默认）：前端自动降级到 dashboard 1.x，"AI 看板" 那个 ui-page 在中控帧里看不到——只看到 1.x "指挥中心控制端" tab。对当前客户演示足够（user 5/20 ack）。

按 user 协作规则："写 install / sudo 之前必须先确认"——这次走前端 fallback，等 user 拍板再决定是否补 plugin。
