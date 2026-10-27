"""Simulador de llamada en vivo contra la API (demo para la exposición).

Envía audio estéreo sintético en tiempo real (canal 0 = cliente, canal 1 = operador)
por WebSocket, actualiza el contexto a mitad de la llamada y muestra, ventana a
ventana, el estrés, el riesgo de fuga, la causa raíz y la latencia medida.

Escenarios:
  calm              cliente tranquilo, sin causas operativas
  escalation        espera larga; a los 4 s ocurre una transferencia y sube el estrés
  billing           error de facturación con estrés alto
  operator_channel  intenta analizar la voz del operador → debe ser rechazado (EU AI Act)

Uso:
  python tools/simulate_call.py --url ws://localhost:8000/v1/stream --scenario escalation
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "batch_pipeline"))
from pipeline.synth_audio import SAMPLE_RATE, interleave_stereo, synth_speech  # noqa: E402

SCENARIOS = {
    "calm": {"context": {"tenure_years": 6}, "stress": [0.15] * 8, "update_at": None},
    "escalation": {
        "context": {"long_wait": 1, "tenure_years": 1.5},
        "stress": [0.35, 0.4, 0.45, 0.5, 0.7, 0.8, 0.85, 0.9],
        "update_at": (4, {"multi_transfer": 1}),
    },
    "billing": {"context": {"billing_error": 1, "tenure_years": 3}, "stress": [0.6] * 8, "update_at": None},
    "operator_channel": {"context": {}, "stress": [0.5] * 3, "update_at": None, "channel": "operator"},
}


def build_audio(stress_per_second: list[float], seed: int = 3) -> bytes:
    rng = np.random.default_rng(seed)
    speaker = rng.uniform(0.9, 1.1)
    customer = np.concatenate([synth_speech(s, 1.0, rng, speaker_factor=speaker) for s in stress_per_second])
    operator = np.concatenate([synth_speech(0.9, 1.0, rng) for _ in stress_per_second])  # operador "alterado"
    return interleave_stereo(customer, operator)


async def run(url: str, scenario: str, token: str, frame_ms: int, realtime: bool) -> int:
    sc = SCENARIOS[scenario]
    audio = build_audio(sc["stress"])
    frame_bytes = int(SAMPLE_RATE * frame_ms / 1000) * 4  # estéreo PCM16
    headers = {"Authorization": f"Bearer {token}"} if token else None
    sent_at: dict[int, float] = {}
    lat: list[float] = []
    srv: list[float] = []

    async with websockets.connect(url, additional_headers=headers, max_size=2**20) as ws:
        await ws.send(json.dumps({
            "type": "start", "call_id": f"demo-{scenario}-{int(time.time())}",
            "channel": sc.get("channel", "customer"),
            "audio": {"sample_rate": SAMPLE_RATE, "channels": 2, "customer_channel": 0, "encoding": "pcm_s16le"},
            "context": sc["context"],
        }))
        first = json.loads(await ws.recv())
        if first["type"] == "error":
            print(f"RECHAZADO por la API: {first['code']} — {first['detail']}")
            return 0 if scenario == "operator_channel" else 1
        print(f"Sesión lista · modelo {first['model_version']} ({first['model_source']}) · "
              f"ventana {first['window_ms']} ms, salto {first['hop_ms']} ms\n")
        print(f"{'t(s)':>5} {'estrés':>7} {'riesgo':>7} {'nivel':>6}  {'causa raíz':<40} {'e2e ms':>7} {'srv ms':>7}")

        async def receiver():
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "inference":
                    rtt = (time.perf_counter() - sent_at.get(msg["audio_ms"], time.perf_counter())) * 1000
                    lat.append(rtt)
                    srv.append(msg["timings_ms"]["server_total"])
                    rc = msg["root_cause"]["label"] if msg["root_cause"] else "—"
                    flag = " ⚠ estrés no explicado" if msg["unexplained_stress"] else ""
                    print(f"{msg['audio_ms']/1000:5.1f} {msg['stress']:7.2f} {msg['churn_risk']:7.1%} "
                          f"{msg['risk_level']:>6}  {rc:<40} {rtt:7.1f} {srv[-1]:7.2f}{flag}")
                elif msg["type"] == "context_ack":
                    print(f"      ↳ contexto actualizado: {msg['context']}")
                elif msg["type"] == "summary":
                    print("\nResumen enviado al camino frío (call.closed):")
                    print(json.dumps(msg["final"], ensure_ascii=False, indent=2))
                    return

        rx = asyncio.create_task(receiver())
        pos, audio_ms = 0, 0
        update = sc["update_at"]
        while pos < len(audio):
            chunk = audio[pos:pos + frame_bytes]
            pos += len(chunk)
            audio_ms += int(len(chunk) / 4 / SAMPLE_RATE * 1000)
            sent_at[audio_ms] = time.perf_counter()
            await ws.send(chunk)
            if update and audio_ms == update[0] * 1000:
                await ws.send(json.dumps({"type": "context", "context": update[1]}))
            if realtime:
                await asyncio.sleep(frame_ms / 1000)
        await ws.send(json.dumps({"type": "stop"}))
        await rx

    if lat:
        arr = np.array(lat)
        s_arr = np.array(srv)
        print(f"\nLatencia extremo a extremo (incluye la red cliente→servidor): p50={np.percentile(arr,50):.1f} ms · "
              f"p95={np.percentile(arr,95):.1f} ms · máx={arr.max():.1f} ms")
        print(f"Procesamiento en el servidor: p50={np.percentile(s_arr,50):.2f} ms · "
              f"p95={np.percentile(s_arr,95):.2f} ms (objetivo del camino caliente < 200 ms)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8000/v1/stream")
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="escalation")
    p.add_argument("--token", default="")
    p.add_argument("--frame-ms", type=int, default=100)
    p.add_argument("--fast", action="store_true", help="no esperar tiempo real entre tramas")
    a = p.parse_args()
    return asyncio.run(run(a.url, a.scenario, a.token, a.frame_ms, not a.fast))


if __name__ == "__main__":
    raise SystemExit(main())
