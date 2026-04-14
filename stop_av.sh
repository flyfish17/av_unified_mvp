#!/bin/bash
# AV统一系统 - 停止脚本
cd "$(dirname "$0")"

PIDFILE="/tmp/av_unified.pid"

if [ ! -f "$PIDFILE" ]; then
    # 兜底：杀掉所有相关进程
    pkill -f "python3 main.py" 2>/dev/null
    pkill -f "streamlit run.*dashboard" 2>/dev/null
    echo "[提示] 无PID文件，已尝试kill相关进程"
    exit 0
fi

echo "停止AV统一系统..."

# 读取并停止所有PID
while read pid; do
    if kill -0 "$pid" 2>/dev/null; then
        echo "  停止 PID $pid..."
        kill "$pid" 2>/dev/null
    fi
done < "$PIDFILE"

rm -f "$PIDFILE"
echo "[OK] 已停止"
