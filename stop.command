#!/bin/bash
# av_unified_mvp 一键停止（macOS 双击运行）
cd "$(dirname "$0")"

PURPLE='\033[1;35m'; GREEN='\033[1;32m'; OFF='\033[0m'
say() { printf "${PURPLE}▸${OFF} %s\n" "$1"; }
ok()  { printf "${GREEN}✓${OFF} %s\n" "$1"; }

say "停止 main.py（含子模块 audio/video/llm/...）"
pkill -f "python3 main.py" 2>/dev/null && ok "main.py 已停" || ok "main.py 未在运行"

say "停止 Node-RED"
pkill -f "node-red" 2>/dev/null && ok "Node-RED 已停" || ok "Node-RED 未在运行"

say "停止 funasr-2pass 容器"
docker stop funasr-2pass >/dev/null 2>&1 && ok "容器已停" || ok "容器未在运行"

say "停止 mosquitto"
pkill -x mosquitto 2>/dev/null && ok "mosquitto 已停" || ok "mosquitto 未在运行"

echo ""
read -p "回车关闭窗口..." _
