#!/bin/bash
# av_unified_mvp 一键启动（macOS 双击运行）
# 顺序：profile 探测 → mosquitto → (按需)funasr-2pass 容器 → 浏览器 → main.py
set -e
cd "$(dirname "$0")"

# 让本机请求绕开系统代理（Clash 之类的会把 127.0.0.1:11434 ollama 请求也代理出去）
export NO_PROXY="127.0.0.1,localhost,::1"
export no_proxy="127.0.0.1,localhost,::1"

# 防止重复双击：已有 main.py 跑着就提示退出
EXISTING=$(pgrep -f "[Pp]ython.*main\.py" || true)
if [ -n "$EXISTING" ]; then
    printf "\033[1;33m!\033[0m main.py 已在运行 (PID: $EXISTING)\n"
    printf "  → 想看那个窗口的日志：直接切到原来的 Terminal\n"
    printf "  → 想重启：先 ./stop.command 再来双击\n"
    read -p "回车关闭..." _
    exit 0
fi

PURPLE='\033[1;35m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; OFF='\033[0m'
say() { printf "${PURPLE}▸${OFF} %s\n" "$1"; }
ok()  { printf "${GREEN}✓${OFF} %s\n" "$1"; }
warn(){ printf "${YELLOW}!${OFF} %s\n" "$1"; }
die() { printf "${RED}✗${OFF} %s\n" "$1"; read -p "回车关闭..." _; exit 1; }

# ── 1. 性能档位 ─────────────────────────────────────────────────
PROFILE=$(grep -E '^\s*performance_profile:' config/system_config.yaml 2>/dev/null | awk '{print $2}')
PROFILE=${PROFILE:-medium}
say "性能档位: $PROFILE  （改 config/system_config.yaml 的 performance_profile 切档）"

# ── 2. mosquitto ────────────────────────────────────────────────
say "MQTT broker (mosquitto)"
if pgrep -x mosquitto >/dev/null; then
    ok "已在运行"
else
    MOSQ_CONF="/opt/homebrew/etc/mosquitto/mosquitto.conf"
    [ -f "$MOSQ_CONF" ] || die "找不到 $MOSQ_CONF —— 请先 brew install mosquitto"
    mosquitto -c "$MOSQ_CONF" -d
    sleep 1
    ok "已启动 (port 1883)"
fi

# ── 3. funasr-2pass 容器（仅 medium / heavy 档需要）────────────
if [ "$PROFILE" = "light" ]; then
    say "FunASR"
    ok "light 档使用本地 SenseVoiceSmall，无需 Docker"
else
    say "FunASR 2pass 容器"
    if ! docker info >/dev/null 2>&1; then
        warn "Docker 未运行 → 临时降级到 light 档（本地 SenseVoiceSmall，按句切段，无 partial）"
        warn "  想恢复 medium 档：打开 Docker Desktop 后再次双击 start.command"
        # 通过环境变量临时覆盖，不写回 config/system_config.yaml（避免 silently 改用户配置）
        export AV_PROFILE_OVERRIDE=light
        PROFILE=light
        ok "已切 light 档，继续启动"
    fi
fi
if [ "$PROFILE" != "light" ]; then
    if [ -z "$(docker ps -q -f name=funasr-2pass)" ]; then
        if [ -z "$(docker ps -aq -f name=funasr-2pass)" ]; then
            warn "容器不存在，首次创建（会下载 ~3GB 模型，5-10 分钟）"
            mkdir -p ~/funasr-runtime-resources/models
            # 关键：用 wait $SERVER_PID 让容器主进程绑定 server 生命周期。
            # server crash → 容器退出 → --restart 自动拉起，避免"端口在但服务死"。
            # 离线友好：MODELSCOPE_DOMAIN= 阻止 modelscope 库做版本探测（funasr 二进制内部调 modelscope SDK）。
            # 注意：run_server_2pass.sh 用 parse_options.sh 严格解析参数，--disable-update 不在白名单会 exit 1，所以只走 env 这一条路。
            docker run -d --name funasr-2pass \
                -p 10095:10095 --privileged=true --memory=2.5g --restart unless-stopped \
                -e MODELSCOPE_DOMAIN= \
                -v ~/funasr-runtime-resources/models:/workspace/models \
                --workdir /workspace/FunASR/runtime \
                registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.12 \
                bash -c 'bash run_server_2pass.sh --download-model-dir /workspace/models --certfile 0 --lm-dir "" --decoder-thread-num 4 >> /workspace/server.log 2>&1
                    # run_server_2pass.sh 用 & 启动 server 后立即返回。轮询 server 进程，存活即陪跑，死亡即退出容器，靠 --restart 自动拉起。
                    # 注意：/proc/PID/comm 截断到 15 字符，所以 server 真实 comm 是 "funasr-wss-serv"。
                    SERVER_PID=""
                    for i in $(seq 1 180); do
                        SERVER_PID=$(pgrep -x funasr-wss-serv | head -1)
                        [ -n "$SERVER_PID" ] && break
                        sleep 1
                    done
                    if [ -z "$SERVER_PID" ]; then
                        echo "supervisor: server not found within 180s" >> /workspace/server.log
                        exit 1
                    fi
                    echo "supervisor: tracking server pid $SERVER_PID" >> /workspace/server.log
                    while kill -0 $SERVER_PID 2>/dev/null; do
                        sleep 5
                    done
                    echo "supervisor: server pid $SERVER_PID exited; container exiting for --restart" >> /workspace/server.log
                    exit 1'
        else
            # 旧容器自检：缺 MODELSCOPE_DOMAIN= 说明是 P0 残留前创建的，提示重建
            if ! docker inspect funasr-2pass --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -q '^MODELSCOPE_DOMAIN='; then
                warn "现有容器是旧参数创建的（无 MODELSCOPE_DOMAIN= 离线探测保护）"
                warn "  → 想应用新参数：docker rm -f funasr-2pass && 再次双击本脚本"
                warn "  → 模型缓存挂在 ~/funasr-runtime-resources/models（volume），重建不丢"
            fi
            docker start funasr-2pass >/dev/null
        fi
    fi
    printf "  等待 10095 就绪 "
    for i in $(seq 1 120); do
        if nc -z 127.0.0.1 10095 2>/dev/null; then
            printf "\n"; ok "FunASR 已就绪"; break
        fi
        printf "."; sleep 1
    done
    nc -z 127.0.0.1 10095 2>/dev/null || die "FunASR 启动超时，看日志: docker logs funasr-2pass"
fi

# ── 4. Node-RED（可选；编辑器嵌在 dashboard 的"编程" tab）──────
say "Node-RED (端口 1880)"
NR_PID=""
# 用户级 npm prefix 的常见位置（npm config set prefix ~/.npm-global 时）
[ -d "$HOME/.npm-global/bin" ] && export PATH="$HOME/.npm-global/bin:$PATH"
if pgrep -f "node-red" >/dev/null; then
    ok "已在运行（不重起）"
elif command -v node-red >/dev/null 2>&1; then
    mkdir -p node-red
    node-red --userDir ./node-red --port 1880 >> node-red/node-red.log 2>&1 &
    NR_PID=$!
    # 等就绪（最多 120s）— iCloud 路径冷启动加载 palette+flows 实测 ~50s
    for i in $(seq 1 240); do
        nc -z 127.0.0.1 1880 2>/dev/null && break
        sleep 0.5
    done
    if nc -z 127.0.0.1 1880 2>/dev/null; then
        ok "已启动 PID=$NR_PID  (日志: node-red/node-red.log)"
    else
        warn "Node-RED 启动超时（120s）；进程可能仍在加载，稍后手动刷新"
    fi
else
    warn "未找到 node-red 命令（npm i -g node-red 后再启动），跳过"
fi

# Ctrl+C / 退出时一并清理 Node-RED
cleanup() {
    if [ -n "$NR_PID" ] && kill -0 "$NR_PID" 2>/dev/null; then
        kill "$NR_PID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

# ── 5. 浏览器 + 主程 ───────────────────────────────────────────
say "打开浏览器 + 启动 main.py"
( sleep 2 && open "http://localhost:5050" ) &
python3 main.py
# main.py 退出后会触发 trap cleanup 清理 Node-RED
