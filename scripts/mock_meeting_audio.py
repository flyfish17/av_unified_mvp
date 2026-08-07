#!/usr/bin/env python3
"""
scripts/mock_meeting_audio.py
会议主机组播发包模拟器（CR-DIG7201 P1 离线验证）。

把 wav 按原厂协议切包发到组播：4B 头（16bit ID 大端×2）+ 320 sample × 16bit BE，
48000Hz 单声道，6.667ms/包 实时节奏。
（2026-08-07 对齐 P2 真机纠偏：PCM 大端；真机实为 160 sample/324B，
receiver 弹性包长两者都收，mock 保持 320 sample 不影响验证。）

用法：
  python scripts/mock_meeting_audio.py --ch 0:a.wav --ch 2:b.wav [--loop] \
      [--group 224.1.1.11] [--base-port 1000]

wav 任意采样率/声道，自动转 48K 单声道。--loop 循环播放。
"""
import argparse
import socket
import struct
import sys
import threading
import time
import wave

import numpy as np


def load_wav_48k(path: str) -> np.ndarray:
    """读 wav → int16 48K 单声道。仅依赖标准库 wave + numpy。"""
    with wave.open(path, "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError(f"{path}: 仅支持 16bit wav（现 {width * 8}bit）")
    pcm = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != 48000:
        # 线性插值重采样（mock 用途足够；正式链路降采样在接收端）
        n_out = int(len(pcm) * 48000 / rate)
        x_old = np.linspace(0.0, 1.0, num=len(pcm), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        pcm = np.interp(x_new, x_old, pcm.astype(np.float64)).astype(np.int16)
    return pcm


def send_channel(mic_id: int, wav_path: str, group: str, base_port: int,
                 loop: bool, stop: threading.Event):
    pcm = load_wav_48k(wav_path)
    port = base_port + mic_id
    header = struct.pack(">HH", mic_id, mic_id)  # 16bit ID 大端 ×2
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    n_packets = len(pcm) // 320
    interval = 320 / 48000.0  # 6.667ms
    print(f"[mic{mic_id}] {wav_path} → {group}:{port}  "
          f"{len(pcm)/48000:.1f}s / {n_packets} 包{'（循环）' if loop else ''}")
    while not stop.is_set():
        t_next = time.monotonic()
        for i in range(n_packets):
            if stop.is_set():
                break
            chunk = pcm[i * 320:(i + 1) * 320]
            # P2 真机纠偏（2026-08-03）：全协议大端，receiver 按 >i2 解；LE 会被解成满量程噪声
            sock.sendto(header + chunk.astype(">i2").tobytes(), (group, port))
            t_next += interval
            delay = t_next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        if not loop:
            break
    sock.close()
    print(f"[mic{mic_id}] 发送结束")


def main():
    ap = argparse.ArgumentParser(description="会议主机组播发包模拟")
    ap.add_argument("--ch", action="append", required=True,
                    metavar="N:file.wav", help="路号:wav 路径，可多次（0-7）")
    ap.add_argument("--group", default="224.1.1.11")
    ap.add_argument("--base-port", type=int, default=1000)
    ap.add_argument("--loop", action="store_true", help="循环播放")
    args = ap.parse_args()

    jobs = []
    for spec in args.ch:
        mic_s, _, path = spec.partition(":")
        mic_id = int(mic_s)
        if not 0 <= mic_id <= 7:
            sys.exit(f"路号越界: {mic_id}（0-7）")
        jobs.append((mic_id, path))

    stop = threading.Event()
    threads = [
        threading.Thread(target=send_channel,
                         args=(m, p, args.group, args.base_port, args.loop, stop),
                         daemon=True)
        for m, p in jobs
    ]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.3)
    except KeyboardInterrupt:
        stop.set()
        for t in threads:
            t.join(timeout=2)


if __name__ == "__main__":
    main()
