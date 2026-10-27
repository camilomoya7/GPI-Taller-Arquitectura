"""Telemetría y auditoría: logs JSON a stdout (Azure Container Apps los envía a Log Analytics)
y percentiles de latencia en memoria por etapa, expuestos en /metrics."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

import numpy as np

_logger = logging.getLogger("vox.api")


def configure_logging() -> None:
    if _logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def log_event(event: str, **fields) -> None:
    record = {"ts": datetime.now(UTC).isoformat(), "event": event, **fields}
    _logger.info(json.dumps(record, ensure_ascii=False, default=str))


def audit(action: str, **fields) -> None:
    """Registro de auditoría: acciones sensibles (modelo cargado, SAS emitida, canal rechazado)."""
    log_event(action, audit=True, **fields)


class LatencyRecorder:
    def __init__(self, maxlen: int = 20_000) -> None:
        self._data: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        self.counters: dict[str, int] = defaultdict(int)
        self.started = time.time()

    def observe(self, stage: str, ms: float) -> None:
        self._data[stage].append(ms)

    def incr(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    def snapshot(self) -> dict:
        stages = {}
        for stage, values in self._data.items():
            if not values:
                continue
            arr = np.fromiter(values, dtype=np.float64)
            stages[stage] = {
                "count": int(arr.size),
                "p50_ms": round(float(np.percentile(arr, 50)), 3),
                "p95_ms": round(float(np.percentile(arr, 95)), 3),
                "p99_ms": round(float(np.percentile(arr, 99)), 3),
                "max_ms": round(float(arr.max()), 3),
            }
        return {"uptime_s": round(time.time() - self.started, 1), "stages": stages,
                "counters": dict(self.counters)}
