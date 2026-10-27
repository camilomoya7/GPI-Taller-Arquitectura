"""Benchmark de latencia y concurrencia por WebSocket (KPIs: < 200 ms y 1.500 llamadas).

Abre N llamadas simultáneas que envían audio en TIEMPO REAL (tramas de 200 ms), igual
que lo haría la plataforma de telefonía. Para cada inferencia mide la latencia
extremo a extremo: desde que el cliente envía la trama que completa una ventana
hasta que recibe el diagnóstico.

Uso:
  python bench/ws_load.py --url ws://localhost:8000/v1/stream --streams 200 --seconds 20
  python bench/ws_load.py --sweep 50,100,200,300,400 --seconds 20 --out bench/results/sweep.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "batch_pipeline"))
sys.path.insert(0, "/srv")  # dentro de la imagen del camino frío (job de benchmark)
from pipeline.synth_audio import SAMPLE_RATE, synth_speech, to_pcm16  # noqa: E402

FRAME_MS = 200


def make_audio(seconds: int) -> bytes:
    rng = np.random.default_rng(0)
    return to_pcm16(np.concatenate([synth_speech(rng.uniform(0.1, 0.9), 1.0, rng) for _ in range(seconds)]))


async def one_call(i: int, url: str, audio: bytes, token: str, lat: list, errors: dict, start_delay: float):
    await asyncio.sleep(start_delay)
    frame_bytes = int(SAMPLE_RATE * FRAME_MS / 1000) * 2
    sent: dict[int, float] = {}
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        async with websockets.connect(url, additional_headers=headers, max_size=2**20, open_timeout=30) as ws:
            await ws.send(json.dumps({
                "type": "start", "call_id": f"bench-{i}", "channel": "customer",
                "audio": {"sample_rate": SAMPLE_RATE, "channels": 1},
                "context": {"long_wait": i % 2, "multi_transfer": int(i % 3 == 0), "tenure_years": i % 10},
            }))
            ready = json.loads(await ws.recv())
            if ready.get("type") != "ready":
                errors["rejected"] += 1
                return

            async def rx():
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg["type"] == "inference" and msg["audio_ms"] in sent:
                        lat.append((time.perf_counter() - sent[msg["audio_ms"]]) * 1000)
                    elif msg["type"] == "summary":
                        return

            task = asyncio.create_task(rx())
            t_start = time.perf_counter()
            pos, audio_ms, k = 0, 0, 0
            while pos < len(audio):
                chunk = audio[pos:pos + frame_bytes]
                pos += len(chunk)
                audio_ms += FRAME_MS
                sent[audio_ms] = time.perf_counter()
                await ws.send(chunk)
                k += 1
                # ritmo de tiempo real sin deriva acumulada
                await asyncio.sleep(max(0.0, t_start + k * FRAME_MS / 1000 - time.perf_counter()))
            await ws.send(json.dumps({"type": "stop"}))
            await asyncio.wait_for(task, timeout=10)
    except websockets.exceptions.ConnectionClosedError as exc:
        errors["closed_" + str(exc.rcvd.code if exc.rcvd else "none")] += 1
    except Exception as exc:  # noqa: BLE001
        errors[type(exc).__name__] += 1


async def run_level(url: str, streams: int, seconds: int, token: str) -> dict:
    from collections import defaultdict

    audio = make_audio(seconds)
    lat: list[float] = []
    errors: dict = defaultdict(int)
    ramp = min(5.0, streams / 100)
    t0 = time.perf_counter()
    await asyncio.gather(*[
        one_call(i, url, audio, token, lat, errors, random.uniform(0, ramp)) for i in range(streams)
    ])
    arr = np.array(lat) if lat else np.array([np.nan])
    return {
        "streams": streams,
        "seconds_audio_per_call": seconds,
        "inferences": len(lat),
        "p50_ms": round(float(np.nanpercentile(arr, 50)), 2),
        "p95_ms": round(float(np.nanpercentile(arr, 95)), 2),
        "p99_ms": round(float(np.nanpercentile(arr, 99)), 2),
        "max_ms": round(float(np.nanmax(arr)), 2),
        "pct_under_200ms": round(float(np.mean(arr < 200) * 100), 2) if lat else 0.0,
        "errors": dict(errors),
        "wall_s": round(time.perf_counter() - t0, 1),
    }


async def main_async(a) -> list[dict]:
    levels = [int(x) for x in a.sweep.split(",")] if a.sweep else [a.streams]
    results = []
    for n in levels:
        r = await run_level(a.url, n, a.seconds, a.token)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False))
        await asyncio.sleep(2)
    return results


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8000/v1/stream")
    p.add_argument("--streams", type=int, default=100)
    p.add_argument("--sweep", default="")
    p.add_argument("--seconds", type=int, default=20)
    p.add_argument("--token", default="")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    results = asyncio.run(main_async(a))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    if os.getenv("BENCH_RESULTS_ACCOUNT_URL"):  # job en Azure: guarda la evidencia en Blob
        _upload_results(results)
    return 0


def _upload_results(results: list[dict]) -> None:  # pragma: no cover - requiere Azure
    from datetime import UTC, datetime

    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(os.environ["BENCH_RESULTS_ACCOUNT_URL"], credential=DefaultAzureCredential())
    name = f"bench/{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    payload = {"region": os.getenv("BENCH_REGION", "?"), "results": results}
    svc.get_blob_client("evidence", name).upload_blob(json.dumps(payload, indent=2).encode())
    svc.get_blob_client("evidence", "bench/latest.json").upload_blob(
        json.dumps(payload, indent=2).encode(), overwrite=True)


if __name__ == "__main__":
    raise SystemExit(main())
