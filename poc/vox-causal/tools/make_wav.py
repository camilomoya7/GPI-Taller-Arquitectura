"""Genera una grabación WAV sintética (sin datos personales) para la demo de SAS."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "batch_pipeline"))
from pipeline.synth_audio import SAMPLE_RATE, synth_speech, to_pcm16  # noqa: E402


def main(out: str = "demo-recording.wav", seconds: int = 5) -> int:
    audio = synth_speech(0.6, seconds, np.random.default_rng(1))
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(to_pcm16(audio))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:2]))
