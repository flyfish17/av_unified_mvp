# 湖森 DNC 批量复刻安装 SOP（全离线资产包 · A→Z）

> 用途：把 3588 当前版本（funasr 2pass 引擎 + RKLLM-NPU LLM + 全栈）批量复刻到湖森 DNC
> 计算模块（RK3588 EVB，`proembed` 用户）。**目标机零外网要求**，全部资产走离线包。
> 首台走通记录：2026-07-03，DNC `192.168.5.62`（本文档即按它实测写成）。
>
> 与 `3588-new-machine-install.md` 的差别只有一处本质：DNC vendor 内核
> （5.10.110-dirty）**未编 `CONFIG_BPF_SYSCALL`**，docker/runc 在 cgroup v2 上设
> device 规则必须走 eBPF → 容器一律 `bpf_prog_query failed` 起不来。
> 解法 = **脱 docker 化**：镜像 rootfs 直接落盘，systemd `RootDirectory=` 跑
> server 二进制。引擎与 3588 docker 版逐字节相同（同镜像导出）。

## 0. 目标机预检（每台机先跑，5min）

```bash
ssh proembed@<DNC_IP>    # 出厂密码 xc
uname -r                                   # 预期 5.10.110-*；不同内核先做下面判定
zcat /proc/config.gz | grep -E "CONFIG_BPF_SYSCALL|CONFIG_CGROUP_BPF"
#   → "is not set" = 走本文档脱 docker 化路径（湖森 DNC 常态）
#   → 都 =y       = 可直接按 3588-new-machine-install.md 用 docker（load 资产包里的镜像 tar）
df -h /                                    # 需 ≥ 14G free
arecord -l                                 # 确认 USB 麦在（板载 ES8388 无麦）
date                                       # 记录板子时钟时区 → 决定 nightly timer 时刻（§6）
```

## 1. 离线资产包（金拷贝清单 ~14G）

从首台走通的 DNC（金源）导出一次，存移动盘/内网 NAS：

| 资产 | 大小 | 金源导出命令（在金源 DNC 上） |
|---|---|---|
| funasr rootfs | ~2.8G | `sudo tar -C /opt/funasr-rootfs -czf funasr-rootfs.tgz .` |
| funasr 模型 | ~1.7G | `tar -C ~ -czf funasr-models.tgz funasr-models` |
| funasr 镜像 tar（备用，有 docker 能力的机型用） | ~4.6G | `docker save funasr镜像 -o funasr-image.tar`（可选） |
| 仓库代码 | 小 | Mac：`git archive --format=tar main \| gzip > av_unified_mvp.tgz`（基准见 §8：main + 金源 config） |
| Python venv | 5.8G | `tar -C ~ -czf venv.tgz creator_ai_demo/venv` |
| RKLLM daemon+权重 | 2.0G | `tar -C ~ -czf rkllm-poc.tgz rkllm-poc` |
| SenseVoice-RKNN（回退路线） | 0.5G | `tar -C ~ -czf sensevoice.tgz SenseVoiceSmall-RKNN2` |
| rknnlite 等 --user 包 | 405M | `tar -C ~ -czf dot-local.tgz .local/lib/python3.10/site-packages` |
| librknnrt.so 2.3.0 | 小 | `cp /usr/lib/librknnrt.so .` |
| node-red userDir 依赖 | 135M | `tar -C ~/av_unified_mvp/node-red -czf nodered-modules.tgz node_modules` |
| systemd 单元模板 ×4 | 小 | 仓库 `deploy/systemd/`（av-demo / funasr-server / funasr-nightly ×2）+ node-red user unit（§5） |

## 2. 落资产（新机上，~20min 拷贝）

```bash
# 假设资产包挂在 /mnt/pack
sudo mkdir -p /opt/funasr-rootfs && sudo tar -xzf /mnt/pack/funasr-rootfs.tgz -C /opt/funasr-rootfs
tar -xzf /mnt/pack/funasr-models.tgz -C ~          # → ~/funasr-models
mkdir -p ~/av_unified_mvp && tar -xzf /mnt/pack/av_unified_mvp.tgz -C ~/av_unified_mvp
tar -xzf /mnt/pack/venv.tgz -C ~                    # → ~/creator_ai_demo/venv
tar -xzf /mnt/pack/rkllm-poc.tgz -C ~
tar -xzf /mnt/pack/sensevoice.tgz -C ~
tar -xzf /mnt/pack/dot-local.tgz -C ~
sudo cp /mnt/pack/librknnrt.so /usr/lib/ && sudo ldconfig
tar -xzf /mnt/pack/nodered-modules.tgz -C ~/av_unified_mvp/node-red
# config：system_config.yaml 被 gitignore，从金源机拷后按 §7 参数表改
scp proembed@<金源IP>:~/av_unified_mvp/config/system_config.yaml ~/av_unified_mvp/config/
```

> 离线机不需要 pip/npm/docker pull —— venv、node_modules、rootfs 都是成品。
> 注意 rootfs 里 `/etc/resolv.conf` 金源已写 223.5.5.5（离线机无所谓，不用改）。

## 3. funasr-server（脱 docker 化）

```bash
sudo cp ~/av_unified_mvp/deploy/systemd/funasr-server.service /etc/systemd/system/
# 换用户名时 sed（单元里 BindPaths/Documentation 硬编码 proembed）：
#   sudo sed -i "s|proembed|<用户名>|g" /etc/systemd/system/funasr-server.service
sudo systemctl daemon-reload && sudo systemctl enable --now funasr-server
# 就绪判定（模型已随资产包落盘，加载 ~30-40s，不用下载）：
for i in $(seq 1 90); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:10095/)" = "426" ] \
    && { echo "funasr ready (${i}s)"; break; }; sleep 1; done
```

⚠️ 单元里**禁止添加 DevicePolicy/DeviceAllow**——会触发同一个内核 BPF 缺失报错。
⚠️ 手工 chroot 调试时要先 `mount --bind /dev /opt/funasr-rootfs/dev`（服务本身靠
MountAPIVFS 不受影响），用完 umount。

## 4. 外部服务 + 麦克风

- mosquitto：`sudo apt install mosquitto`（离线机用资产包里的 deb 或出厂预装）→ `systemctl enable --now mosquitto`
- ollama（LLM CPU 回退，可选）：arm64 版 + `qwen2.5:7b`
- 麦克风/增益：`3588-demo-start.sh` §0.5 自动探卡写 `~/.asoundrc` + pulse 定 default source/增益，
  无需手配；增益值走 §7 参数表（env）
- `loginctl enable-linger <用户名>`（pulse 开机可用 + node-red user unit 自启的前提）

## 5. 开机自启单元

```bash
U=proembed   # 板子用户名
# av-demo（supervisor+模块+node-red 兜底）
sudo sed -e "s|firefly|$U|g" \
  -e "s|^After=.*|& user@1000.service funasr-server.service|" \
  -e "s|^Environment=PATH=|Environment=PATH=/home/$U/.local/node-v20.19.2-linux-arm64/bin:|" \
  ~/av_unified_mvp/deploy/systemd/av-demo.service > /tmp/av-demo.service
# 按 §7 参数表追加板级 env（PLAYBACK_CARD / MIC_PULSE_VOL / XDG_RUNTIME_DIR）：
sudo sed -i "/^Environment=PATH/a Environment=AV_PLAYBACK_CARD=2\nEnvironment=AV_MIC_PULSE_VOL=45%\nEnvironment=XDG_RUNTIME_DIR=/run/user/1000" /tmp/av-demo.service
sudo cp /tmp/av-demo.service /etc/systemd/system/

# funasr nightly 重启（防长跑卡死）：DNC 三处适配 = 路径、User=root、restart 命令
sudo sed -e "s|firefly|$U|g" -e "s|^User=.*|User=root|" \
  -e "/^\[Service\]/a Environment=AV_FUNASR_RESTART_CMD=systemctl restart funasr-server" \
  ~/av_unified_mvp/deploy/systemd/funasr-nightly-restart.service > /tmp/nr.service
# timer 时刻按板子时钟时区换算成"北京凌晨 04:23"（§0 记录的 date）：UTC 板 20:23 / CST 板 04:23
sudo sed -e "s|20:23:00|04:23:00|" ~/av_unified_mvp/deploy/systemd/funasr-nightly-restart.timer > /tmp/nr.timer
sudo cp /tmp/nr.service /etc/systemd/system/funasr-nightly-restart.service
sudo cp /tmp/nr.timer   /etc/systemd/system/funasr-nightly-restart.timer

# node-red user unit（repo flows）
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/node-red.service <<EOF
[Unit]
Description=Node-RED
After=network.target
[Service]
Type=simple
Environment=PATH=/home/$U/.local/node-v20.19.2-linux-arm64/bin:/home/$U/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=NODE_OPTIONS=--max_old_space_size=512
ExecStart=/home/$U/.local/node-v20.19.2-linux-arm64/bin/node-red --userDir /home/$U/av_unified_mvp/node-red
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload && systemctl --user enable node-red

sudo systemctl daemon-reload
sudo systemctl enable av-demo.service funasr-nightly-restart.timer
```

> node.js 二进制（`~/.local/node-v20.19.2-linux-arm64/`）也要进资产包（母亮装法），
> 或统一改装系统 node ≥18。

## 6. 板级参数表（每台机唯一要人工定的量）

| 参数 | 首台 DNC 值 | 怎么定 |
|---|---|---|
| 用户名 | proembed | 出厂即有 |
| `AV_PLAYBACK_CARD` | 2（ES8388） | `aplay -l` 找板载 codec |
| `AV_MIC_PULSE_VOL` | 45%（杂牌 webcam）/ 40%（C920） | 按麦标定：底噪 RMS < VAD 阈值 0.012 留余量，看 `[rms]` 日志 |
| nightly timer 时刻 | 04:23（CST 板） | 板子时钟时区换算北京凌晨 04:23 |
| mqtt client_id | av_box_dnc | config/system_config.yaml，每台唯一 |
| ASR backend | **不设**（脚本默认 funasr_2pass） | 回退 route B 时才设 `AV_ASR_BACKEND=sense_voice_arm` |

## 7. 验收清单（每台机，10min + 一次 reboot）

1. `systemctl is-active funasr-server` = active；`curl :10095` = 426
2. `bash ~/av_unified_mvp/scripts/3588-demo-start.sh --status` 全绿；dashboard :5050 = 200
3. `ss -tn | grep 10095` 有 ESTAB（audio_processor ws 已连）
4. 对麦说话：dashboard 灰词真流式蹦 → final 带标点整句修正；或无麦时用 rootfs 自带
   client 直验：`sudo mount --bind /dev /opt/funasr-rootfs/dev && sudo chroot /opt/funasr-rootfs
   /workspace/FunASR/runtime/websocket/build/bin/funasr-wss-client-2pass --server-ip 127.0.0.1
   --port 10095 --wav-path /tmp/test.wav --is-ssl 0; sudo umount /opt/funasr-rootfs/dev`
5. `sudo reboot` → 零人工：funasr-server 自起 → av-demo 等 426 拉 supervisor → ws ESTAB →
   node-red :1880（repo flows）→ pulse default source = USB 麦 @ 标定增益
6. `systemctl list-timers funasr-nightly-restart.timer` 有下次触发
7. 资源基线参考（首台实测）：funasr-server 常驻后整机 used ~5-7G / available ≥ 8G

## 8. 版本锚点与回退

- 引擎：`funasr-runtime-sdk-online-cpu-0.1.12`（rootfs 即此镜像导出，勿混版本）
- **复刻基准（2026-08-21 起）= `main` HEAD + 金源 62 的 `config/system_config.yaml`**。
  品牌已配置化（`brand: {name: Husion湖森, product: AI 视听理解平台, logo: husion.png}`，
  素材 `web/static/brand/husion.png` 在仓库内），形态/声源/摄像头/发言人区分等全部在 config，
  **代码不再按客户分支**。新板复刻：`git archive main` + 拷金源 config（§1 资产表同步改）。
  历史：7/14 湖森品牌验收态 tag `dnc-husion-brand-stable-20260714`（旧 husion-dnc 分支，已退役为
  `archive/husion-dnc-20260715`）仅作回滚参考，**不要从它复刻**——落后 main 60+ 提交（纪要/声纹/单路视频等都没有）。
  旧"三形态分支彼此独立"的红线随之作废：只有 main 一个分支，差异全在 config。
- 回退 route B（SenseVoice-NPU，无 funasr 时的降级链路）：
  `av-demo.service` 加回 `Environment=AV_ASR_BACKEND=sense_voice_arm` +
  `Environment=AV_RKNN_BACKEND=1` → daemon-reload → 重启 av-demo。
  代码层三处 sense_voice 适配（punctuated 补发/逐字蹦/仿 partial）都是 backend-gated，
  两条路线可随时互切。tag：`dnc-sensevoice-partial-stable-20260703`

## 9. 已知坑速查

- **docker 在 DNC 内核上永远起不了容器**（CONFIG_BPF_SYSCALL 未编）——别再试
  daemon.json/privileged，7/3 已逐一实测死。pull/create/export 可用（不经过 runc init）。
- 冷启动 pulse default source 会落板载 ES8388_Mic（无麦）→ 录全零。demo-start §0.5
  已修（显式扫 USB source 设 default），别绕过脚本手拉 supervisor。
- ssh 远程 pkill/pgrep -f 的 pattern 用 `[x]` 字符类防自匹配（否则可能把远端 shell 杀了
  且静默吞掉后续命令）。
- 板子时钟时区不统一（3588=UTC、首台 DNC=CST），凡涉及定时任务先 `date` 确认。
