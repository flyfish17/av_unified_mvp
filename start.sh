#!/bin/bash
# 启动脚本

echo "=== AV统一系统启动 ==="
echo ""

# 检查依赖
echo "检查依赖..."
python3 -c "import yaml, cv2, paho.mqtt.client, funasr" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ 缺少依赖，正在安装..."
    pip3 install -r requirements.txt
fi

# 检查YOLO模型
if [ ! -f "yolov8n.pt" ]; then
    echo "❌ YOLO模型不存在，请先下载"
    exit 1
fi

echo "✓ 依赖检查完成"
echo ""

# 启动选项
echo "请选择启动模式："
echo "1) 主程序（后台运行）"
echo "2) Web界面（Streamlit）"
echo "3) 同时启动"
read -p "输入选项 [1-3]: " choice

case $choice in
    1)
        echo "启动主程序..."
        python3 main.py
        ;;
    2)
        echo "启动Web界面..."
        streamlit run ui/dashboard.py
        ;;
    3)
        echo "启动主程序（后台）..."
        python3 main.py &
        sleep 2
        echo "启动Web界面..."
        streamlit run ui/dashboard.py
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac
