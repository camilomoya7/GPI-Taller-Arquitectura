from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from pipeline.synth_audio import SAMPLE_RATE, synth_speech, to_pcm16

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def model_dir(tmp_path: Path) -> Path:
    """Copia del artefacto aprobado (model.json + sha256) en un directorio temporal."""
    for name in ("model.json", "model.json.sha256"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path


@pytest.fixture()
def artifact() -> dict:
    return json.loads((FIXTURES / "model.json").read_text())


@pytest.fixture()
def rng() -> np.random.Generator:
    return np.random.default_rng(123)


@pytest.fixture()
def pcm_audio(rng):
    def make(stress: float = 0.5, seconds: float = 1.0) -> bytes:
        return to_pcm16(synth_speech(stress, seconds, rng))
    return make


__all__ = ["SAMPLE_RATE"]
