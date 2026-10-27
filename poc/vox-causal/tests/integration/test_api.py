"""Pruebas de integración de la API (REST + WebSocket) con el modelo aprobado."""

import base64
import json
from dataclasses import replace

import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from pipeline.synth_audio import interleave_stereo, synth_speech
from starlette.websockets import WebSocketDisconnect

from tests.unit.test_sas import FakeBlobService


@pytest.fixture()
def settings(model_dir, tmp_path):
    return replace(Settings(), model_path=model_dir / "model.json", api_token="",
                   outbox_path=tmp_path / "outbox" / "events.jsonl", storage_account_url="")


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def _start(channel="customer", channels=1, context=None):
    return json.dumps({"type": "start", "call_id": "call-001", "channel": channel,
                       "audio": {"sample_rate": 16000, "channels": channels, "customer_channel": 0},
                       "context": context or {"long_wait": 1}})


def test_health_ready_model(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["model_source"] == "registry" and ready["degraded"] is False
    info = client.get("/v1/model").json()
    assert set(info["treatments"]) == {"long_wait", "multi_transfer", "billing_error"}
    assert info["data_region"] == "uksouth"


def test_rest_inference(client, pcm_audio):
    body = {"call_id": "c1", "context": {"billing_error": 1},
            "audio_b64": base64.b64encode(pcm_audio(0.7)).decode()}
    r = client.post("/v1/infer", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["root_cause"]["cause"] == "billing_error"
    assert data["timings_ms"]["server_total"] < 200
    assert client.get("/metrics").json()["counters"]["inferences"] == 1


def test_rest_rejects_operator_channel_and_bad_audio(client):
    r = client.post("/v1/infer", json={"call_id": "c", "channel": "operator", "audio_b64": ""})
    assert r.status_code == 403
    r = client.post("/v1/infer", json={"call_id": "c", "audio_b64": "%%%"})
    assert r.status_code == 400


def test_auth_required_when_token_set(settings):
    with TestClient(create_app(replace(settings, api_token="s3cret"))) as c:
        assert c.get("/v1/model").status_code == 401
        assert c.get("/v1/model", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        with c.websocket_connect("/v1/stream") as ws, pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
        with c.websocket_connect("/v1/stream?token=s3cret") as ws:
            ws.send_text(_start())
            assert ws.receive_json()["type"] == "ready"


def test_stream_full_call_publishes_event(client, settings, rng):
    audio = b"".join(
        interleave_stereo(synth_speech(s, 1.0, rng), synth_speech(0.9, 1.0, rng)) for s in (0.3, 0.5, 0.8)
    )
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text(_start(channels=2))
        ready = ws.receive_json()
        assert ready["type"] == "ready" and len(ready["call_ref"]) == 32
        inferences = []
        frame = 16000 * 4 // 10  # 100 ms estéreo
        for i in range(0, len(audio), frame):
            ws.send_bytes(audio[i:i + frame])
            if i == frame * 15:
                ws.send_text(json.dumps({"type": "context", "context": {"multi_transfer": 1}}))
        ws.send_text(json.dumps({"type": "stop"}))
        while True:
            msg = ws.receive_json()
            if msg["type"] == "inference":
                inferences.append(msg)
            elif msg["type"] == "summary":
                summary = msg
                break
    assert len(inferences) >= 4
    assert all(m["timings_ms"]["server_total"] < 200 for m in inferences)
    assert inferences[-1]["stress"] > inferences[0]["stress"]
    assert {c["cause"] for c in inferences[-1]["causes"]} == {"long_wait", "multi_transfer"}
    assert summary["final"]["root_cause"] is not None
    events = settings.outbox_path.read_text().splitlines()
    event = json.loads(events[-1])
    assert event["type"] == "call.closed" and "call-001" not in json.dumps(event)


def test_operator_voice_does_not_influence_result(client, rng):
    customer = synth_speech(0.2, 2.0, rng)
    results = []
    for op_stress in (0.0, 1.0):
        op = synth_speech(op_stress, 2.0, rng) if op_stress else customer * 0
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_text(_start(channels=2, context={}))
            ws.receive_json()
            ws.send_bytes(interleave_stereo(customer, op))
            results.append(ws.receive_json()["prosody"])
            ws.send_text(json.dumps({"type": "stop"}))
    assert results[0] == results[1]


def test_stream_rejects_operator_channel(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text(_start(channel="agent"))
        err = ws.receive_json()
        assert err["code"] == "channel_forbidden"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_stream_bad_format_and_protocol(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text(json.dumps({"type": "start", "channel": "customer", "audio": {"sample_rate": 44100}}))
        assert ws.receive_json()["code"] == "bad_audio_format"
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text("not json")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_capacity_limit_rejects_with_1013(settings):
    with TestClient(create_app(replace(settings, max_sessions=0))) as c:
        with c.websocket_connect("/v1/stream") as ws, pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1013


def test_silence_uses_context_fallback(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_text(_start())
        ws.receive_json()
        ws.send_bytes(b"\x00\x00" * 16000)
        msg = ws.receive_json()
        assert msg["prosody_quality"] == "low" and msg["stress_source"] == "context-fallback"


def test_degraded_mode_without_artifact(settings, tmp_path):
    with TestClient(create_app(replace(settings, model_path=tmp_path / "missing.json"))) as c:
        ready = c.get("/ready").json()
        assert ready["degraded"] is True and ready["model_source"] == "fallback-rules"


def test_recording_access(settings):
    with TestClient(create_app(settings)) as c:
        assert c.post("/v1/recordings/abc123/access").status_code == 503
        assert c.post("/v1/recordings/bad..ref/access").status_code == 400
    from app.sas import SasIssuer
    issuer = SasIssuer("https://stvox.blob.core.windows.net", "recordings", 5, service_client=FakeBlobService())
    with TestClient(create_app(settings, sas_issuer=issuer)) as c:
        res = c.post("/v1/recordings/abc123/access").json()
        assert "spr=https" in res["url"] and "sp=r" in res["url"]
