"""Perfil de latencia por etapa del camino caliente, sin red (aislado del cliente de carga).

Ejecuta N inferencias reales (CallSession → rasgos prosódicos → runtime causal) con el modelo
aprobado y guarda p50/p95/p99 por etapa en bench/results/server_stages.json.

Uso:  taskset -c 0 python bench/stage_profile.py --n 20000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs/voxfeatures", "services/inference_api", "services/batch_pipeline"):
    sys.path.insert(0, str(ROOT / p))

from app.scm_runtime import CausalRuntime  # noqa: E402
from app.stream import AudioFormat, CallSession  # noqa: E402
from pipeline.synth_audio import synth_speech, to_pcm16  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20_000)
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "server_stages.json")
    a = ap.parse_args()
    artifact = json.loads((ROOT / "services/inference_api/model/model.json").read_text())
    runtime = CausalRuntime(artifact)
    rng = np.random.default_rng(0)
    clips = [to_pcm16(synth_speech(s, 1.0, rng)) for s in np.linspace(0.05, 0.95, 40)]
    stages: dict[str, list[float]] = {"prosody": [], "scm": [], "server_total": []}
    for i in range(a.n):
        t0 = time.perf_counter()
        s = CallSession(call_ref="x", runtime=runtime, fmt=AudioFormat(), window_ms=1000, hop_ms=500)
        s.update_context({"long_wait": i % 2, "multi_transfer": int(i % 3 == 0), "tenure_years": i % 10})
        s.push_audio(clips[i % len(clips)])
        _, timings = s.infer()
        stages["prosody"].append(timings["prosody"])
        stages["scm"].append(timings["scm"])
        stages["server_total"].append((time.perf_counter() - t0) * 1000)
    out = {k: {"count": len(v), **{f"p{q}_ms": round(float(np.percentile(v, q)), 3) for q in (50, 95, 99)}}
           for k, v in stages.items()}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
