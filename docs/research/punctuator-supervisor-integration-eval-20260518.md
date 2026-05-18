# Punctuator 进 supervisor 管理 — 集成评估

**日期**：2026-05-18
**背景**：P1.1 punctuator 当前跑在 3588 独立 spike_venv（`/home/firefly/spike_venv_20260518/`），nohup 启动，崩溃无自动重拉。要 production-ready 需进 supervisor。

---

## 核心挑战

- **依赖位置**：punctuator 需要 sherpa-onnx 1.13.2 (aarch64) + ct-punc 模型，仅装在 spike_venv
- **红线**：`/home/firefly/creator_ai_demo/venv/` 是 audio_processor / video_processor / sensevoice RKNN 共享的关键 venv，不能动（不能装新依赖、不能改 site-packages）
- supervisor 当前 `_spawn` 用 `sys.executable -m <module>` — `sys.executable` 是 supervisor 自己的 Python = creator_ai_demo/venv 的 python，不带 sherpa-onnx

---

## 方案矩阵

| 方案 | 改动 | 红线 | 维护成本 | 推荐 |
|---|---|---|---|---|
| **A · supervisor per-module Python override** | ~20 行 main.py | ✅ | 低 | **⭐ 推荐** |
| B · systemd user service 独立跑 punctuator | 1 个 .service 文件 | ✅ | 中（双管理系统）| 备选 |
| C · bash `while true; do ...; done` watchdog | 1 个 shell 脚本 | ✅ | 简陋（脚本崩没人救）| × |
| D · 装 sherpa-onnx 到 creator_ai_demo/venv | 0 行 | ❌ 破红线 | 0（但风险高）| × |

---

## 方案 A 实施草案

### main.py 改动（surgical）

```python
MANAGED_MODULES = [
    "modules.audio_processor.main",
    "modules.video_processor.main",
    # ... 其它 8 个 string 形式保留 ...
    {
        "module": "modules.punctuator.main",
        "python": "/home/firefly/spike_venv_20260518/bin/python",
        "env": {"AV_PUNCT_MODEL": "/home/firefly/spike_venv_20260518/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8/model.int8.onnx"},
    },
]

@staticmethod
def _spec_name(spec):
    return spec["module"] if isinstance(spec, dict) else spec

@staticmethod
def _spec_python(spec):
    return spec.get("python", sys.executable) if isinstance(spec, dict) else sys.executable

@staticmethod
def _spec_extra_env(spec):
    return spec.get("env", {}) if isinstance(spec, dict) else {}

def _spawn(self, spec) -> subprocess.Popen:
    module = self._spec_name(spec)
    python = self._spec_python(spec)
    env = os.environ.copy()
    env.update(self._spec_extra_env(spec))
    proc = subprocess.Popen([python, "-m", module], cwd=str(self._project_root), env=env)
    self.logger.info(f"[supervisor] 拉起 {module} (PID={proc.pid}, python={python})")
    return proc

def _spawn_all(self):
    now = time.time()
    for spec in MANAGED_MODULES:
        name = self._spec_name(spec)
        proc = self._spawn(spec)
        self._procs[name] = {"proc": proc, "spec": spec, ...}  # spec 留着 retry 时用

def _tick(self):
    ...
    proc = self._spawn(state["spec"])  # retry 时用 spec 而非 module name
```

**改动范围**：
- `MANAGED_MODULES` 加一个 dict 条目
- 3 个 staticmethod helper
- `_spawn` 签名 + body
- `_spawn_all` 字典 key 用 module name
- `_tick` 重拉时 spec

### 风险点

1. **spike_venv 重建**：换设备部署或 spike_venv 误删 → punctuator 起不来 → supervisor 重拉死循环。
   - **缓解**：spike_venv 创建脚本化（`scripts/setup_spike_venv.sh`），文档化为部署 prerequisite
2. **退避保护**：supervisor 已有 `WARN_AFTER_FAILS=5` 退避机制（main.py:69）。如果 sherpa-onnx 没装 punctuator 必崩，会触发持续 ERROR log，不会真"死循环占资源"
3. **3588 main.py 本地修改**：3588 上 main.py 已和本地 git 同步（5/18 P1.3 时 scp 过去），但用户**仍未 git commit**。再 patch main.py 要继续走 scp + 重启 supervisor 流程

### 收益

- punctuator 崩溃自动重拉（与其它 10 模块一致体验）
- dashboard discovery 把 punctuator 当一等公民显示（LWT offline 自动可见）
- 不再依赖手动 nohup → 文档简化、新人接手成本下降
- 不破红线（sherpa-onnx 仍在 spike_venv 隔离）

---

## 方案 A 不立即做的理由（如果保留现状）

- spike 阶段产品形态尚未冻结：可能后续 punctuator 还要扩字段（说话人 tag 关联、原文+带标点双路径）
- 当前 nohup + monitor 模式调试效率高（手动重启快）
- 进 supervisor 后想改 punctuator 必须 supervisor 重启 → 影响其它 10 模块短暂不可用

---

## 推荐执行节奏

**当前阶段**（spike + dashboard 验证期）：保持 nohup，提高 punctuator 迭代效率

**触发点**：以下任一发生时立即转方案 A
1. punctuator schema 稳定（连续 3 天无字段改动）
2. P0.9 Phase B 通过 + speaker_tagger 立项（再多一个 sidekick，手动管两个 nohup 已显累赘）
3. 接近客户演示（须保证崩溃自动重拉）

**实施工时估算**：方案 A 一次完整改动 + 测试 ≈ 1-2h（含 supervisor 重启验证）

---

## 备选方案 B（systemd 兜底）

如果方案 A 因任何原因被否，方案 B 是次选：

`~/.config/systemd/user/punctuator.service`：
```ini
[Unit]
Description=av_unified_mvp punctuator (ct-punc sidecar)
After=mosquitto.service

[Service]
WorkingDirectory=/home/firefly/av_unified_mvp
ExecStart=/home/firefly/spike_venv_20260518/bin/python -m modules.punctuator.main
Restart=always
RestartSec=5
StandardOutput=append:/tmp/punctuator.log
StandardError=append:/tmp/punctuator.log

[Install]
WantedBy=default.target
```

`systemctl --user enable --now punctuator` 即可。注意：3588 user 是否启用了 lingering（`loginctl enable-linger firefly`）决定开机自启是否生效——需 sudo，**所以方案 B 仍卡 3588 无 sudo 红线**。方案 A 仍优。
