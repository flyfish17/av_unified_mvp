# 转写纪要机 · HDMI 开机信息屏

> 2026-08-21 从 creator_om/deploy/hdmi-info 移植,3588(.6) 纪要机用。总部拿板子测试时 HDMI 接任意显示器,
> 开机自动全屏显示各网口 IP(标注 DHCP/静态)/网关/纪要机服务状态/dashboard 访问地址,绿字黑底 figlet 大字,10 秒刷新。

## 安装(两条命令)

```bash
sudo install -m 755 creator-asr-hdmi-info.sh /usr/local/bin/
sudo install -m 644 creator-asr-hdmi-info.desktop /etc/xdg/autostart/
```

前提:firefly 出厂固件(xfce 桌面 + autologin firefly + xterm/figlet 预装),无额外依赖。
重启后自动生效;立即看效果:
`DISPLAY=:0 setsid -f xterm -fa Monospace -fs 26 -bg black -fg green -fullscreen -e /usr/local/bin/creator-asr-hdmi-info.sh`

服务判定:dashboard `:5050` 回 200 = 运行中;仅 av-demo active = 启动中;否则未运行。
