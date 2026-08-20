"""
modules/net_audio_capture/receiver.py
会议主机 8 路话筒组播收包 → 48K→16K 降采样 → FunASR 2pass 转写（CR-DIG7201 P1）。

协议（原厂 doc + 字段级确定）：
  UDP 组播 224.1.1.11，8 路话筒 = 端口 1000-1007（1000=第1路）。
  包 = 4 字节头（16bit ID 大端重复两次：ID高8+ID低8+ID高8+ID低8）+ 320 个 16bit LE sample（640B）。
  音频 48000Hz / 16bit / 单声道。以端口号定话筒（port-base_port），头部 ID 只做交叉校验告警。

不复用 audio_processor.AudioProcessor（它与 sounddevice 麦克风耦合，且是已验收主链路，
不动）；本文件自带精简 2pass 会话，PCM 从 UDP 喂入。
"""
import asyncio
import json
import logging
import queue
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional

import numpy as np
import scipy.signal as signal

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<\|[^|]+\|>")

PACKET_HEADER_BYTES = 4
# 原厂 doc 称每包 320 sample / 644B；2026-08-03 真机（会议主机 192.168.2.2）实测为
# 160 sample / 324B（doc 不可信，已抓包对照）。故不写死包长：4 字节头 + 任意偶数字节 PCM，
# 按实际长度解，兼容不同型号/配置的包长，头部 ID 仍做合法性交叉校验。
MIN_PACKET_BYTES = PACKET_HEADER_BYTES + 2  # 至少 1 个 16bit sample


@dataclass
class MicTranscriptEvent:
    mic_id: int          # 0-based 路号（端口 - base_port）
    text: str
    is_final: bool
    seq_id: int
    ts: float
    raw_mode: str


class Downsampler48to16:
    """流式 48K→16K：8 阶 butter 低通（7000Hz）持久 zi + 每 3 取 1。
    余数 sample 跨块保留，保证严格 1/3 相位连续。"""

    def __init__(self):
        self._sos = signal.butter(8, 7000, btype="lp", fs=48000, output="sos")
        self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)
        self._rem = np.zeros(0, dtype=np.float64)

    def feed(self, pcm48: np.ndarray) -> np.ndarray:
        """输入 int16 48K 样本，返回 int16 16K 样本（可能为空数组）。"""
        filtered, self._zi = signal.sosfilt(
            self._sos, pcm48.astype(np.float64), zi=self._zi
        )
        buf = np.concatenate([self._rem, filtered])
        n_take = (len(buf) // 3) * 3
        self._rem = buf[n_take:]
        down = buf[:n_take:3]
        return np.clip(down, -32768.0, 32767.0).astype(np.int16)


class FunASRSession:
    """单路 FunASR websocket_2pass 会话，PCM 由 feed() 喂入（对照
    audio_processor.processor 的 ws 逻辑裁剪，去掉 sounddevice/降级路径）。"""

    def __init__(self, mic_id: int, funasr_cfg: dict,
                 callback: Callable[[MicTranscriptEvent], None]):
        self.mic_id = mic_id
        self.url = funasr_cfg.get("url", "ws://127.0.0.1:10095")
        self.chunk_size = list(funasr_cfg.get("chunk_size", [5, 10, 5]))
        self.chunk_interval = int(funasr_cfg.get("chunk_interval", 10))
        self.hotwords = str(funasr_cfg.get("hotwords", ""))
        self.use_itn = bool(funasr_cfg.get("use_itn", True))
        self._callback = callback
        self._send_q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=128)
        self._stop = threading.Event()
        self._seq = 0
        self._last_partial = ""
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"funasr-mic{self.mic_id}"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._send_q.put_nowait(None)
        except queue.Full:
            pass

    def feed(self, pcm16k: bytes):
        try:
            self._send_q.put_nowait(pcm16k)
        except queue.Full:
            # 丢最老的保最新（与 audio_processor 同策略），并让人看到
            try:
                self._send_q.get_nowait()
                self._send_q.put_nowait(pcm16k)
            except (queue.Empty, queue.Full):
                pass
            logger.warning(f"[mic{self.mic_id}] send_q 满，丢帧（FunASR 消费不过来）")

    def _run(self):
        try:
            asyncio.run(self._supervise())
        except Exception as e:
            logger.error(f"[mic{self.mic_id}] FunASR 线程退出: {e}")

    async def _supervise(self):
        import websockets
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url, max_size=10 * 1024 * 1024,
                    ping_interval=20, ping_timeout=20,
                ) as ws:
                    logger.info(f"[mic{self.mic_id}] FunASR 已连接 {self.url}")
                    backoff = 1.0
                    await ws.send(json.dumps({
                        "mode": "2pass",
                        "chunk_size": self.chunk_size,
                        "chunk_interval": self.chunk_interval,
                        "audio_fs": 16000,
                        "wav_name": f"mic{self.mic_id}",
                        "wav_format": "pcm",
                        "is_speaking": True,
                        "hotwords": self.hotwords,
                        "itn": self.use_itn,
                    }, ensure_ascii=False))
                    send_task = asyncio.create_task(self._send_loop(ws))
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    done, pending = await asyncio.wait(
                        {send_task, recv_task}, return_when=asyncio.FIRST_EXCEPTION
                    )
                    for t in pending:
                        t.cancel()
                    for t in done:
                        if t.exception() is not None:
                            raise t.exception()
            except Exception as e:
                if self._stop.is_set():
                    return
                logger.warning(f"[mic{self.mic_id}] FunASR WS 异常: {e}，{backoff:.1f}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    async def _send_loop(self, ws):
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                pcm = await loop.run_in_executor(
                    None, partial(self._send_q.get, True, 0.5)
                )
            except queue.Empty:
                continue
            if pcm is None:
                try:
                    await ws.send(json.dumps({"is_speaking": False}))
                except Exception:
                    pass
                return
            await ws.send(pcm)

    async def _recv_loop(self, ws):
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            text = _TAG_RE.sub("", msg.get("text", "")).strip()
            if not text:
                continue
            raw_mode = str(msg.get("mode", ""))
            is_final = raw_mode.endswith("offline")
            if not is_final:
                if text == self._last_partial:
                    continue
                self._last_partial = text
            ev = MicTranscriptEvent(
                mic_id=self.mic_id,
                text=text,
                is_final=is_final,
                # 跨路唯一：mic_id*10000 + 会话内序号，避免 dashboard 气泡串路
                seq_id=self.mic_id * 10000 + self._seq,
                ts=time.time(),
                raw_mode=raw_mode or ("final" if is_final else "partial"),
            )
            if is_final:
                self._seq += 1
                self._last_partial = ""
            try:
                self._callback(ev)
            except Exception as e:
                logger.error(f"[mic{self.mic_id}] 回调异常: {e}")


class UdpMicChannel:
    """单路：UDP 组播收包线程 → 解包校验 → 降采样 → RMS 静音门 → FunASRSession。

    静音门：闲置话筒不喂 FunASR（8 路全喂 3588 扛不住 8 个 online decoder）。
    RMS 超阈值开门，低于阈值持续 hangover_ms 后关门；关门期数据丢弃（≈静音）。
    hangover 默认 1800ms（2026-08-07 由 800 上调）：真人句内停顿常见 0.8-1.5s，
    800ms 门逢停顿即关门补静音强制结算 final → 一句话被切成 2-4 字碎片；
    1800ms 让词间停顿不触发门切（server VAD 的自然分句不受此参数控制）。
    """

    def __init__(self, mic_id: int, group: str, port: int, funasr_cfg: dict,
                 callback: Callable[[MicTranscriptEvent], None],
                 gate_threshold: float = 150.0, gate_hangover_ms: int = 1800,
                 pcm_tap: Optional[Callable[[int, np.ndarray], None]] = None):
        # pcm_tap: gate 后 16k PCM 旁路（会话录制用，见 recorder.SessionRecorder）；
        # 异常隔离，录制故障不影响转写主链
        self._pcm_tap = pcm_tap
        self.mic_id = mic_id
        self.group = group
        self.port = port
        self._session = FunASRSession(mic_id, funasr_cfg, callback)
        self._down = Downsampler48to16()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        # 静音门（阈值单位：int16 RMS）
        self._gate_threshold = gate_threshold
        self._gate_hangover_s = gate_hangover_ms / 1000.0
        self._gate_open = False
        self._gate_last_voice = 0.0
        # 16K 帧聚合：960 sample（60ms）一发，对齐 audio_processor 的帧节奏
        self._out_buf = np.zeros(0, dtype=np.int16)
        self._frame_16k = 960
        # 统计（模块心跳里上报）
        self.packets = 0
        self.bad_packets = 0
        self.header_mismatch = 0
        self.gate_open_count = 0

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(("", self.port))
        mreq = struct.pack("4s4s", socket.inet_aton(self.group),
                           socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)
        self._sock = sock
        self._session.start()
        self._thread = threading.Thread(
            target=self._recv_loop, daemon=True, name=f"udp-mic{self.mic_id}"
        )
        self._thread.start()
        logger.info(f"[mic{self.mic_id}] 组播收包已启动 {self.group}:{self.port}")

    def stop(self):
        self._stop.set()
        self._session.stop()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass

    def _recv_loop(self):
        expected_id = None  # 首包头部 ID 记为基准，后续变化才告警
        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(2048)
            except socket.timeout:
                # 断流也算静音：会议主机掉线/mock 播完停发时同样要关门结算 final
                self._maybe_close_gate(time.time())
                continue
            except OSError:
                return  # socket 已关闭
            if len(data) < MIN_PACKET_BYTES or (len(data) - PACKET_HEADER_BYTES) % 2 != 0:
                self.bad_packets += 1
                if self.bad_packets <= 3 or self.bad_packets % 1000 == 0:
                    logger.warning(
                        f"[mic{self.mic_id}] 包长异常 {len(data)}B（需 4 字节头+偶数 PCM，"
                        f"累计 {self.bad_packets}）"
                    )
                continue
            self.packets += 1
            # 头部：16bit ID 重复两次（大端）。端口定路号，ID 只交叉校验。
            id1 = (data[0] << 8) | data[1]
            id2 = (data[2] << 8) | data[3]
            if id1 != id2:
                self.header_mismatch += 1
            elif expected_id is None:
                expected_id = id1
                logger.info(f"[mic{self.mic_id}] 首包头部 ID={id1}（端口推定路号 {self.mic_id}）")
            elif id1 != expected_id:
                self.header_mismatch += 1
                if self.header_mismatch <= 3:
                    logger.warning(
                        f"[mic{self.mic_id}] 头部 ID 漂移 {expected_id}→{id1}"
                    )
                expected_id = id1

            # 2026-08-03 真机实测：PCM 是大端（BE）。包头 ID 也是大端（00 08 00 08），
            # 整个协议大端一致。原按小端 "<i2" 解会把安静波形（大端小负值 ff f1=-15）
            # 解成满量程噪声（0xf1ff=-3585）→ 听感嗡嗡、转写幻听碎片（曾误判为工频干扰）。
            pcm48 = np.frombuffer(data, dtype=">i2", offset=PACKET_HEADER_BYTES)
            # 静音门：48K 原始域算 RMS，避免白做降采样
            rms = float(np.sqrt(np.mean(pcm48.astype(np.float64) ** 2)))
            now = time.time()
            if rms >= self._gate_threshold:
                if not self._gate_open:
                    self._gate_open = True
                    self.gate_open_count += 1
                    logger.info(f"[mic{self.mic_id}] 语音活动开始 (RMS={rms:.0f})")
                self._gate_last_voice = now
            else:
                self._maybe_close_gate(now)
            if not self._gate_open:
                continue

            pcm16 = self._down.feed(pcm48)
            if len(pcm16) == 0:
                continue
            if self._pcm_tap is not None:
                try:
                    self._pcm_tap(self.mic_id, pcm16)
                except Exception:
                    pass  # 录制旁路故障不影响转写主链
            self._out_buf = np.concatenate([self._out_buf, pcm16])
            while len(self._out_buf) >= self._frame_16k:
                frame = self._out_buf[:self._frame_16k]
                self._out_buf = self._out_buf[self._frame_16k:]
                self._session.feed(frame.tobytes())

    def _maybe_close_gate(self, now: float) -> None:
        """RMS 低于阈值（或断流）持续 hangover 后关门，并补 1s 静音：
        FunASR 2pass 的 offline 段靠 server 端 VAD 检出尾部静音才结算 final，
        直接断流 server 会一直等（实测 0 final 的根因）。"""
        if not self._gate_open or now - self._gate_last_voice <= self._gate_hangover_s:
            return
        self._gate_open = False
        logger.info(f"[mic{self.mic_id}] 语音活动结束")
        silence_frame = bytes(self._frame_16k * 2)
        for _ in range(16):  # 16 × 60ms ≈ 1s
            self._session.feed(silence_frame)

    def stats(self) -> dict:
        return {
            "mic_id": self.mic_id,
            "port": self.port,
            "packets": self.packets,
            "bad_packets": self.bad_packets,
            "header_mismatch": self.header_mismatch,
            "gate_open": self._gate_open,
            "gate_open_count": self.gate_open_count,
        }
