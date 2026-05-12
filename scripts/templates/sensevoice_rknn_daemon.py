#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
SenseVoice RKNN inference daemon — long-running subprocess for av_unified_mvp.

LICENSE NOTE
============
This file imports SenseVoiceInferenceSession + WavFrontend from
happyme531/SenseVoiceSmall-RKNN2 (AGPL-3.0). As an importer it's considered
derivative work under AGPL-3.0; the file itself is therefore AGPL-3.0-or-later.

It MUST be deployed to the 3588 device under `~/SenseVoiceSmall-RKNN2/`
(alongside happyme531's `sensevoice_rknn.py` + `.rknn` model + auxiliaries),
NOT into the av_unified_mvp runtime tree. The license boundary between this
AGPL daemon and the main av_unified_mvp codebase is the subprocess + JSON
line protocol, keeping av_unified_mvp itself outside AGPL scope.

This template is kept in `scripts/templates/` of the av_unified_mvp repo
for deploy reproducibility; it is not loaded at runtime by any module here.

Protocol
========
  Handshake: stdout `{"ready": true}` once model loaded.
  Request line (stdin):  {"wav_path": "...", "language": "auto|zh|en|ja|ko|yue", "seq": N, "use_itn": false}
  Response line (stdout): {"seq": N, "text": "...", "encoder_ms": ms, "audio_s": s}
  Error line (stdout):    {"seq": N, "error": "msg"}
"""
import json
import os
import sys
import time
import logging
from pathlib import Path

import numpy as np
import soundfile as sf

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))

from sensevoice_rknn import (
    SenseVoiceInferenceSession,
    WavFrontend,
    languages,
)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# happyme531 SenseVoiceInferenceSession.__call__ prints debug to stdout (e.g.
# "padded shape: ...", "encoder inference time: ..."). This pollutes our JSON
# line protocol — redirect stdout during inference, write JSON to original.
_real_stdout = sys.stdout


def main():
    front = WavFrontend(str(THIS / "am.mvn"))
    model = SenseVoiceInferenceSession(
        str(THIS / "embedding.npy"),
        str(THIS / "sense-voice-encoder.rknn"),
        str(THIS / "chn_jpn_yue_eng_ko_spectok.bpe.model"),
        device_id=-1,
        intra_op_num_threads=4,
    )
    # daemon ready
    _real_stdout.write(json.dumps({"ready": True}) + "\n")
    _real_stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        seq = 0
        try:
            req = json.loads(line)
            seq = req.get("seq", 0)
            wav_path = req["wav_path"]
            lang = req.get("language", "auto")
            use_itn = req.get("use_itn", False)

            waveform, sr = sf.read(wav_path, dtype="float32", always_2d=True)
            channel = waveform[:, 0]
            audio_s = len(channel) / sr

            t0 = time.time()
            # Mute happyme531 debug prints during inference
            sys.stdout = open(os.devnull, "w")
            try:
                audio_feats = front.get_features(channel)
                text = model(
                    audio_feats[None, ...],
                    language=languages.get(lang, 0),
                    use_itn=use_itn,
                )
            finally:
                sys.stdout.close()
                sys.stdout = _real_stdout
            elapsed_ms = int((time.time() - t0) * 1000)

            resp = {
                "seq": seq,
                "text": text,
                "encoder_ms": elapsed_ms,
                "audio_s": round(audio_s, 3),
            }
            _real_stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            _real_stdout.flush()
        except Exception as e:
            _real_stdout.write(json.dumps({"seq": seq, "error": f"{type(e).__name__}: {e}"}) + "\n")
            _real_stdout.flush()


if __name__ == "__main__":
    main()
