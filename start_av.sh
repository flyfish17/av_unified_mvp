#!/bin/bash
# AV统一系统 - 启动脚本
cd "$(dirname "$0")"

PIDFILE="/tmp/av_unified.pid"
LOGFILE="/tmp/av_unified.log"

# 停止已有进程
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "停止旧进程 (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$PIDFILE"
fi

echo "=========================================="
echo "  AV统一系统启动中..."
echo "=========================================="

# 检查依赖
python3 -c "import cv2, yaml, paho.mqtt, ultralytics" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[安装依赖]..."
    pip3 install opencv-python pyyaml paho-mqtt ultralytics --break-system-packages -q
fi

# 启动主程序
echo "[启动] 主程序 (main.py)..."
nohup python3 main.py > "$LOGFILE" 2>&1 &
MAIN_PID=$!
echo $MAIN_PID > "$PIDFILE"
sleep 2

if ! kill -0 "$MAIN_PID" 2>/dev/null; then
    echo "[错误] 主程序启动失败"
    cat "$LOGFILE"
    exit 1
fi

echo "[OK] 主程序已启动 (PID $MAIN_PID)"

# 启动Streamlit Web界面
echo "[启动] Web界面 (streamlit)..."
nohup streamlit run ui/dashboard.py --server.port 8501 --browser.gatherUsageStats false > /tmp/av_streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo $STREAMLIT_PID >> "$PIDFILE"

# 启动Node-RED
echo "[启动] Node-RED..."
nohup npx node-red -f "$(dirname "$0")/node-red/flows_template.json" > /tmp/av_nodered.log 2>&1 &
NR_PID=$!
echo $NR_PID >> "$PIDFILE"

sleep 2
echo ""
echo "=========================================="
echo "  AV统一系统已启动"
echo "=========================================="
echo "  主进程: PID $MAIN_PID"
echo "  Web界面: http://localhost:8501"
echo "  Node-RED: http://localhost:1880"
echo "  日志: $LOGFILE"
echo "  停止: ./stop_av.sh"
echo "=========================================="

# 自动打开Streamlit网页
sleep 2
open http://localhost:8501
