#!/bin/bash
# Jetson 视觉深思 scene_analyzer 启动器
#
# 部署位置：~/av_scene/run.sh
# 开机自启：crontab `@reboot /home/jetson/av_scene/run.sh`（jetson 用户，无需 sudo）
# 日志：/tmp/sa.log
#
# 设计：
#   - 等 ollama(localhost) 就绪 → 等 broker(中控 3588) TCP 可达 → 才起 scene_analyzer
#   - 等 broker 是关键：crontab @reboot 早于网络 up，直接起会报 OSError 101
#     Network unreachable 崩溃（scene_analyzer 连 broker 失败不重试）。
#   - setsid 脱离会话，detached 起（不受启动它的 ssh/cron 退出影响）
#   - 重启脚本时别在外层命令里 pkill scene_analyzer.main：pkill -f 会匹配杀掉
#     运行该命令的 shell 自己（命令文本含同字串）。本脚本内部 pkill 安全。
set -u
BROKER_HOST="${AV_BROKER_HOST:-192.168.5.6}"
APP_DIR="${AV_APP_DIR:-$HOME/av_scene}"

pkill -9 -f scene_analyzer.main 2>/dev/null || true

# 等 ollama (本机 VLM 后端)
for _ in $(seq 1 60); do
    curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 2
done

# 等中控 broker 的网络路由就绪（开机竞态）
for _ in $(seq 1 90); do
    (echo > "/dev/tcp/${BROKER_HOST}/1883") 2>/dev/null && break
    sleep 2
done

sleep 2
cd "$APP_DIR" || exit 1
setsid python3 modules/scene_analyzer/main.py > /tmp/sa.log 2>&1 < /dev/null &
