# Node-RED Demo Flow 库

> 销售现场演示用的预置 flow。每个 .json 是一个完整 tab，**Import 即用**。
> 不动当前运行的 `flows.json`，互不影响。

## Import 方法

1. 打开 Node-RED 编辑器：http://192.168.5.6:1880/
2. 右上角菜单 → Import
3. 选择 "select a file to import" → 选下面任一 `.json`
4. 点 Import → 出现新 tab → 编辑器右上角 Deploy

或者复制 JSON 文本，粘贴到 Import 对话框的 "or paste flow JSON" 框里。

## 现有 demo

### Demo A · 巡检关键词 → 对讲广播
`demo_a_inspection_keyword.json`

订 `av/audio/command_punctuated`，命中 "巡检/检查/排查" 关键词时往 `av/control` 推一条 `target=intercom action=broadcast` 指令。

**演示话术**："听到'巡检'两个字，AI 立刻让对讲系统广播'收到巡检指令'"

### Demo B · 视觉异常 → 声光报警 + 推送
`demo_b_anomaly_alert.json`

订 `av/video/openvocab` (openvocab_filter 出 hits 即推)，分流：
- `target=siren_strobe action=on` (声光报警, 高置信度=high)
- `target=notify_channel action=push` (oncall 推送)
- `av/audit/log` 落库

**演示话术**："摄像头看到火/烟/未戴安全帽，AI 自己触发报警 + 通知值班 + 留证"

**依赖**：`openvocab_filter` 5/21 修后能正常出 hits（5 类预设：fire/smoke/person without hardhat/falling/fighting）。

### Demo C · 智能纪要按钮 → LLM 摘要
`demo_c_smart_summary.json`

后台持续累积过去 5 分钟的 `av/audio/command_punctuated`（flow context 滑窗），dashboard 点"生成纪要"按钮（触发 `av/control/summary_request`）即把窗口内文本拼 prompt 发给 `av/llm/command`，结果回 `av/llm/summary_result`。

**演示话术**："按一下按钮，5 分钟前的对话变成 3-5 条要点摘要"

**注意**：
- 5 分钟窗口缓存放在 Node-RED 进程内 — Node-RED 重启会清空。演示场景够用。
- 触发按钮当前依赖 dashboard 自己发 `av/control/summary_request`，可手动用 `mosquitto_pub` 触发测试

## 通用约定

- 每个 flow 用独立 `broker` config 节点（id 各异），import 时不会冲突
- broker 默认 `127.0.0.1:1883`，3588 本地 mosquitto 一律可用
- function 节点的关键词 / 阈值都写在代码注释里，销售可现场改

## 销售脚本

完整流程参考 [docs/sales/node-red-customer-demo-script-20260520.md](../../../docs/sales/node-red-customer-demo-script-20260520.md)
