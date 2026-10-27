"""Generador de voz sintética con nivel de estrés conocido.

No existe un corpus etiquetado de Alloxentric disponible para el equipo (datos
personales bajo UK GDPR). Para calibrar y validar el estimador prosódico se
generan señales tipo voz (fuente armónica + sílabas + pausas) cuyo nivel de
estrés ``s`` en [0, 1] es conocido por construcción:

* la frecuencia fundamental sube con el estrés (≈110 Hz → ≈240 Hz),
* la entonación y el jitter aumentan,
* la energía aumenta y las pausas se acortan.

Cada "hablante" tiene una variación aleatoria propia, de modo que el problema no
es trivial y el error de estimación es realista.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000


def synth_speech(
    stress: float,
    seconds: float,
    rng: np.random.Generator,
    sample_rate: int = SAMPLE_RATE,
    speaker_factor: float | None = None,
) -> np.ndarray:
    """Devuelve audio float32 mono en [-1, 1] con el estrés indicado."""
    s = float(np.clip(stress, 0.0, 1.0))
    speaker = speaker_factor if speaker_factor is not None else rng.uniform(0.85, 1.15)
    n_total = int(seconds * sample_rate)
    out = np.zeros(n_total, dtype=np.float64)

    base_f0 = (110.0 + 130.0 * s) * speaker
    intonation = 0.04 + 0.12 * s
    jitter = 0.004 + 0.03 * s
    amplitude = 0.08 + 0.35 * s
    pause_mean = 0.22 - 0.16 * s

    pos = int(rng.uniform(0.0, 0.05) * sample_rate)
    while pos < n_total:
        syl_len = int(rng.uniform(0.12, 0.25) * sample_rate)
        end = min(pos + syl_len, n_total)
        n = end - pos
        if n <= 0:
            break
        t = np.arange(n) / sample_rate
        contour = 1.0 + intonation * np.sin(2 * np.pi * rng.uniform(1.5, 4.0) * t + rng.uniform(0, 6.28))
        f0 = base_f0 * rng.uniform(0.93, 1.07) * contour
        f0 = f0 * (1.0 + jitter * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)))
        phase = 2 * np.pi * np.cumsum(f0) / sample_rate
        voice = sum((0.8**k) * np.sin((k + 1) * phase) for k in range(5))
        envelope = np.sin(np.pi * np.linspace(0, 1, n)) ** 0.6
        out[pos:end] += amplitude * rng.uniform(0.85, 1.15) * envelope * voice / 2.5
        pos = end + int(max(0.02, rng.exponential(pause_mean)) * sample_rate)

    out += 0.002 * rng.standard_normal(n_total)
    return np.clip(out, -1.0, 1.0).astype(np.float32)


def to_pcm16(signal: np.ndarray) -> bytes:
    return (np.clip(signal, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def interleave_stereo(customer: np.ndarray, operator: np.ndarray) -> bytes:
    """PCM16 estéreo intercalado: canal 0 = cliente, canal 1 = operador."""
    n = min(len(customer), len(operator))
    stereo = np.stack([customer[:n], operator[:n]], axis=1)
    return (np.clip(stereo, -1.0, 1.0) * 32767).astype("<i2").tobytes()
