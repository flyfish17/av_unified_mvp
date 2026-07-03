#!/usr/bin/env bash
# 3588 funasr 每日凌晨重启 — 防长跑卡死
#
# 背景（2026-06-12 实锤）：funasr-wss-server-2pass 连跑 2-3 天后会出现单解码线程
# 死循环（单核 100%、不再产出结果），且内存涨到 7.4G。io 线程仍应答 ws ping，
# audio_processor 感知不到、不触发重连 → 转写静默停摆。
# 不做"无输出检测"：夜间静音与卡死无法区分，误判率高；每日重启余量足够。
#
# 顺序硬约束：funasr 重启加载模型 ~30-40s，而 audio_processor 的 ws 重连只试
# 5 次（~30s）就永久降级 local_offline（modules/audio_processor/processor.py
# _supervise_ws）。所以必须：先等 funasr 就绪，再 kill audio_processor 让
# main.py supervisor 重拉、重新连接。
#
# 部署：板子没装 cron，用 systemd timer（2026-06-12 已装）：
#   /etc/systemd/system/funasr-nightly-restart.{service,timer}
#   每日 UTC 20:23（板子时钟 UTC，= 北京凌晨 04:23），日志 /tmp/funasr-nightly-restart.log
#   状态：systemctl list-timers funasr-nightly-restart.timer

set -u

say() { echo "[$(date '+%F %T')] $*"; }

say "== funasr 每日重启开始 =="

# 1. 重启 funasr（3588=docker 容器；DNC 等无 CGROUP_BPF 内核机型=脱 docker 化
#    systemd 服务，由 nightly-restart.service 的 Environment 覆盖此命令）
RESTART_CMD="${AV_FUNASR_RESTART_CMD:-docker restart funasr}"
$RESTART_CMD || { say "FATAL: $RESTART_CMD 失败"; exit 1; }
say "funasr 已重启（$RESTART_CMD），等待就绪…"

# 2. 等 ws 端口就绪（就绪时 HTTP 426，同 3588-demo-start.sh §1.5），上限 120s 留余量
FUNASR_READY=0
for i in $(seq 1 120); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:10095/ 2>/dev/null || echo 000)"
    if [ "$code" = "426" ]; then FUNASR_READY=1; say "funasr 就绪（等待 ${i}s）"; break; fi
    sleep 1
done
if [ "$FUNASR_READY" != "1" ]; then
    say "FATAL: funasr 120s 未就绪，不动 audio_processor（保持现状，人工排查）"
    exit 1
fi

# 3. kill audio_processor → supervisor 自动重拉并重连 funasr
OLD_PID="$(pgrep -f 'modules\.audio_processor\.main' | head -1)"
if [ -z "$OLD_PID" ]; then
    say "WARN: 未发现 audio_processor 进程（supervisor 没在跑？），跳过"
    exit 1
fi
kill -TERM "$OLD_PID"
say "已 kill audio_processor (PID=$OLD_PID)，等待 supervisor 重拉…"

# 4. 验证：新进程起来且 ws 连上 funasr（最多 60s）
for i in $(seq 1 60); do
    NEW_PID="$(pgrep -f 'modules\.audio_processor\.main' | head -1)"
    if [ -n "$NEW_PID" ] && [ "$NEW_PID" != "$OLD_PID" ] \
       && ss -tnp 2>/dev/null | grep -q "127.0.0.1:10095.*pid=${NEW_PID}"; then
        say "OK: audio_processor 已重拉 (PID=$NEW_PID) 且 ws 已连 funasr"
        say "== funasr 每日重启完成 =="
        exit 0
    fi
    sleep 1
done

say "FATAL: 60s 内 audio_processor 未重连 funasr（可能已降级 local_offline），需人工排查"
exit 1
