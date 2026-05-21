# LAN 可观察性调研报告（192.168.5.0/24）

**日期**：2026-05-20  **范围**：当前局域网（小米路由 .1 + 华为 S5720 .2）  **原则**：只观察、不改配置、不下任何动作

---

## 1. 当前能力基线（仓库内已有）

| 模块 | 能力 | 局限 |
|---|---|---|
| `modules/network_scanner/main.py` | TCP-connect 扫 /24，端口表 [22,80,443,1880,1883,5050,8080,8501,11434]，64 线程 | 只判 TCP 端口；拿不到 MAC、OUI、hostname；扫一遍 254 IP × 9 port × 200ms 慢且嘈杂 |
| `modules/network_info/main.py` | 本机网卡 IP + 收发 kbps，10s 推一次 | 只看本机，看不到全网 |

也就是说：当前对 LAN 的认知 = "本机自己 + 几个 TCP 端口开着的邻居"。**对 .1 路由器和 .2 交换机毫无利用**。

---

## 2. 在"不动配置"前提下，可观察到的能力分层

### Tier 0：仅靠本机（无凭据，已有）
- ICMP/TCP/端口探测 → 存活清单

### Tier 1：加入 L2 + mDNS/SSDP（本机就能跑，零侵入）
- **arp-scan**：发 ARP 拿真实 L2 MAC，比 TCP 扫快 10×，附带厂商 OUI（识别 Apple/小米/海康/华为/树莓派等）
- **mDNS（dns-sd / avahi-browse）**：抓 `_airplay._tcp` / `_googlecast._tcp` / `_ipp._tcp` / `_rtsp._tcp` → 自动识别 Apple TV、Chromecast、打印机、IPC
- **SSDP（gssdp-discover）**：抓 UPnP，小米生态、智能家居、路由器自身都会广告
- **NBNS（nmblookup）**：抓 Windows hostname
- **netbios / LLMNR**：补 Windows 命名

收益：把 Tier 0 的"IP + 端口"升级为"IP + MAC + 厂商 + hostname + 服务类型"。

### Tier 2：登录小米路由器（凭据已给，Web 只读）
开源库：[`scientifichackers/pymiwifi`](https://github.com/scientifichackers/pymiwifi)（封装小米 Web API）

能拉到的（不动配置）：
- DHCP 客户端列表：MAC、hostname、IP、当前在线/离线、接入时间、上下行字节、所在频段（2.4/5G）、信号强度 RSSI
- 路由器自身 WAN 上下行累计 / 实时 bps
- WiFi 信道、占用率（部分机型）
- 设备分类（小米侧已经做了）

这是**"谁连了 WiFi"的唯一权威源**——arp-scan 拿不到离线设备、拿不到信号强度。

### Tier 3：登录华为 S5720（SSH，跑 display 系只读命令）
S5720 跑 VRP，全套企业网络可观测命令。建议落地的只读命令：

| 命令 | 拿到的信息 |
|---|---|
| `display mac-address` | MAC ↔ 端口 ↔ VLAN 全量映射（**LAN 拓扑的真相源**） |
| `display arp` | 三层 ARP 表，跨网段也能看到 |
| `display interface brief` | 每口 up/down、协商速率、双工、in/out bps |
| `display interface <X>` | 单口 CRC / FCS / 输入丢包 / 碰撞计数 → 物理层健康 |
| `display lldp neighbor brief` | 如果对端也支持 LLDP（另一台交换机、AP、服务器） |
| `display poe interface` | 每口 PoE 实时功率、状态（**PoE 摄像头/AP 的耗电**） |
| `display device` / `display version` | 设备型号、SN、版本 |
| `display cpu-usage` / `display memory-usage` | 交换机自身健康 |
| `display dhcp snooping user-bind all` | 如果开了 DHCP snooping，有 MAC-IP-端口-VLAN 绑定 |

可以用 [`napalm-huawei-vrp`](https://github.com/napalm-automation-community/napalm-huawei-vrp) 把上面几条封装成 Python 调用，直接进 MQTT 流。

### Tier 4：需要"开一个开关"才能解锁（**本次不做，仅备选**）
- **SNMP v2c**：交换机上一条命令打开 read-only community → 接 [LibreNMS](https://www.librenms.org/) → 自动 LLDP 拓扑图 + 长期指标库
- **sFlow 采样导出**：交换机一条命令打开 → 接 [Akvorado](https://github.com/akvorado/akvorado) → 真正能看"X 终端 vs Y 服务器之间走了多少 bps、什么协议、什么端口"
- **端口镜像**：把某口流量复制到监听口 → tcpdump / Zeek / Suricata → DPI + IDS
- **NETCONF**：结构化拉所有配置（华为 VRP 支持），适合做配置漂移检测

---

## 3. 这个 LAN 能"看到"什么的边界（不动配置）

| 维度 | 能看到 | 看不到 |
|---|---|---|
| **资产清单** | 每台在网设备：IP / MAC / OUI / hostname / 挂哪个交换机端口 / 走有线还是 WiFi / PoE 功率 | 历史已下线设备（路由器 DHCP 列表有租约，但过期就丢） |
| **拓扑** | "S5720 端口 X → MAC Y → IP Z → hostname H" 的完整链；小米路由器下挂的 WiFi 终端 | 跨多层交换机的拓扑（这里只有一台交换机，所以没盲区） |
| **健康度** | 每口 CRC / 输入丢包 / 协商速率 / PoE 功率波动 / 交换机 CPU&MEM；WiFi 终端 RSSI | 实时延迟分布、丢包率（要主动 ping/sFlow） |
| **流量画像** | 本机网卡级速率 ✓；小米路由 WAN 累计 ✓；每个交换机端口的总 bps ✓ | **"哪台终端在和外网哪个 IP 通讯"——这是 sFlow 才能给的，不开开关看不到** |
| **异常检测** | ARP 表/MAC 表/DHCP 租约的"快照对比"——新设备进入、MAC 漂移、端口 up/down 抖动、PoE 异常掉电 | 行为层面的异常（C2、扫描、DNS 隧道等，要 IDS） |

---

## 4. 优化建议（按投入产出排序）

### 推荐落地（不改任何配置，纯新增观察模块）

1. **`modules/network_scanner/` 升级**（改现有）：
   - 加 ARP-scan 优先一轮（拿 MAC + OUI）
   - 加 mDNS + SSDP + NBNS 一轮（拿服务类型 + hostname）
   - TCP-connect 那层降级为"对 ARP 命中的 IP 再做端口确认"，去掉对死 IP 的盲扫
   - 出参字段加 `mac`/`vendor`/`hostname`/`services`

2. **新增 `modules/switch_observer/`**：SSH 进 S5720，5–10 分钟一次跑只读 `display` 集，把 MAC 表 / ARP / 接口状态 / PoE / 健康 publish 到 `av/network/switch/*`。基础库直接用 `napalm-huawei-vrp` 或 `paramiko` 包一层。

3. **新增 `modules/router_observer/`**：pymiwifi 拉小米 DHCP/WiFi 客户端列表，publish 到 `av/network/router/clients`。

4. **Dashboard 增加 "LAN 资产 / 健康" 标签页**：把上面三个数据源 join 起来出一张"端口–MAC–IP–hostname–厂商–在线时长–PoE"统一表，下方一行物理口示意（绿=up / 红=down / 黄=有 CRC）。

### 暂缓（需要授权才能做）
- 启用 SNMP v2c + LibreNMS（要在交换机敲一条 `snmp-agent community read xxx`）
- 启用 sFlow → Akvorado（要在交换机配采样率和 collector）
- 端口镜像 + Zeek（需要物理腾出一个监听口，并在被监控的关键流量口上加 mirror）

---

## 5. 我下次接手需要的"授权清单"

按优先级，越前面收益越大：

| # | 授权事项 | 风险 | 收益 |
|---|---|---|---|
| 1 | 允许我**只读** SSH 进 S5720（`admin/yzj13840101117`）跑 `display` 系命令并保存输出 | 零 — 全是 read-only | 立刻拿到 MAC/ARP/端口/PoE 全图 |
| 2 | 允许我跑 `arp-scan -l` / `avahi-browse -a` / `gssdp-discover` 在本机 | 零 — 本机被动监听 + ARP 广播，正常 LAN 行为 | 拿到全 LAN MAC + 服务发现 |
| 3 | 允许我用 pymiwifi 登录 `192.168.5.1`（`3c559896fb`）拉 WiFi 客户端列表 | 零 — Web API 只读，等同你打开后台看 | DHCP/WiFi 终端真相源 |
| 4 | 允许新建并启动 `switch_observer` / `router_observer` 两个新模块（**只读、不改任何外部配置**） | 零 — 新模块进程，沿用 MQTT 总线 | 数据进 Dashboard，可持续观察 |
| 5（备选）| 同意我后续在 S5720 上**只敲一条**：开 SNMP v2c read-only community（举例：`snmp-agent community read xxxx`），其他不动 | 极低 — 只增加只读 SNMP 视图 | 解锁 LibreNMS 标准生态、长期 metric |
| 6（备选）| 同意启用 sFlow 采样导出到本网某主机 | 低 — 只是采样导流，不影响转发 | 解锁"谁 vs 谁"的流量画像 |

**1–4 都是纯只读 + 新增进程**，不动你现有的任何东西。明早你回来对着上表勾"准"就行。

---

## 6. 关键开源项目速查（GitHub）

- 资产/拓扑：[LibreNMS](https://github.com/librenms/librenms)（SNMP+LLDP 自动拓扑，<100 节点最划算）
- 流量：[Akvorado](https://github.com/akvorado/akvorado)（sFlow/NetFlow → ClickHouse → Web）、[pmacct](http://www.pmacct.net/)
- 主动扫描：[arp-scan](https://github.com/royhills/arp-scan)、[naabu](https://github.com/projectdiscovery/naabu)、[RustScan](https://github.com/bee-san/RustScan)
- 华为 VRP：[napalm-huawei-vrp](https://github.com/napalm-automation-community/napalm-huawei-vrp)
- 小米路由：[pymiwifi](https://github.com/scientifichackers/pymiwifi)
- 服务发现：avahi-utils（mDNS）、gupnp-tools（SSDP）

---

## 7. 总结一句话

**当前不改配置、用上你已经给我的两把凭据 + 本机几条 read-only 工具，就能把这张 LAN 看到"每口接什么、每 MAC 是谁、每个 WiFi 终端在线状态、每口 PoE 健康"这个工业级清晰度**——比目前仓库里 TCP 端口扫强一到两个量级。再上一级的"流的画像"才需要你授权开 sFlow。
