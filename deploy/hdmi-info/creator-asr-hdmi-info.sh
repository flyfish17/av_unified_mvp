#!/bin/bash
# CREATOR 转写纪要机 · 开机信息屏
# 来源: creator_om/deploy/hdmi-info/creator-om-hdmi-info.sh(运维平台现场调试屏)移植,文案/服务检测改为纪要机。
# 用途: 纪要机 HDMI 接任意显示器,通电即显示本机 IP(标注 DHCP/静态)/网关/纪要机服务状态/访问地址,
#       总部演示环境拿到板子插网线即可看到 DHCP 分到的 IP,不用进路由器后台。
# 部署: /usr/local/bin/creator-asr-hdmi-info.sh  +  /etc/xdg/autostart/creator-asr-hdmi-info.desktop
#
# 刷新方式: 整帧先攒进变量,再一次性原地重绘(光标回 Home 覆盖打印),无清屏白闪。
# 周期: 网口/服务 10s 检测(插拔网线 10s 内上屏);本机 CPU/内存/温度 5 分钟一算。

INTERVAL=10          # 网口/服务检测周期(秒)
SYS_ROUNDS=30        # 本机信息每 30 轮 = 5 分钟算一次
DASH_PORT="${AV_DASHBOARD_PORT:-5050}"
tput civis 2>/dev/null   # 藏光标,避免左上角闪烁
round=0
sysline="    本机: 采样中..."

while true; do
  # ── 本机信息(每 SYS_ROUNDS 轮一次;CPU% = 与上次采样间 /proc/stat 差值,即 5 分钟平均) ──
  if [ $((round % SYS_ROUNDS)) -eq 0 ]; then
    read -r _ u n s idle io irq sirq _ < /proc/stat
    busy=$((u+n+s+irq+sirq)); total=$((busy+idle+io))
    if [ -n "${pt:-}" ] && [ $((total-pt)) -gt 0 ]; then
      cpu="$(( (busy-pb)*100/(total-pt) ))%"
    else
      cpu="-"
    fi
    pb=$busy; pt=$total
    mem=$(LC_ALL=C free -m | awk '/^Mem:/{printf "%d/%dMB(%d%%)", $3, $2, $3*100/$2}')
    temp=$(awk '{printf "%d°C", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
    sysline="    本机: CPU ${cpu} · 内存 ${mem} · 温度 ${temp:-?}   (每 5 分钟更新)"
  fi
  round=$((round+1))

  # ── 攒整帧 ──
  frame="=================== CREATOR 转写纪要机 · 开机信息 ===================
$(date '+%Y-%m-%d %H:%M:%S')
"
  found=0
  for p in /sys/class/net/*; do
    ifc=$(basename "$p")
    [ "$ifc" = "lo" ] && continue
    # 只看物理网口(有 device 链接);跳过 docker0/br-*/veth* 等虚拟口(纪要机跑 funasr 容器,有 docker0)
    [ -e "$p/device" ] || continue
    # 只看以太网(ARPHRD_ETHER=1);3588 板上的 can0 是 CAN 总线,没 IP 概念,跳过
    [ "$(cat "$p/type" 2>/dev/null)" = "1" ] || continue
    ip4=$(ip -4 addr show "$ifc" 2>/dev/null | awk '/inet /{print $2}' | head -1)
    if [ -n "$ip4" ]; then
      # 该网口当前活动连接的 ipv4.method: auto=DHCP / manual=静态
      how=$(nmcli -t -f GENERAL.CONNECTION dev show "$ifc" 2>/dev/null | cut -d: -f2- | head -1)
      method=$(nmcli -t -f ipv4.method con show "$how" 2>/dev/null | cut -d: -f2)
      case "$method" in
        auto)   src="DHCP 自动获取";;
        manual) src="静态配置";;
        *)      src="";;
      esac
      frame+="$(figlet -w 220 "${ip4%/*}")
    网口 $ifc = $ip4 ${src:+($src)}
"
      found=1
    else
      # 无 IP 时若该口配了静态地址,标出来让人知道插线即活
      cfg=$(nmcli -t -f NAME,DEVICE,TYPE con show 2>/dev/null | awk -F: '$3=="802-3-ethernet"{print $1}' | while read -r cn; do
              nmcli -t -f connection.interface-name,ipv4.method,ipv4.addresses con show "$cn" 2>/dev/null \
                | awk -F: -v i="$ifc" 'BEGIN{ok=0} $1=="connection.interface-name"&&$2==i{ok=1} $1=="ipv4.method"&&$2!="manual"{ok=0} $1=="ipv4.addresses"&&ok{print $2}'
            done | head -1)
      if [ -n "$cfg" ]; then
        frame+="    网口 $ifc: 无 IP (链路: $(cat "$p/operstate" 2>/dev/null)) · 已配静态 ${cfg} 插线即活
"
      else
        frame+="    网口 $ifc: 无 IP (链路: $(cat "$p/operstate" 2>/dev/null)) · 等待 DHCP 分配
"
      fi
    fi
  done
  if [ "$found" = 0 ]; then
    frame+="$(figlet -w 220 "NO IP")
    请检查网线 / 交换机 / DHCP
"
  fi
  gw=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')
  frame+="
    网关: ${gw:-无}
$sysline
"
  # 服务状态: systemd av-demo 活 + dashboard 端口真能回 200 才算"运行中"(av-demo 是 oneshot,单看 is-active 不够)
  ipm=$(hostname -I 2>/dev/null | awk '{print $1}')
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${DASH_PORT}/" 2>/dev/null)
  if [ "$code" = "200" ]; then
    frame+="    转写纪要机: 运行中    浏览器访问 → http://${ipm}:${DASH_PORT}
"
  elif systemctl is-active --quiet av-demo; then
    frame+="    转写纪要机: 启动中 (服务已拉起,等待 :${DASH_PORT} 就绪,约 1-2 分钟)
"
  else
    frame+="    转写纪要机: 未运行 (排查: systemctl status av-demo)
"
  fi
  frame+="============== 网口/服务每 ${INTERVAL} 秒检测 · 插拔网线自动更新 ==============
"
  if [ -n "${DISPLAY:-}" ]; then
    frame+="    退出本屏进桌面: 接键盘按 Ctrl+C  ·  重新打开: 桌面终端跑 creator-asr-hdmi-info.sh 或注销重登"
  else
    frame+="    本屏由 systemd 托管  ·  停用: sudo systemctl disable --now creator-asr-hdmi-console"
  fi

  # ── 原地重绘:光标回 Home 覆盖打印,再清掉屏幕剩余部分 ──
  printf '\033[H\033[1;32m%s\033[J' "$frame"
  sleep $INTERVAL
done
