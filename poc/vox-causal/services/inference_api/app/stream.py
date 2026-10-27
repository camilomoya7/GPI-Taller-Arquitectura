"""Sesión de streaming por llamada: buffer de audio, ventanas deslizantes e inferencia.

* Solo el canal del cliente entra al buffer; el del operador se descarta al decodificar.
* Cada ``hop_ms`` de audio se evalúa la última ventana de ``window_ms``.
* Si llegan varios saltos a la vez (cliente atrasado o red con ráfagas), se evalúa
  solo la ventana más reciente (coalescencia) para no acumular latencia.
* El audio vive solo en memoria y se descarta al cerrar la sesión.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import voxfeatures

from .scm_runtime import CausalRuntime, sanitize_context

SUPPORTED_RATES = {8000, 16000}
EMA_ALPHA = 0.6


@dataclass
class AudioFormat:
    sample_rate: int = 16000
    channels: int = 1
    customer_channel: int = 0

    @classmethod
    def parse(cls, raw: dict | None) -> AudioFormat:
        raw = raw or {}
        fmt = cls(
            sample_rate=int(raw.get("sample_rate", 16000)),
            channels=int(raw.get("channels", 1)),
            customer_channel=int(raw.get("customer_channel", 0)),
        )
        if raw.get("encoding", "pcm_s16le") != "pcm_s16le":
            raise ValueError("encoding no soportado: use pcm_s16le")
        if fmt.sample_rate not in SUPPORTED_RATES:
            raise ValueError(f"sample_rate no soportado: {sorted(SUPPORTED_RATES)}")
        if fmt.channels not in (1, 2) or not 0 <= fmt.customer_channel < fmt.channels:
            raise ValueError("configuración de canales inválida")
        return fmt


@dataclass
class CallSession:
    call_ref: str
    runtime: CausalRuntime
    fmt: AudioFormat
    window_ms: int
    hop_ms: int
    context: dict[str, float] = field(default_factory=dict)
    seq: int = 0
    samples_total: int = 0
    next_hop_at: int = 0
    coalesced: int = 0
    stress_ema: float | None = None
    risk_history: list[float] = field(default_factory=list)
    last: dict | None = None
    started: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.window = int(self.fmt.sample_rate * self.window_ms / 1000)
        self.hop = int(self.fmt.sample_rate * self.hop_ms / 1000)
        self.buffer = np.zeros(0, dtype=np.float32)
        self.next_hop_at = self.window
        self._frame_bytes = 2 * self.fmt.channels
        self._remainder = b""

    def update_context(self, raw: dict | None) -> None:
        merged = {**self.context, **(raw or {})}
        self.context = sanitize_context(merged, self.runtime.defaults)

    def push_audio(self, data: bytes) -> bool:
        """Agrega audio; devuelve True si corresponde emitir una inferencia."""
        data = self._remainder + data
        usable = len(data) - (len(data) % self._frame_bytes)
        self._remainder = data[usable:]
        if usable == 0:
            return False
        mono = voxfeatures.pcm16_to_float(data[:usable], self.fmt.channels, self.fmt.customer_channel)
        self.samples_total += len(mono)
        self.buffer = np.concatenate([self.buffer, mono])[-self.window:]
        if self.samples_total < self.next_hop_at:
            return False
        skipped = (self.samples_total - self.next_hop_at) // self.hop
        self.coalesced += int(skipped)
        self.next_hop_at += (skipped + 1) * self.hop
        return True

    def infer(self) -> tuple[dict, dict[str, float]]:
        t0 = time.perf_counter()
        feats = voxfeatures.extract(self.buffer, self.fmt.sample_rate)
        t1 = time.perf_counter()
        raw_stress = self.runtime.stress_from_prosody(feats)
        if raw_stress is not None:
            self.stress_ema = raw_stress if self.stress_ema is None else (
                EMA_ALPHA * raw_stress + (1 - EMA_ALPHA) * self.stress_ema)
            stress = self.stress_ema
        else:
            stress = None
        result = self.runtime.infer(self.context, stress)
        t2 = time.perf_counter()
        self.seq += 1
        self.risk_history.append(result.churn_risk)
        payload = {
            "type": "inference",
            "seq": self.seq,
            "audio_ms": int(1000 * self.samples_total / self.fmt.sample_rate),
            "stress": result.stress,
            "stress_source": result.stress_source,
            "expected_stress": result.expected_stress,
            "unexplained_stress": result.unexplained_stress,
            "churn_risk": result.churn_risk,
            "risk_level": result.risk_level,
            "root_cause": result.root_cause,
            "causes": result.causes,
            "prosody": feats.as_dict(),
            "prosody_quality": "ok" if raw_stress is not None else "low",
        }
        self.last = payload
        return payload, {"prosody": (t1 - t0) * 1000, "scm": (t2 - t1) * 1000}

    def summary(self, model_version: str, model_source: str) -> dict:
        last = self.last or {}
        return {
            "type": "call.closed",
            "call_ref": self.call_ref,
            "model_version": model_version,
            "model_source": model_source,
            "duration_s": round(self.samples_total / self.fmt.sample_rate, 2),
            "windows": self.seq,
            "coalesced_windows": self.coalesced,
            "context": self.context,
            "final": {
                "churn_risk": last.get("churn_risk"),
                "risk_level": last.get("risk_level"),
                "max_churn_risk": max(self.risk_history) if self.risk_history else None,
                "stress": last.get("stress"),
                "unexplained_stress": last.get("unexplained_stress", False),
                "root_cause": last.get("root_cause"),
            },
        }
