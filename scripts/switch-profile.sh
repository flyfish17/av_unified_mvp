#!/bin/bash
# av_unified_mvp · 3588 应用形态切换（meeting_asr 纪要机 ⇄ full 全功能演示）
#
# 在板子本机运行：
#   bash ~/av_unified_mvp/scripts/switch-profile.sh full          # 切全功能演示
#   bash ~/av_unified_mvp/scripts/switch-profile.sh meeting_asr   # 切回纪要机
#   bash ~/av_unified_mvp/scripts/switch-profile.sh --status      # 只看当前形态,不动
#
# 做的事(约 60s,期间 dashboard 不可用):
#   1. 改 config/system_config.yaml 顶层 app_profile(先备份 config.bak-<时间>)
#   2. SIGKILL 老 supervisor + module 子进程 + rkllm 意图 daemon
#      —— 必须 -9:supervisor 的 SIGTERM handler 会 docker stop funasr,而启动脚本不重起它,
#         转写会降级;SIGKILL 绕过 handler 保住 funasr/mosquitto。rkllm_daemon 是 llm_engine 的
#         子进程,不杀它 2GB NPU IOVA 不释放,切回纪要机后 1.7B 装载会报 IOVA -12。
#   3. systemctl restart av-demo → 走 3588-demo-start.sh 正常拉起(期望模块数按 profile 自动算)
#   4. 等 :5050 回 200 + 模块数到位,打印结果
#
# 注意:两个形态在 3588 上互斥(YOLO 吃满 4 核 / NPU IOVA 4G),不存在"同时跑"。
#       前端刻意不给切换按钮,防客户误切;切换只走本脚本。

set -u

PROJECT_DIR="${AV_PROJECT_DIR:-$HOME/av_unified_mvp}"
VENV_PY="${AV_VENV_PY:-$HOME/creator_ai_demo/venv/bin/python}"
CONFIG="$PROJECT_DIR/config/system_config.yaml"
DASHBOARD_PORT="${AV_DASHBOARD_PORT:-5050}"
WAIT_SECONDS="${AV_WAIT_SECONDS:-90}"

GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; CYAN='\033[1;36m'; OFF='\033[0m'
ok()   { printf "${GREEN}✓${OFF} %s\n" "$1"; }
warn() { printf "${YELLOW}!${OFF} %s\n" "$1"; }
fail() { printf "${RED}✗${OFF} %s\n" "$1"; }

current_profile() {
  sed -n 's/^app_profile:[[:space:]]*\([A-Za-z_]*\).*/\1/p' "$CONFIG" | head -1
}
# 按 config 里的 profile / audio.source / door_access 算期望模块数(和 supervisor 同一套逻辑)
expected_modules() {
  (cd "$PROJECT_DIR" && "$VENV_PY" - <<'PY'
import yaml, main
cfg = yaml.safe_load(open("config/system_config.yaml")) or {}
p = cfg.get("app_profile") or "full"
mods = list(main.APP_PROFILES[p])
src = cfg.get("audio", {}).get("source", "mic")
src = src if isinstance(src, list) else [src]
if "mic" not in src:
    mods = [m for m in mods if m != "modules.audio_processor.main"]
if "net_multicast" in src:
    mods.append("modules.net_audio_capture.main")
if cfg.get("door_access", {}).get("enabled"):
    mods.append("modules.door_access.main")
if cfg.get("speaker_diarizer", {}).get("enabled"):
    mods.append("modules.speaker_diarizer.main")
if cfg.get("device_state", {}).get("enabled"):
    mods.append("modules.device_state.main")
print(len(mods))
PY
  )
}
module_count() { pgrep -f "${VENV_PY}.*-m modules\\." 2>/dev/null | wc -l | tr -d ' '; }
http_code()    { curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${DASHBOARD_PORT}/" 2>/dev/null || echo 000; }

TARGET="${1:-}"
CUR="$(current_profile)"; CUR="${CUR:-full}"

case "$TARGET" in
  --status|"")
    printf "  当前形态     : ${CYAN}%s${OFF}\n" "$CUR"
    printf "  语音输入     : %s  (USB 麦: %s)\n" "$(sed -nE 's/^  source:[[:space:]]*([A-Za-z_]+).*/\1/p' "$CONFIG" | head -1)" "$(arecord -l 2>/dev/null | grep -iE 'C920|USB Audio' | sed -E 's/^card ([0-9]+): ([^ ]+).*/card\1 \2/' | head -1)"
    printf "  模块子进程   : %s / %s\n" "$(module_count)" "$(expected_modules)"
    printf "  dashboard    : HTTP %s  (http://%s:%s)\n" "$(http_code)" "$(hostname -I | awk '{print $1}')" "$DASHBOARD_PORT"
    printf "  funasr 容器  : %s\n" "$(docker inspect -f '{{.State.Status}}' funasr 2>/dev/null || echo 无)"
    printf "  rkllm daemon : %s\n" "$(pgrep -f 'rkllm_daemon\.py' >/dev/null && echo 运行中 || echo 未运行)"
    [ -z "$TARGET" ] && { echo; sed -n '2,8p' "$0"; }
    exit 0 ;;
  full|meeting_asr) ;;
  *) fail "未知形态 '$TARGET',可选 full | meeting_asr | --status"; exit 1 ;;
esac

case "$TARGET" in
  full)        SRC=mic ;;
  meeting_asr) SRC=net_multicast ;;
esac
CUR_SRC="$(sed -nE 's/^  source:[[:space:]]*([A-Za-z_]+).*/\1/p' "$CONFIG" | head -1)"
if [ "$TARGET" = "$CUR" ] && [ "$CUR_SRC" = "$SRC" ]; then
  ok "已经是 $CUR(audio.source=$SRC),不动。要强制重启: sudo systemctl restart av-demo"
  exit 0
fi

# 1. 改 config
cp "$CONFIG" "$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"
ls -1t "$CONFIG".bak-* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
if grep -q '^app_profile:' "$CONFIG"; then
  sed -i "s/^app_profile:.*/app_profile: $TARGET/" "$CONFIG"
else
  printf '\napp_profile: %s\n' "$TARGET" >> "$CONFIG"
fi
ok "config app_profile: $CUR → $TARGET"

# 语音输入跟着形态走(3588 纪要机现场约定):
#   full        → mic           USB 麦 C920 本机拾音,audio_processor 跑;启动脚本 §0.5 会把 ALSA default 指到 C920
#   meeting_asr → net_multicast 会议主机 8 路组播,net_audio_capture 跑(话筒号=发言人)
# 不切的话 full 下 audio.source 还是 net_multicast → supervisor 按 main.py 去掉 audio_processor,演示没麦克风。
if grep -qE '^  source:' "$CONFIG"; then
  sed -i -E "0,/^  source:.*/s//  source: $SRC/" "$CONFIG"
  ok "config audio.source: ${CUR_SRC:-?} → $SRC"
else
  fail "config 里没找到 audio.source(两空格缩进 'source:'),不敢猜,停"; exit 1
fi
if [ "$SRC" = "mic" ] && ! arecord -l 2>/dev/null | grep -qiE 'C920|USB Audio'; then
  warn "没探到 USB 麦克风(C920)——full 形态语音输入会是空,插上麦后重跑本脚本或 systemctl restart av-demo"
fi
EXPECTED="$(expected_modules)" || { fail "按 config 算期望模块数失败(config 语法?)"; exit 1; }

# 2. SIGKILL 老进程(顺序:先 supervisor 防它重拉,再 module,再 rkllm daemon)
pkill -9 -f "${VENV_PY}.*main\.py$"        2>/dev/null
pkill -9 -f "${VENV_PY}.*-m modules\\."   2>/dev/null
pkill -9 -f "rkllm_daemon\.py"             2>/dev/null
sleep 2
[ "$(module_count)" = "0" ] && ok "老 supervisor/模块已停(funasr 容器: $(docker inspect -f '{{.State.Status}}' funasr 2>/dev/null || echo 无))" \
                            || warn "仍有 $(module_count) 个模块进程,继续"

# 3. systemd 重启(此时 cgroup 已空,restart 不会触发 supervisor 的 docker stop)
sudo systemctl restart av-demo || { fail "systemctl restart av-demo 失败: sudo journalctl -u av-demo -n 30"; exit 1; }

# 4. 等就绪
printf "等待 dashboard + %s 个模块(最多 %ss)\n" "$EXPECTED" "$WAIT_SECONDS"
for i in $(seq 1 "$WAIT_SECONDS"); do
  C="$(http_code)"; M="$(module_count)"
  if [ "$C" = "200" ] && [ "$M" -ge "$EXPECTED" ]; then
    ok "已切到 ${TARGET}:模块 $M/$EXPECTED,dashboard http://$(hostname -I | awk '{print $1}'):$DASHBOARD_PORT"
    [ "$TARGET" = "full" ] && warn "full 形态下 YOLO 占满 CPU,纪要会很慢/超时——这是 3588 算力边界,演示视听功能可以,别在此形态开长会"
    exit 0
  fi
  [ $((i % 10)) -eq 0 ] && printf "  %02ds  HTTP=%s  modules=%s/%s\n" "$i" "$C" "$M" "$EXPECTED"
  sleep 1
done
fail "超时:HTTP=$(http_code) modules=$(module_count)/$EXPECTED。看 tail -50 /tmp/main_supervisor.log"
exit 2
