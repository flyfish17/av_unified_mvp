"""
RKLLM backend for ARM (RK3588) — talks to a long-running daemon subprocess that
wraps librkllmrt.so via ctypes. Daemon lives at `~/rkllm-poc/daemon/rkllm_daemon.py`
(rsync 自 scripts/templates/rkllm/ 部署到 3588）；这边只跨 subprocess + JSON 行协议
调用，保持模块边界干净 — 与 modules/audio_processor/rknn_backend.py 同款模式。

启用方式：
  - 环境变量 `AV_LLM_BACKEND=rknn`（engine.py 读取），或
  - config: `llm.backend: rknn`
  - 可选环境变量：
      AV_RKLLM_DAEMON_DIR   daemon 目录（默认 ~/rkllm-poc/daemon）
      AV_RKLLM_LIB          librkllmrt.so 路径（默认见 daemon 内置）
      AV_RKLLM_MODEL        .rkllm 模型路径（默认见 daemon 内置）

实测 5/13（晚间 POC）：首 token p50/p95 = 194ms / 360ms，decode 8.84 tok/s，
27 prompt × 3 round 无衰减；详见 OVERNIGHT_REPORT_20260513.md。
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


DEFAULT_DAEMON_DIR = Path.home() / "rkllm-poc" / "daemon"


class RKLLMBackend:
    """单进程 daemon-isolated NPU 推理后端。

    线程模型：一个 daemon 子进程同一时刻只处理一条 inference（rkllm SDK 本身
    单实例同步）。`_lock` 保护 stdin/stdout 协议不被多线程交错；engine.py 端
    `generate_command` 由 MQTT _handle_message 单线程触发，正常情况无并发。
    """

    def __init__(
        self,
        daemon_dir: Optional[str] = None,
        model_path: Optional[str] = None,
        lib_path: Optional[str] = None,
        max_context_len: int = 2048,
        max_new_tokens: int = 200,
    ):
        self.daemon_dir = Path(
            daemon_dir
            or os.environ.get("AV_RKLLM_DAEMON_DIR")
            or DEFAULT_DAEMON_DIR
        )
        script = self.daemon_dir / "rkllm_daemon.py"
        if not script.exists():
            raise FileNotFoundError(
                f"RKLLM daemon script not found: {script}. "
                f"部署见 scripts/templates/rkllm/README.md；可改 AV_RKLLM_DAEMON_DIR 覆盖路径。"
            )
        self.model_path = model_path or os.environ.get("AV_RKLLM_MODEL")
        self.lib_path = lib_path or os.environ.get("AV_RKLLM_LIB")
        self.max_context_len = max_context_len
        self.max_new_tokens = max_new_tokens
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._seq = 0
        self._tmpdir = Path(tempfile.mkdtemp(prefix="av_rkllm_"))
        self._stderr_log = self._tmpdir / "daemon.stderr.log"

    def start(self) -> dict:
        """启动 daemon 子进程，等待 ready 握手。返回 handshake dict（含 load_ms/rss_mb）。"""
        cmd = [sys.executable, str(self.daemon_dir / "rkllm_daemon.py")]
        if self.lib_path:
            cmd += ["--lib", self.lib_path]
        if self.model_path:
            cmd += ["--model", self.model_path]
        cmd += [
            "--max-context-len", str(self.max_context_len),
            "--max-new-tokens", str(self.max_new_tokens),
        ]
        stderr_f = open(self._stderr_log, "w")
        logger.info(f"启动 RKLLM daemon: {' '.join(cmd)} (stderr→{self._stderr_log})")
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
                f"RKLLM daemon 启动失败 (rc={rc})，详见 {self._stderr_log}"
            )
        ack = json.loads(line.strip())
        if not ack.get("ready"):
            raise RuntimeError(f"RKLLM daemon handshake 失败: {ack}")
        logger.info(
            f"RKLLM daemon ready (pid={self._proc.pid}, "
            f"load_ms={ack.get('load_ms'):.0f}, rss_mb={ack.get('rss_mb'):.0f}, "
            f"握手耗时 {time.time() - t0:.1f}s)"
        )
        return ack

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
            logger.info("RKLLM daemon 已停止")

    def ask(
        self,
        prompt: str,
        role: str = "user",
        enable_thinking: bool = False,
        timeout: float = 30.0,
    ) -> str:
        """同步推理一条 prompt → text。daemon 死或超时返回空串（与 ollama _ask 一致语义）。"""
        if self._proc is None or self._proc.poll() is not None:
            logger.error("RKLLM daemon 未运行；返回空字符串")
            return ""
        with self._lock:
            self._seq += 1
            seq = self._seq
            req = {
                "seq": seq,
                "prompt": prompt,
                "role": role,
                "enable_thinking": enable_thinking,
                "max_new_tokens": self.max_new_tokens,
            }
            try:
                self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                logger.error(f"RKLLM daemon 写入失败：{e}")
                return ""
            # readline 没有原生 timeout — 用一个 helper 线程实现软超时
            holder: dict = {}
            def _read():
                holder["line"] = self._proc.stdout.readline()
            t = threading.Thread(target=_read, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                logger.error(f"RKLLM daemon 推理超时 {timeout}s（seq={seq}）")
                return ""
            line = holder.get("line", "")
            if not line:
                logger.error("RKLLM daemon EOF（进程死了？）")
                return ""
            try:
                resp = json.loads(line.strip())
            except Exception as e:
                logger.error(f"RKLLM daemon 响应非 JSON：{line[:200]!r} ({e})")
                return ""
            if "error" in resp:
                logger.warning(f"RKLLM 推理 error: {resp['error']}")
                return ""
            text = resp.get("text", "") or ""
            perf = resp.get("perf") or {}
            if perf:
                logger.debug(
                    f"[rkllm seq={seq}] first_token={resp.get('first_token_ms', 0):.0f}ms "
                    f"total={resp.get('total_ms', 0):.0f}ms "
                    f"prefill={perf.get('prefill_tokens')}t/{perf.get('prefill_time_ms', 0):.0f}ms "
                    f"gen={perf.get('generate_tokens')}t/{perf.get('generate_time_ms', 0):.0f}ms"
                )
            return text

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
