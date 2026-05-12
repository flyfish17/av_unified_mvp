#!/bin/bash
# NPU stability stress: loop 5 wav x 30 rounds, log RTF + RSS, output summary.
set -u
cd "$HOME/SenseVoiceSmall-RKNN2"
LOG=/tmp/npu_stress.log
: > "$LOG"
START_TS=$(date +%s)
echo "[start ts=$START_TS] NPU stress: 5 wav x 30 rounds" >> "$LOG"
ROUNDS=30
PYBIN=python3
for round in $(seq 1 $ROUNDS); do
  for w in zh en ja ko yue; do
    T0=$(date +%s.%N)
    OUT=$($PYBIN sensevoice_rknn.py --audio_file "$HOME/eval_test_wavs/$w.wav" --language "$w" 2>&1)
    T1=$(date +%s.%N)
    RTF=$(echo "$OUT" | grep -oE "RTF is [0-9.]+" | tail -1 | awk '{print $3}')
    AUDIO=$(echo "$OUT" | grep -oE "Audio.*is [0-9.]+ seconds" | head -1 | awk '{print $5}')
    REAL=$(echo "$T1 - $T0" | bc -l)
    # 取当前 SenseVoice 子进程的 RSS（已退出，看不到）；改取 bash 自己 + 总系统可用内存
    MEM_AVAIL=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
    echo "round=$round wav=$w audio=$AUDIO rtf=$RTF real=${REAL}s mem_avail_kb=$MEM_AVAIL" >> "$LOG"
  done
  echo "[round $round/$ROUNDS done at $(date '+%Y-%m-%d %H:%M:%S')]" >> "$LOG"
done
END_TS=$(date +%s)
echo "[done ts=$END_TS elapsed=$((END_TS - START_TS))s]" >> "$LOG"
