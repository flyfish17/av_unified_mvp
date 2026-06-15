# RK3588 新机器安装流程（A→Z 复现清单）

> 用途：从一块空白 / 新克隆的 RK3588 板子，装到「上电自动恢复到当前演示状态」。
> 这是**总装清单**，重活引用既有文档，只在这里补齐两块盲点：funasr 容器 + systemd 自启。
>
> ⚠️ ASR 路径已变更：线上 2026-05-19 起切 **funasr_2pass（CPU docker）**，
> `3588-npu.md` § 11 里的 `AV_ASR_BACKEND=sense_voice_arm` / `AV_RKNN_BACKEND=1` 已过时，
> 以 `scripts/3588-demo-start.sh` 实际 env 为准（funasr 路径）。SenseVoice-RKNN 仅作备选保留。

约定：板子用户名 `firefly`，IP 段示例 `192.168.5.6`，板子系统时钟为 **UTC**。

---

## 1. 基础环境（引用 3588-npu.md）

按 `3588-npu.md` § 1–10 完成 NPU 驱动 / docker / 模型与 daemon 部署：

- `~/av_unified_mvp/`（本仓库，`git clone` + checkout 当前分支）
- `~/creator_ai_demo/venv/`（demo 自带 venv，含 torch/paho-mqtt/numpy 等）
- `~/rkllm-poc/`（LLM daemon + Qwen2.5-1.5B `.rkllm` 权重，NPU LLM 路径）
- mosquitto / ollama / Node-RED（外部服务，`3588-demo-start.sh` 会按需拉起）

补 av_unified_mvp 需要、demo venv 没有的 3 个包：

```bash
~/creator_ai_demo/venv/bin/pip install flask opencv-python-headless ultralytics
```

## 2. ASR：funasr_2pass 容器（CPU）

线上 ASR 后端。手工 `docker run` 起，无 compose。镜像走阿里云 mirror。

```bash
# 2.1 模型挂载目录（首次 run 时 run_server_2pass.sh 自动下载到这里）
mkdir -p /home/firefly/funasr-models

# 2.2 起容器（restart=unless-stopped → 重启随 docker 自启）
docker run -d --name funasr --restart unless-stopped \
  -p 10095:10095 \
  -v /home/firefly/funasr-models:/workspace/models \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.12 \
  bash -c "cd /workspace/FunASR/runtime && bash run_server_2pass.sh --certfile 0 2>&1 | tee /workspace/server.log"

# 2.3 首次拉模型(paraformer+vad+punc+lm+itn)需数分钟，等就绪(ws 端口应答 HTTP 426)
for i in $(seq 1 300); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:10095/)" = "426" ] \
    && { echo "funasr ready (${i}s)"; break; }
  sleep 1
done
```

模型已就位的板子可直接复用 `/home/firefly/funasr-models`（damo/ + thuduj12/），跳过下载。

## 3. 麦克风默认录音设备

板载 codec(card0) 无麦，USB 麦(C920)在 card2。`3588-demo-start.sh` § 0.5 启动时会**动态探测 USB 麦卡号并写 `~/.asoundrc`**，新机无需手动配置——只要插了 C920 即可。详见 [[3588-funasr-mic-default-device]] 记录的坑。

## 4. 开机自启（systemd）—— 重启恢复的关键

unit 文件已版本化在 `deploy/systemd/`。**这是「reboot 恢复当前状态」的全部依赖。**

```bash
sudo cp ~/av_unified_mvp/deploy/systemd/av-demo.service \
        ~/av_unified_mvp/deploy/systemd/funasr-nightly-restart.service \
        ~/av_unified_mvp/deploy/systemd/funasr-nightly-restart.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now av-demo.service            # 上电拉起 supervisor+模块+node-red
sudo systemctl enable --now funasr-nightly-restart.timer  # 每日 UTC20:23 重启 funasr 防卡死
```

unit 路径硬编码 `/home/firefly/...`，换用户名需同步改三个文件。

## 5. 验收

```bash
systemctl is-enabled av-demo.service funasr-nightly-restart.timer   # 均应 enabled
systemctl list-timers funasr-nightly-restart.timer                  # 看下次触发 UTC20:23
docker ps                                                           # funasr unless-stopped, Up
curl -s http://192.168.5.6:5050 -o /dev/null -w '%{http_code}\n'    # dashboard 200
# 对着 C920 说话 → 看转写
grep '\[final\]' /tmp/main_supervisor.log | tail
```

**重启恢复验证**（确认窗口期再做）：`sudo reboot` 后，docker 自动起 funasr（unless-stopped）→ av-demo.service 等 funasr 就绪后拉起 supervisor → nightly timer 随 timers.target 恢复。三者均 `enabled`，重启即恢复到当前状态。

---

## 关联

- 基础部署：`3588-npu.md` § 1–11
- 演示当天 ops：`3588-demo-package.md`
- funasr 长跑卡死 + 每日重启方案：`scripts/3588-funasr-nightly-restart.sh` 头注释
