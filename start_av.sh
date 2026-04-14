#!/bin/bash
# 快捷启动脚本 - AV统一系统
cd "$(dirname "$0")"

echo "启动 AV 统一系统..."
echo ""

# 检查依赖
python3 -c "import cv2, streamlit, funasr, yaml" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "缺少依赖，正在安装..."
    SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null)
    pip3 install opencv-python streamlit funasr pyyaml paho-mqtt ultralytics --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

echo "启动 Streamlit..."
streamlit run ui/dashboard.py
