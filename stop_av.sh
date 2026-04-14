#!/bin/bash
# 停止脚本 - AV统一系统
pkill -f "streamlit run.*ui/dashboard.py" 2>/dev/null
echo "已停止 AV 统一系统"
