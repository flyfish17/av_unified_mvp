"""
RKNN backend for ARM (RK3588) — talks to a long-running daemon subprocess that
imports happyme531/SenseVoiceSmall-RKNN2 (AGPL-3.0). Daemon lives outside this
repo (default `~/SenseVoiceSmall-RKNN2/sensevoice_rknn_daemon.py`); we cross
the license boundary at the subprocess / JSON-line protocol — av_unified_mvp
itself stays clean.

Enable via env `AV_RKNN_BACKEND=1` when running with `AV_ASR_BACKEND=sense_voice_arm`.
Override daemon dir via env `AV_RKNN_DAEMON_DIR`.

Per-call cost on RK3588 (measured 5/12 with 4-7s wavs): RTT 329-443 ms end-to-end
(temp wav IO + fbank + NPU encoder + JSON parse), avg ~380 ms.
"""
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<\|[^|]+\|>")


class SenseVoiceRKNNBackend:
    """Daemon-isolated RKNN backend for SenseVoiceSmall on RK3588 NPU.

    Single-threaded by design (one daemon process, one inference at a time).
    The internal lock guards stdin/stdout against concurrent recognize() calls
    from multiple worker threads — but in current processor_arm.py only one
    worker thread calls inference, so contention is rare.
    """

    def __init__(self, daemon_dir: Optional[str] = None, language: str = "auto",
                 use_itn: bool = False):
        self.daemon_dir = Path(
            daemon_dir
            or os.environ.get("AV_RKNN_DAEMON_DIR")
            or (Path.home() / "SenseVoiceSmall-RKNN2")
        )
        script = self.daemon_dir / "sensevoice_rknn_daemon.py"
        if not script.exists():
            raise FileNotFoundError(
                f"RKNN daemon script not found: {script}. "
                "Expected the SenseVoiceSmall-RKNN2 directory (with the daemon "
                "alongside happyme531 sensevoice_rknn.py + .rknn model). "
                "Override location via env AV_RKNN_DAEMON_DIR."
            )
        self.language = language
        self.use_itn = use_itn
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._seq = 0
        self._tmpdir = Path(tempfile.mkdtemp(prefix="av_rknn_seg_"))
        self._stderr_log = self._tmpdir / "daemon.stderr.log"

    def start(self) -> None:
        cmd = ["python3", str(self.daemon_dir / "sensevoice_rknn_daemon.py")]
        stderr_f = open(self._stderr_log, "w")
        logger.info(f"启动 RKNN daemon: {cmd[1]} (stderr→{self._stderr_log})")
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_f,
            text=True,
            bufsize=1,
            cwd=str(self.daemon_dir),
        )
        t0 = time.time()
        line = self._proc.stdout.readline()
        if not line:
            rc = self._proc.poll()
            raise RuntimeError(
                f"RKNN daemon died at startup (rc={rc}). "
                f"check {self._stderr_log}"
            )
        ack = json.loads(line.strip())
        if not ack.get("ready"):
            raise RuntimeError(f"RKNN daemon handshake failed: {ack}")
        logger.info(f"RKNN daemon ready (pid={self._proc.pid}, handshake {time.time()-t0:.1f}s)")

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        finally:
            self._proc = None
            logger.info("RKNN daemon 已停止")

    def recognize(self, audio_f32: np.ndarray, sample_rate: int = 16000) -> str:
        """Inference one VAD-segmented audio chunk → cleaned text.

        Strips happyme531 meta tags (<|zh|><|NEUTRAL|>...) so the return value
        matches the funasr-CPU backend's contract.
        """
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("RKNN daemon not running (call start() first)")
        with self._lock:
            self._seq += 1
            seq = self._seq
            wav_path = self._tmpdir / f"seg-{seq}.wav"
            sf.write(str(wav_path), audio_f32, sample_rate, subtype="PCM_16")
            req = {
                "wav_path": str(wav_path),
                "language": self.language,
                "seq": seq,
                "use_itn": self.use_itn,
            }
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
                line = self._proc.stdout.readline()
            finally:
                # Clean up temp wav even on error
                try:
                    wav_path.unlink()
                except OSError:
                    pass
            if not line:
                raise RuntimeError("RKNN daemon EOF (process died?)")
            resp = json.loads(line.strip())
            if "error" in resp:
                logger.warning(f"RKNN inference error: {resp['error']}")
                return ""
            return _TAG_RE.sub("", resp.get("text", "")).strip()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
