"""Extracción de rasgos prosódicos sobre una ventana de audio PCM mono.

Librería compartida por el camino caliente (API de inferencia) y el camino frío
(pipeline batch). Compartir exactamente el mismo código evita el desfase
entrenamiento/servicio (training-serving skew): el modelo se calibra con los
mismos rasgos que verá en producción.

Solo depende de NumPy para mantener la latencia baja (sin librosa ni torch).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

FEATURE_NAMES = (
    "f0_mean_hz",
    "f0_std_st",
    "jitter",
    "energy_db",
    "energy_std_db",
    "zcr",
    "voiced_ratio",
)

_F0_MIN_HZ = 70.0
_F0_MAX_HZ = 400.0
_FRAME_S = 0.040
_HOP_S = 0.020
_VOICING_THRESHOLD = 0.45
_SILENCE_DB = -45.0


@dataclass(frozen=True)
class ProsodyFeatures:
    f0_mean_hz: float
    f0_std_st: float
    jitter: float
    energy_db: float
    energy_std_db: float
    zcr: float
    voiced_ratio: float

    def as_vector(self) -> np.ndarray:
        return np.array([getattr(self, n) for n in FEATURE_NAMES], dtype=np.float64)

    def as_dict(self) -> dict[str, float]:
        return {k: round(float(v), 5) for k, v in asdict(self).items()}


def pcm16_to_float(raw: bytes, channels: int = 1, keep_channel: int = 0) -> np.ndarray:
    """Convierte PCM int16 little-endian a float32 en [-1, 1].

    Si el audio es multicanal, conserva solo ``keep_channel`` y descarta el resto
    sin procesarlo (en Vox-Causal, el canal del operador nunca se analiza).
    """
    samples = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        usable = len(samples) - (len(samples) % channels)
        samples = samples[:usable].reshape(-1, channels)[:, keep_channel]
    return samples.astype(np.float32) / 32768.0


def _frames(signal: np.ndarray, frame_len: int, hop: int) -> np.ndarray:
    if len(signal) < frame_len:
        return np.empty((0, frame_len), dtype=signal.dtype)
    n = 1 + (len(signal) - frame_len) // hop
    idx = np.arange(frame_len)[None, :] + hop * np.arange(n)[:, None]
    return signal[idx]


def extract(signal: np.ndarray, sample_rate: int = 16000) -> ProsodyFeatures:
    """Calcula los rasgos prosódicos de una ventana (típicamente 1 s)."""
    frame_len = int(_FRAME_S * sample_rate)
    hop = int(_HOP_S * sample_rate)
    frames = _frames(signal.astype(np.float64, copy=False), frame_len, hop)
    if frames.shape[0] == 0:
        return ProsodyFeatures(0.0, 0.0, 0.0, -90.0, 0.0, 0.0, 0.0)

    frames = frames - frames.mean(axis=1, keepdims=True)
    rms = np.sqrt(np.mean(frames**2, axis=1)) + 1e-10
    energy_db = 20.0 * np.log10(rms)
    signs = np.signbit(frames)
    zcr = np.mean(signs[:, 1:] != signs[:, :-1], axis=1)

    # Autocorrelación normalizada vía FFT, en lote para todas las tramas.
    n_fft = 1 << (2 * frame_len - 1).bit_length()
    windowed = frames * np.hanning(frame_len)
    spec = np.fft.rfft(windowed, n=n_fft, axis=1)
    acf = np.fft.irfft(spec * np.conj(spec), n=n_fft, axis=1)[:, :frame_len]
    acf = acf / (acf[:, :1] + 1e-12)

    lag_min = int(sample_rate / _F0_MAX_HZ)
    lag_max = min(int(sample_rate / _F0_MIN_HZ), frame_len - 1)
    region = acf[:, lag_min:lag_max]
    best = np.argmax(region, axis=1)
    peak = region[np.arange(region.shape[0]), best]
    lag = (best + lag_min).astype(np.float64)

    # Interpolación parabólica para refinar el lag (más precisión en f0).
    rows = np.arange(region.shape[0])
    left = region[rows, np.clip(best - 1, 0, region.shape[1] - 1)]
    right = region[rows, np.clip(best + 1, 0, region.shape[1] - 1)]
    denom = left - 2 * peak + right
    safe = np.where(np.abs(denom) > 1e-9, denom, 1.0)
    shift = np.where(np.abs(denom) > 1e-9, 0.5 * (left - right) / safe, 0.0)
    lag = lag + np.clip(shift, -0.5, 0.5)

    voiced = (peak > _VOICING_THRESHOLD) & (energy_db > _SILENCE_DB)
    voiced_ratio = float(np.mean(voiced))
    speech = energy_db > _SILENCE_DB
    energy_mean = float(np.mean(energy_db[speech])) if speech.any() else -90.0
    energy_std = float(np.std(energy_db[speech])) if speech.sum() > 1 else 0.0
    zcr_mean = float(np.mean(zcr[speech])) if speech.any() else 0.0

    if voiced.sum() >= 3:
        f0 = sample_rate / lag[voiced]
        semitones = 12.0 * np.log2(f0 / np.median(f0))
        f0_mean = float(np.mean(f0))
        f0_std = float(np.std(semitones))
        jitter = float(np.mean(np.abs(np.diff(f0))) / f0_mean)
    else:
        f0_mean, f0_std, jitter = 0.0, 0.0, 0.0

    return ProsodyFeatures(
        f0_mean_hz=f0_mean,
        f0_std_st=f0_std,
        jitter=jitter,
        energy_db=energy_mean,
        energy_std_db=energy_std,
        zcr=zcr_mean,
        voiced_ratio=voiced_ratio,
    )
