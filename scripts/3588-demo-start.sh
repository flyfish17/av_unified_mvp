#!/bin/bash
# av_unified_mvp · RK3588 客户演示一键启动
#
# 在 3588 板子本机运行（user 双击 / SSH 进去 `bash ~/av_unified_mvp/scripts/3588-demo-start.sh`）。
# 目标：演示前 60s 内把 9 模块 + dashboard + Node-RED 拉起，输出"演示就绪 URL"。
#
# 设计原则：
#   - 不破坏既有进程：发现旧 supervisor 仍在跑 → 不重启，只报告状态（user 想强制重启加 --force）
#   - 显式 env：AV_LLM_BACKEND=rknn / AV_ASR_BACKEND=sense_voice_arm / AV_RKNN_BACKEND=0 (5/19 切 funasr CPU)
#     ASR 5/19 默认切 funasr CPU sensevoice — RKNN port 在低音量/短段会幻听单字"我"/韩语片段，
#     5/18 真音频回归实锤丢长句，funasr CPU 切回后 70 字长句完整。代价：audio_processor CPU
#     2%→107%（5x），3588 总负载吃紧但可承受。想切回 RKNN（experimental）：AV_RKNN_BACKEND=1 bash $0
#   - 30s 探活：循环 ping :5050 + 数 modules. 子进程，全在线才报"就绪"
#   - 失败兜底：单步失败打印修复建议，不静默挂起
#
# 用法：
#   bash scripts/3588-demo-start.sh             # 标准启动（旧进程在则跳过）
#   bash scripts/3588-demo-start.sh --force     # 强制 kill 旧 supervisor 再启
#   bash scripts/3588-demo-start.sh --status    # 只检查不启动
#
# 相关文档：docs/deploy/3588-demo-package.md（user 手册）/ docs/deploy/3588-npu.md § 11

set -u  # 未定义变量报错；不开 -e（每步自检）

# ── 配置 ──────────────────────────────────────────────────────────────
PROJECT_DIR="${AV_PROJECT_DIR:-$HOME/av_unified_mvp}"
VENV_PY="${AV_VENV_PY:-$HOME/creator_ai_demo/venv/bin/python}"
LOG_FILE="${AV_LOG_FILE:-/tmp/main_supervisor.log}"
DASHBOARD_PORT="${AV_DASHBOARD_PORT:-5050}"
MJPEG_PORT="${AV_MJPEG_PORT:-5051}"
EXPECTED_MODULES=9   # audio video llm system network scanner husion control_dispatch keyframe_filter
WAIT_SECONDS="${AV_WAIT_SECONDS:-45}"

# ── 颜色 ──────────────────────────────────────────────────────────────
PURPLE='\033[1;35m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; CYAN='\033[1;36m'; OFF='\033[0m'
say()  { printf "${PURPLE}▸${OFF} %s\n" "$1"; }
ok()   { printf "${GREEN}✓${OFF} %s\n" "$1"; }
warn() { printf "${YELLOW}!${OFF} %s\n" "$1"; }
fail() { printf "${RED}✗${OFF} %s\n" "$1"; }
hdr()  { printf "\n${CYAN}═══ %s ═══${OFF}\n" "$1"; }

# ── 参数 ──────────────────────────────────────────────────────────────
FORCE=0
STATUS_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --force)  FORCE=1 ;;
        --status) STATUS_ONLY=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) warn "未知参数 $arg（忽略）" ;;
    esac
done

# ── 0. 基本环境 ───────────────────────────────────────────────────────
hdr "0. 环境自检"
[ -d "$PROJECT_DIR" ] || { fail "项目目录不存在: $PROJECT_DIR"; exit 1; }
[ -x "$VENV_PY" ] || { fail "venv python 不存在或不可执行: $VENV_PY"; exit 1; }
[ -f "$PROJECT_DIR/main.py" ] || { fail "main.py 不在 $PROJECT_DIR"; exit 1; }
ok "项目目录: $PROJECT_DIR"
ok "venv 解释器: $VENV_PY"

# 关键 NPU 资源
[ -e /dev/dri/renderD129 ] || warn "/dev/dri/renderD129 不存在 — 板子可能不是 RK3588"
[ -f "$HOME/SenseVoiceSmall-RKNN2/sense-voice-encoder.rknn" ] \
    || warn "SenseVoice RKNN 模型未找到 — ASR 会回退到 CPU"
[ -f "$HOME/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm" ] \
    || warn "RKLLM 模型未找到 — LLM 会回退到 ollama CPU"

# ── 1. 外部依赖（mosquitto / ollama / Node-RED） ────────────────────────
hdr "1. 外部服务"

# mosquitto
if pgrep -x mosquitto >/dev/null 2>&1; then
    ok "mosquitto 已在跑（PID=$(pgrep -x mosquitto | head -1)）"
else
    warn "mosquitto 未运行，尝试启动..."
    if command -v mosquitto >/dev/null 2>&1; then
        mosquitto -c /etc/mosquitto/mosquitto.conf -d 2>/dev/null \
            || sudo systemctl start mosquitto 2>/dev/null \
            || { fail "mosquitto 启动失败 — 手动: sudo systemctl start mosquitto"; exit 1; }
        sleep 1
        ok "mosquitto 已启动"
    else
        fail "mosquitto 未安装 — sudo apt install mosquitto"; exit 1
    fi
fi

# ollama (CPU fallback for LLM)
if curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "ollama 已在跑（11434）"
else
    warn "ollama 未响应 — 尝试启动..."
    if command -v ollama >/dev/null 2>&1; then
        nohup ollama serve >/tmp/ollama.log 2>&1 &
        for i in $(seq 1 15); do
            curl -s --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
            sleep 1
        done
        curl -s --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
            && ok "ollama 已启动" || warn "ollama 启动超时 — LLM CPU 回退路径可能不可用"
    else
        warn "ollama 未安装 — NPU 路径优先，但回退路径不可用"
    fi
fi

# Node-RED（可选）
if pgrep -f "node-red" >/dev/null 2>&1; then
    ok "Node-RED 已在跑"
else
    if command -v node-red >/dev/null 2>&1; then
        warn "Node-RED 未运行，尝试启动..."
        cd "$PROJECT_DIR" && mkdir -p node-red
        nohup node-red --userDir "$PROJECT_DIR/node-red" --port 1880 \
            >> "$PROJECT_DIR/node-red/node-red.log" 2>&1 &
        sleep 2
        pgrep -f "node-red" >/dev/null 2>&1 \
            && ok "Node-RED 已启动（PID=$(pgrep -f node-red | head -1)）" \
            || warn "Node-RED 启动失败 — dashboard 编程 tab 会显示 fallback"
    else
        warn "Node-RED 未安装 — npm i -g node-red（dashboard 编程 tab 显示 fallback）"
    fi
fi

# ── 2. supervisor 状态 ────────────────────────────────────────────────
hdr "2. main.py supervisor"

EXISTING_PID="$(pgrep -f "${VENV_PY}.*main\.py$" | head -1)"
if [ -n "$EXISTING_PID" ]; then
    ETIME="$(ps -o etime= -p "$EXISTING_PID" 2>/dev/null | tr -d ' ')"
    if [ "$STATUS_ONLY" = "1" ]; then
        ok "supervisor 已在跑 (PID=$EXISTING_PID, 运行 $ETIME)"
    elif [ "$FORCE" = "1" ]; then
        warn "--force：杀掉旧 supervisor PID=$EXISTING_PID"
        kill -TERM "$EXISTING_PID" 2>/dev/null
        for i in $(seq 1 10); do
            kill -0 "$EXISTING_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$EXISTING_PID" 2>/dev/null && { kill -KILL "$EXISTING_PID"; sleep 2; }
        # 残留 module 子进程（如有）
        pkill -f "${VENV_PY}.*-m modules\\." 2>/dev/null
        sleep 2
        EXISTING_PID=""
    else
        ok "supervisor 已在跑 (PID=$EXISTING_PID, 运行 $ETIME)"
        warn "  → 想重启：bash $0 --force"
    fi
fi

if [ -z "$EXISTING_PID" ] && [ "$STATUS_ONLY" != "1" ]; then
    AV_RKNN_BACKEND="${AV_RKNN_BACKEND:-0}"
    say "启动 supervisor（AV_LLM_BACKEND=rknn / AV_ASR_BACKEND=sense_voice_arm / AV_RKNN_BACKEND=$AV_RKNN_BACKEND）"
    cd "$PROJECT_DIR" || { fail "cd $PROJECT_DIR 失败"; exit 1; }
    # 轮换旧日志：保留 5 份历史
    if [ -f "$LOG_FILE" ]; then
        mv "$LOG_FILE" "${LOG_FILE}.$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
        ls -1t "${LOG_FILE}".* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
    fi
    AV_LLM_BACKEND=rknn \
    AV_ASR_BACKEND=sense_voice_arm \
    AV_RKNN_BACKEND="$AV_RKNN_BACKEND" \
    nohup "$VENV_PY" main.py > "$LOG_FILE" 2>&1 &
    sleep 2
    NEW_PID="$(pgrep -f "${VENV_PY}.*main\.py$" | head -1)"
    [ -n "$NEW_PID" ] && ok "supervisor 已拉起 (PID=$NEW_PID, log=$LOG_FILE)" \
                     || { fail "supervisor 启动失败 — 看 $LOG_FILE"; tail -30 "$LOG_FILE"; exit 1; }
fi

# ── 3. 等待 dashboard + 模块上线 ──────────────────────────────────────
hdr "3. 等待 dashboard 就绪（最多 ${WAIT_SECONDS}s）"

READY=0
for i in $(seq 1 "$WAIT_SECONDS"); do
    HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${DASHBOARD_PORT}/" 2>/dev/null || echo 000)"
    MODULE_COUNT="$(pgrep -f "${VENV_PY}.*-m modules\\." 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$HTTP_CODE" = "200" ] && [ "$MODULE_COUNT" -ge "$EXPECTED_MODULES" ]; then
        READY=1
        break
    fi
    printf "  %02ds  HTTP=%s  modules=%s/%s\n" "$i" "$HTTP_CODE" "$MODULE_COUNT" "$EXPECTED_MODULES"
    sleep 1
done

# ── 4. 最终报告 ────────────────────────────────────────────────────────
hdr "4. 演示就绪状态"

HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${DASHBOARD_PORT}/" 2>/dev/null || echo 000)"
MODULE_COUNT="$(pgrep -f "${VENV_PY}.*-m modules\\." 2>/dev/null | wc -l | tr -d ' ')"
RKLLM_PID="$(pgrep -f "rkllm_daemon\\.py" | head -1)"
SENSEVOICE_PID="$(pgrep -f "sensevoice_rknn_daemon\\.py" | head -1)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$IP" ] && IP="192.168.5.6"

printf "  Dashboard HTTP   : %s\n" "$HTTP_CODE"
printf "  Module 子进程    : %s / %s\n" "$MODULE_COUNT" "$EXPECTED_MODULES"
printf "  RKLLM daemon     : %s\n" "${RKLLM_PID:-未运行（首次 av/llm/command 会按需拉起）}"
printf "  SenseVoice daemon: %s\n" "${SENSEVOICE_PID:-未运行（audio_processor 拉起后才会出现）}"

if [ "$READY" = "1" ]; then
    printf "\n${GREEN}═══════════════════════════════════════════════${OFF}\n"
    printf "${GREEN}  ✓ 演示就绪${OFF}\n"
    printf "${GREEN}═══════════════════════════════════════════════${OFF}\n"
    printf "  主 dashboard : ${CYAN}http://%s:%s${OFF}\n" "$IP" "$DASHBOARD_PORT"
    printf "  视频 MJPEG   : http://%s:%s\n" "$IP" "$MJPEG_PORT"
    printf "  Node-RED     : http://%s:1880\n" "$IP"
    printf "  日志         : tail -f %s\n" "$LOG_FILE"
    printf "\n  下一步：\n"
    printf "    1) 浏览器打开主 dashboard\n"
    printf "    2) 顶部「演示按钮」区点击预设句式（销售指着说）\n"
    printf "    3) 或对着麦克风说「开研发部空调」等\n"
    exit 0
else
    printf "\n${YELLOW}═══════════════════════════════════════════════${OFF}\n"
    printf "${YELLOW}  ! 部分就绪，需排查${OFF}\n"
    printf "${YELLOW}═══════════════════════════════════════════════${OFF}\n"
    if [ "$HTTP_CODE" != "200" ]; then
        printf "  → Dashboard :%s 不通\n" "$DASHBOARD_PORT"
        printf "    可能：端口被占（ss -tlnp | grep :%s）或 Flask 启动失败\n" "$DASHBOARD_PORT"
        printf "    看日志：tail -50 %s | grep -E 'Flask|Address|演示页'\n" "$LOG_FILE"
    fi
    if [ "$MODULE_COUNT" -lt "$EXPECTED_MODULES" ]; then
        printf "  → 模块 %s/%s 上线，等 30s 再看（exp backoff 重拉）\n" "$MODULE_COUNT" "$EXPECTED_MODULES"
        printf "    pgrep -af 'modules\\.' | grep -v grep\n"
    fi
    printf "  主 dashboard : http://%s:%s （能否打开看上面）\n" "$IP" "$DASHBOARD_PORT"
    exit 2
fi
