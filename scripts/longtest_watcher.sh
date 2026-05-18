#!/bin/bash
# 3588 夜班长测 watcher · 5min 间隔采样
# 部署：scp /tmp/longtest_watcher.sh firefly@192.168.5.6:/tmp/
# 启动：ssh firefly@192.168.5.6 'nohup bash /tmp/longtest_watcher.sh > /tmp/longtest_20260515/watcher.stderr.log 2>&1 & disown'
# 停止：ssh firefly@192.168.5.6 'pkill -f longtest_watcher'

set -u
OUT_DIR=/tmp/longtest_20260515
mkdir -p "$OUT_DIR"
SAMPLE_LOG="$OUT_DIR/sample.jsonl"
META="$OUT_DIR/meta.txt"
START_TS=$(date +%s)
START_ISO=$(date -Iseconds)

cat > "$META" <<EOF
watcher 启动时间: $START_ISO
PID: $$
预期持续: 14h（不限定，靠 pkill 停）
间隔: 300s (5min)
采样维度:
  - ps: 10 modules + supervisor + node-red + mosquitto (PID/etime/%cpu/RSS)
  - mqtt discovery: 在线 client_id 列表
  - mqtt topic 15s 消息率: av/audio/+ av/video/+ av/llm/+ av/control/+
  - 系统: load / mem_avail% / thermal_zone0-6 温度
  - log 累计: RKNN inference error / respawn / crash / "exception"
  - 端口: :1880 :1883 :5050 :5051 listening
  - MJPEG 4 路响应: USB罗技C920 / test / 财务室 / 办公室 (raw mode, code+time+size)
EOF

# 提前写一条 header 行
echo '{"_header":"longtest_20260515","start":"'"$START_ISO"'","interval_s":300}' >> "$SAMPLE_LOG"

sample_once() {
    local now_iso=$(date -Iseconds)
    local now_ts=$(date +%s)
    local elapsed=$(( now_ts - START_TS ))

    # === 系统层 ===
    local load1=$(awk '{print $1}' /proc/loadavg)
    local load5=$(awk '{print $2}' /proc/loadavg)
    local mem_avail_kb=$(awk '/MemAvailable:/{print $2}' /proc/meminfo)
    local mem_total_kb=$(awk '/MemTotal:/{print $2}' /proc/meminfo)
    local mem_avail_pct=$(awk "BEGIN{printf \"%.1f\", $mem_avail_kb*100/$mem_total_kb}")
    local uptime_s=$(awk '{print int($1)}' /proc/uptime)

    # 温度（rk3588 通常 thermal_zone0-6）
    local temp_max=0
    for t in /sys/class/thermal/thermal_zone*/temp; do
        if [ -r "$t" ]; then
            v=$(cat "$t" 2>/dev/null)
            [ -n "$v" ] && [ "$v" -gt "$temp_max" ] && temp_max=$v
        fi
    done
    local temp_max_c=$(awk "BEGIN{printf \"%.1f\", $temp_max/1000}")

    # === 进程层 ===
    local procs_json=$(ps -eo pid,etime,%cpu,rss,cmd --no-headers | \
        grep -E 'main\.py$|modules\.|node-red|mosquitto' | grep -v grep | \
        python3 -c "
import sys, json, re
out = []
for ln in sys.stdin:
    parts = ln.split(None, 4)
    if len(parts) < 5: continue
    pid, etime, cpu, rss, cmd = parts
    # 简化 module name
    m = re.search(r'modules\.([a-z_]+)', cmd)
    if m: mod = m.group(1)
    elif 'main.py' in cmd: mod = 'supervisor'
    elif 'node-red' in cmd: mod = 'nodered'
    elif 'mosquitto' in cmd: mod = 'mosquitto'
    else: continue
    out.append({'mod': mod, 'pid': int(pid), 'etime': etime, 'cpu': float(cpu), 'rss_kb': int(rss)})
print(json.dumps(out, ensure_ascii=False))
" 2>/dev/null || echo "[]")

    # === MQTT discovery (5s sample) ===
    local online_modules_json=$(timeout 6 mosquitto_sub -h 127.0.0.1 -W 5 \
        -t "av/system/discovery/+" 2>/dev/null | python3 -c "
import sys, json
seen = set()
for ln in sys.stdin:
    try:
        d = json.loads(ln)
        if d.get('event') in ('online', 'heartbeat'):
            seen.add(d.get('client_id', '?'))
    except: pass
print(json.dumps(sorted(seen), ensure_ascii=False))
" 2>/dev/null || echo "[]")

    # === MQTT topic 消息率 (15s) ===
    local topic_rates_json=$(timeout 17 mosquitto_sub -h 127.0.0.1 -W 15 -v \
        -t "av/audio/+" -t "av/video/+" -t "av/llm/+" -t "av/control/+" 2>/dev/null | \
        awk '{print $1}' | sort | uniq -c | python3 -c "
import sys, json
out = {}
for ln in sys.stdin:
    parts = ln.split()
    if len(parts) == 2:
        out[parts[1]] = int(parts[0])
print(json.dumps(out))
" 2>/dev/null || echo "{}")

    # === MJPEG 4 路响应时间 ===
    local mjpeg_json=$(python3 <<'PYEOF' 2>/dev/null || echo "{}"
import subprocess, json, urllib.parse
cams = ["USB罗技C920", "test", "办公室", "财务室"]
out = {}
for cam in cams:
    enc = urllib.parse.quote(cam)
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{size_download} %{time_total}",
             "--max-time", "8", f"http://127.0.0.1:5051/snapshot/{enc}?mode=raw"],
            capture_output=True, text=True, timeout=10)
        parts = r.stdout.strip().split()
        if len(parts) == 3:
            out[cam] = {"code": int(parts[0]), "size": int(parts[1]), "time_s": float(parts[2])}
        else:
            out[cam] = {"code": 0, "size": 0, "time_s": -1}
    except Exception as e:
        out[cam] = {"err": str(e)[:60]}
print(json.dumps(out, ensure_ascii=False))
PYEOF
)

    # === 端口 ===
    local ports_count=$(ss -tln 2>/dev/null | grep -cE ':1880|:1883|:5050|:5051')

    # === Log 累计计数 ===
    # 注意：grep -c 在 0 匹配时 exit 1，配合 `|| echo 0` 会让 stdout 变 "0\n0" 多行
    # 用 `; true` 模式：grep 任何 exit 都不中断；空输出再用 :-0 兜底
    local rknn_err=$(grep -c 'RKNN inference error' /tmp/main_supervisor.log 2>/dev/null; true)
    rknn_err=${rknn_err:-0}
    local respawn=$(grep -ciE 'respawn|child.*died|child.*restart' /tmp/main_supervisor.log 2>/dev/null; true)
    respawn=${respawn:-0}
    local exc_total=$(grep -ciE 'Traceback|Exception|Error:' /tmp/main_supervisor.log 2>/dev/null; true)
    exc_total=${exc_total:-0}
    local supervisor_log_size=$(stat -c%s /tmp/main_supervisor.log 2>/dev/null; true)
    supervisor_log_size=${supervisor_log_size:-0}
    local node_red_log_size=$(stat -c%s /tmp/node-red.log 2>/dev/null; true)
    node_red_log_size=${node_red_log_size:-0}

    # === 拼 JSONL 一行 ===
    python3 <<PYEOF >> "$SAMPLE_LOG"
import json
print(json.dumps({
    "iso": "$now_iso",
    "elapsed_s": $elapsed,
    "uptime_s": $uptime_s,
    "load1": $load1,
    "load5": $load5,
    "mem_avail_pct": $mem_avail_pct,
    "temp_max_c": $temp_max_c,
    "ports_listening": $ports_count,
    "rknn_err_cumul": $rknn_err,
    "respawn_cumul": $respawn,
    "exc_cumul": $exc_total,
    "log_supervisor_bytes": $supervisor_log_size,
    "log_nodered_bytes": $node_red_log_size,
    "procs": $procs_json,
    "online_modules": $online_modules_json,
    "topic_rates_15s": $topic_rates_json,
    "mjpeg": $mjpeg_json,
}, ensure_ascii=False))
PYEOF
}

# 立即采一次（让 user 立刻能看到数据生成）
sample_once

# 主循环
while true; do
    sleep 285  # 加 sample 内 ~15s 等于 ~300s 每轮
    sample_once
done
