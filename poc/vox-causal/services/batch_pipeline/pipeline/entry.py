"""Punto de entrada de los Container Apps Jobs del camino frío.

JOB_MODE:
  worker  (por defecto) procesa eventos call.closed pendientes en Service Bus
  train   entrena, valida y publica el modelo en el registro (y en Blob si está configurado)
  bench   cliente de carga EN LA MISMA REGIÓN que la API (simula la plataforma de telefonía)
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    mode = os.getenv("JOB_MODE", "worker").strip().lower()
    if mode == "worker":
        from .worker import main as run
        sys.argv = ["worker", "--once"]
    elif mode == "train":
        from .train import main as run
        sys.argv = ["train", "--registry", os.getenv("REGISTRY_DIR", "/srv/registry"),
                    "--replicas", os.getenv("TRAIN_REPLICAS", "5")]
    elif mode == "bench":
        sys.path.insert(0, "/srv")
        from bench.ws_load import main as run
        sys.argv = ["bench", "--url", os.environ["API_WS_URL"], "--token", os.getenv("API_TOKEN", ""),
                    "--sweep", os.getenv("BENCH_SWEEP", "100,180"), "--seconds", os.getenv("BENCH_SECONDS", "20")]
    else:
        print(f"JOB_MODE desconocido: {mode}", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
