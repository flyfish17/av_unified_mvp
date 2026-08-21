"""
speaker_diarizer 核心：CAM++ 逐句嵌入 + 在线余弦质心聚类。

路线（2026-07-29 S1 拍板，见 DEVELOPMENT_PLAN）：
- 嵌入模型 iic/speech_campplus_sv_zh-cn_16k-common（192 维）。加载走 funasr AutoModel
  而非 modelscope pipeline：后者导入链需 addict 等额外包（环境没有，新增依赖是红线），
  funasr 1.3.1 自带 CAM++ 实现且传本地路径即完全离线。
- 在线聚类：嵌入 L2 归一化 → 与各质心余弦相似度取 max → ≥阈值归入并更新质心，
  <阈值新建说话人。不回改历史 ID（流式 UI/store 回填不承受历史重写）。
- 本文件不接管线（S2 最小闭环）；MQTT 订阅/发布在 main.py（S3）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

CAMPP_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"

# 段长约束（秒）：<MIN_EMBED_S 不嵌入不猜；<LOW_CONF_S 照算但置信度降档；
# 新建说话人需 ≥NEW_SPK_MIN_S —— 短段嵌入不可靠（7-29 实测同人短段余弦 p25≈0.30，
# 逼近异人上限 0.28），若允许其开新簇必然过分裂，故短段只可归入已有簇，够不上阈值返回 None。
MIN_EMBED_S = 0.5
LOW_CONF_S = 1.5
NEW_SPK_MIN_S = 1.0


def find_local_model(model_id: str = CAMPP_MODEL_ID) -> Optional[Path]:
    """探测 modelscope 本地缓存，命中返回模型目录，未命中返回 None。

    与 audio_processor/processor.py 的 SenseVoiceSmall 探测同模式：
    离线机上绝不触发 hub 网络探测（会把进程拖崩）。
    """
    for base in (
        Path.home() / ".cache/modelscope/hub/models",
        Path.home() / ".cache/modelscope/hub",
    ):
        cand = base / model_id
        if (cand / "configuration.json").exists() or list(cand.glob("*.bin")) or list(cand.glob("*.pt")):
            return cand
    return None


class CamppEmbedder:
    """CAM++ 说话人嵌入。仅从本地缓存加载（allow_download 交由调用方处理）。"""

    def __init__(self, model_dir: Path):
        # 延迟导入：funasr/torch 较重，仅在真正建 embedder 时引入
        from funasr import AutoModel

        self._model = AutoModel(model=str(model_dir), disable_update=True, disable_pbar=True)

    def embed_wav(self, wav_path: str | Path) -> Optional[np.ndarray]:
        """对 16k 单声道 WAV 文件出 192 维嵌入；失败返回 None（不抛，管线不容崩）。"""
        try:
            res = self._model.generate(input=str(wav_path))
            emb = np.asarray(res[0]["spk_embedding"], dtype=np.float32).reshape(-1)
            n = np.linalg.norm(emb)
            if n == 0 or not np.isfinite(n):
                return None
            return emb / n
        except Exception as e:
            logger.warning(f"嵌入失败 {wav_path}: {e}")
            return None


@dataclass
class _Speaker:
    centroid: np.ndarray  # L2 归一化
    count: int = 1


@dataclass
class Assignment:
    speaker_id: Optional[str]   # "S1" / …；段过短或嵌入失败为 None
    confidence: Optional[float]  # 归入时的余弦相似度（降档段 ×0.8）；新建簇无参照，为 None
    is_new: bool = False


class OnlineSpeakerClusterer:
    """增量余弦质心聚类。线程不安全——调用方（单订阅回调）保证串行。"""

    # 默认阈值 0.35：7-29 真实远场录音标定（同人长段余弦 min 0.448/med 0.611，
    # 异人 max 0.281；0.35 落在两分布之间）。近讲清晰语音常用的 0.5+ 在此域必过分裂。
    def __init__(self, threshold: float = 0.35):
        self.threshold = float(threshold)
        self._speakers: list[_Speaker] = []

    @property
    def num_speakers(self) -> int:
        return len(self._speakers)

    def assign(self, emb: Optional[np.ndarray], duration_s: float) -> Assignment:
        if emb is None or duration_s < MIN_EMBED_S:
            return Assignment(speaker_id=None, confidence=None)

        emb = np.asarray(emb, dtype=np.float32)
        n = np.linalg.norm(emb)
        if n == 0 or not np.isfinite(n):
            return Assignment(speaker_id=None, confidence=None)
        emb = emb / n

        low_conf = duration_s < LOW_CONF_S
        can_spawn = duration_s >= NEW_SPK_MIN_S
        if not self._speakers:
            if not can_spawn:
                return Assignment(speaker_id=None, confidence=None)
            self._speakers.append(_Speaker(centroid=emb))
            return Assignment("S1", None, is_new=True)

        sims = [float(np.dot(sp.centroid, emb)) for sp in self._speakers]
        best = int(np.argmax(sims))
        if sims[best] >= self.threshold:
            sp = self._speakers[best]
            # 短段只归簇不污染质心（其嵌入噪声大）；长段滑动更新，count 封顶防质心冻结
            if not low_conf:
                c = (sp.centroid * min(sp.count, 50) + emb) / (min(sp.count, 50) + 1)
                sp.centroid = c / np.linalg.norm(c)
                sp.count += 1
            conf = sims[best] * (0.8 if low_conf else 1.0)
            return Assignment(f"S{best + 1}", round(conf, 3))

        if not can_spawn:
            return Assignment(speaker_id=None, confidence=None)
        self._speakers.append(_Speaker(centroid=emb))
        return Assignment(f"S{len(self._speakers)}", None, is_new=True)
