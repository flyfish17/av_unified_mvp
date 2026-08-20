#!/usr/bin/env bash
#
# deploy-62.sh — Mac 端一键把本仓 HEAD 刷到 62 板 (proembed@192.168.5.62)
#
# 幂等：可重复执行，再跑一次 = 升级到当前 HEAD。
#
# 流程：
#   1. git archive HEAD 打 tar（只含 git 跟踪文件，天然干净），打包侧剔除 node-red/
#   2. scp 推到板上 /tmp
#   3. 板上整目录备份 ~/av_unified_mvp.bak-<时间戳>（只保留最近 2 个，老的删）
#   4. 解包到临时目录，rsync 覆盖进 ~/av_unified_mvp
#      —— 排除不覆盖：config/ data/ summaries/ node-red/ logs/（板上实际配置与运行数据）
#   5. sudo systemctl restart av-demo（不手工 pkill，交给 systemd control-group）
#   6. 冒烟：:5050=200 → 模块进程数>=12 → door_access 在 → :1880=200 →
#      funasr-server active → 抽 3 个文件 md5 对比 Mac 仓 HEAD
#   7. 任一冒烟失败 → 自动整体回退到本次备份 + restart，失败现场留 .failed-<时间戳>
#
# 红线：
#   - 板上 config/ data/ summaries/ node-red/ 绝不覆盖。
#     尤其 node-red/：62 上它是 node-red 运行时 userDir（flows/credentials/node_modules
#     135M+，--userDir 指到仓库目录），整刷覆盖 = 毁掉 62 的 node-red 运行数据。
#   - 板上 creator_om 栈（~/creator_om）与本仓无关，本脚本全程不碰。
#   - 62 是湖森演示机，跑本脚本前先确认演示窗口。
#
# 用法：./scripts/deploy-62.sh

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BOARD_HOST="192.168.5.62"
BOARD_USER="proembed"
BOARD_PASS="xc"          # ssh 与 sudo 同密码
BOARD="${BOARD_USER}@${BOARD_HOST}"
APP_DIR="/home/${BOARD_USER}/av_unified_mvp"
TS="$(date +%Y%m%d-%H%M)"
TAR_LOCAL="/tmp/av62.tar"
TAR_REMOTE="/tmp/av62.tar"
STAGE_LOCAL="/tmp/av62_stage_local"
STAGE_REMOTE="/home/${BOARD_USER}/av62_stage"

# rsync 覆盖时排除（板上实际配置与运行数据，永不覆盖）。
# node-red/ 打包侧已剔除，这里再排除一次做双保险。
EXCLUDES=(config/ data/ summaries/ node-red/ logs/)

# md5 抽查文件（板上 vs Mac 仓 HEAD）
MD5_FILES=(modules/net_audio_capture/main.py web/server.py web/static/dashboard.js)

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\n!! %s\n' "$*" >&2; exit 1; }

bssh() { sshpass -p "$BOARD_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$BOARD" "$@"; }
bscp() { sshpass -p "$BOARD_PASS" scp -o StrictHostKeyChecking=no "$1" "${BOARD}:$2"; }

BACKUP_DONE=0
rollback() {
  local reason="$1"
  printf '\n!! 冒烟失败：%s\n' "$reason" >&2
  if [ "$BACKUP_DONE" != 1 ]; then
    die "尚未做过备份，无可回退（部署也尚未覆盖任何文件），请人工检查。"
  fi
  say "自动回退：换回部署前备份 av_unified_mvp.bak-${TS} 并重启服务"
  bssh "set -e
    mv '$APP_DIR' '${APP_DIR}.failed-${TS}'
    mv '${APP_DIR}.bak-${TS}' '$APP_DIR'
    echo '$BOARD_PASS' | sudo -S -p '' systemctl restart av-demo"
  printf '!! 已回退到部署前状态；失败现场保留在 %s.failed-%s 供尸检。\n' "$APP_DIR" "$TS" >&2
  exit 1
}

# ---------- 0. 前置检查 ----------
say "前置检查：仓库 HEAD 与板连通性"
command -v sshpass >/dev/null || die "本机缺 sshpass"
git -C "$REPO" rev-parse HEAD >/dev/null || die "$REPO 不是 git 仓"
HEAD_SHA="$(git -C "$REPO" rev-parse --short HEAD)"
echo "仓库: $REPO @ $HEAD_SHA"
bssh "test -d '$APP_DIR'" || die "板上不存在 $APP_DIR"

# ---------- 1. Mac 端打包（git archive 只含跟踪文件；剔除 node-red/） ----------
say "打包 HEAD（剔除 node-red/）"
rm -rf "$STAGE_LOCAL" "$TAR_LOCAL"
mkdir -p "$STAGE_LOCAL"
git -C "$REPO" archive HEAD | tar -x -C "$STAGE_LOCAL"
rm -rf "$STAGE_LOCAL/node-red"          # 打包侧剔除：绝不把仓内 node-red/ 带上板
tar -C "$STAGE_LOCAL" --no-xattrs --no-mac-metadata -cf "$TAR_LOCAL" .
echo "tar: $(ls -lh "$TAR_LOCAL" | awk '{print $5}')，$(tar -tf "$TAR_LOCAL" | grep -c -v '/$') 个文件"
if tar -tf "$TAR_LOCAL" | grep -q '^\./node-red'; then die "tar 内仍有 node-red/，中止"; fi

# ---------- 2. 推送 ----------
say "scp 推送 tar 到板上"
bscp "$TAR_LOCAL" "$TAR_REMOTE"

# ---------- 3. 板上备份（只保留最近 2 个 bak） ----------
say "板上整目录备份 -> av_unified_mvp.bak-${TS}"
bssh "set -e
  cp -a '$APP_DIR' '${APP_DIR}.bak-${TS}'
  ls -dt ${APP_DIR}.bak-* | tail -n +3 | xargs -r rm -rf
  echo '现存备份：'; ls -d ${APP_DIR}.bak-*"
BACKUP_DONE=1

# ---------- 4. 板上解包 + rsync 覆盖（排除 config/ data/ summaries/ node-red/ logs/） ----------
say "解包并 rsync 覆盖（排除：${EXCLUDES[*]}）"
EXCL_ARGS=""
for e in "${EXCLUDES[@]}"; do EXCL_ARGS+=" --exclude='/$e'"; done
bssh "set -e
  rm -rf '$STAGE_REMOTE'
  mkdir -p '$STAGE_REMOTE'
  tar -xf '$TAR_REMOTE' -C '$STAGE_REMOTE'
  rm -rf '$STAGE_REMOTE/node-red'   # 双保险
  rsync -a --itemize-changes $EXCL_ARGS '$STAGE_REMOTE/' '$APP_DIR/' > /tmp/av62_rsync.log
  grep -v '^\.d' /tmp/av62_rsync.log || echo '(无文件级变更)'
  rm -rf '$STAGE_REMOTE' '$TAR_REMOTE'"

# ---------- 5. 重启服务 ----------
say "重启 av-demo（systemd control-group，不手工 pkill）"
bssh "echo '$BOARD_PASS' | sudo -S -p '' systemctl restart av-demo"

# ---------- 6. 冒烟 ----------
say "冒烟 1/6：等 :5050 返回 200（最多 120s）"
OK=0
for _ in $(seq 1 60); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://${BOARD_HOST}:5050/" || true)"
  if [ "$CODE" = "200" ]; then OK=1; break; fi
  sleep 2
done
[ "$OK" = 1 ] || rollback ":5050 在 120s 内未返回 200（最后一次 http_code=${CODE}）"
echo "OK :5050 = 200"

say "冒烟 2/6：模块进程数 >= 12（最多再等 90s）"
NPROC=0
for _ in $(seq 1 30); do
  NPROC="$(bssh 'pgrep -f "creator_ai_demo/ven[v]" | wc -l' | tr -d '[:space:]')"
  if [ "$NPROC" -ge 12 ]; then break; fi
  sleep 3
done
[ "$NPROC" -ge 12 ] || rollback "模块进程数只有 ${NPROC}（要求 >=12，62 full 形态 12 个）"
echo "OK 模块进程数 = $NPROC"

say "冒烟 3/6：door_access 进程在（新旧 main.py 等价性验收点）"
DOOR="$(bssh 'pgrep -af "modules.door_access.mai[n]" | head -1' || true)"
[ -n "$DOOR" ] || rollback "modules.door_access.main 进程不在 —— HEAD 新式 profile 注册未把 door_access 拉起来"
echo "OK door_access: $DOOR"

say "冒烟 4/6：node-red :1880 返回 200（最多 120s）"
OK=0
for _ in $(seq 1 60); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://${BOARD_HOST}:1880/" || true)"
  if [ "$CODE" = "200" ]; then OK=1; break; fi
  sleep 2
done
[ "$OK" = 1 ] || rollback "node-red :1880 在 120s 内未返回 200（最后 http_code=${CODE}）—— 检查 node-red/ 是否被误动"
echo "OK :1880 = 200"

say "冒烟 5/6：funasr-server active"
FUN="$(bssh 'systemctl is-active funasr-server' 2>/dev/null | tr -d '[:space:]' || true)"
[ "$FUN" = "active" ] || rollback "funasr-server 状态为 ${FUN}（应为 active）"
echo "OK funasr-server = active"

say "冒烟 6/6：抽 ${#MD5_FILES[@]} 个文件 md5 对比 Mac 仓 HEAD"
MD5_FAIL=""
for f in "${MD5_FILES[@]}"; do
  LOCAL_MD5="$(git -C "$REPO" show "HEAD:$f" | md5 -q)"
  REMOTE_MD5="$(bssh "md5sum '$APP_DIR/$f'" | awk '{print $1}')"
  if [ "$LOCAL_MD5" = "$REMOTE_MD5" ]; then
    echo "OK  $f  $LOCAL_MD5"
  else
    echo "FAIL $f  HEAD=$LOCAL_MD5  板=$REMOTE_MD5"
    MD5_FAIL=1
  fi
done
[ -z "$MD5_FAIL" ] || rollback "md5 抽查有文件与 HEAD 不一致（见上）"

# ---------- 收尾 ----------
rm -rf "$STAGE_LOCAL" "$TAR_LOCAL"
say "部署完成：62 已刷到 ${HEAD_SHA}，全部冒烟通过。备份 ${APP_DIR}.bak-${TS} 可整体回退。"
