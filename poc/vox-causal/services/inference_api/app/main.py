"""API de inferencia en tiempo real de Vox-Causal AI (camino caliente).

Endpoints:
  GET  /health                            liveness
  GET  /ready                             readiness (modelo cargado / modo degradado)
  GET  /metrics                           percentiles de latencia por etapa
  GET  /v1/model                          versión, origen e integridad del modelo causal
  POST /v1/infer                          inferencia puntual (REST) sobre 1 ventana de audio
  WS   /v1/stream                         audio del cliente → diagnóstico causal en vivo
  POST /v1/recordings/{call_ref}/access   URL temporal (User Delegation SAS, solo HTTPS)
"""

from __future__ import annotations

import base64
import binascii
import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, status
from pydantic import BaseModel, Field

from . import model_store
from .config import Settings, get_settings
from .events import EventPublisher
from .privacy import ChannelPolicyError, check_channel, pseudonymize
from .sas import SasIssuer, SasNotConfiguredError
from .scm_runtime import CausalRuntime
from .stream import AudioFormat, CallSession
from .telemetry import LatencyRecorder, audit, configure_logging, log_event
from .ws_handler import StreamHandler


class InferRequest(BaseModel):
    call_id: str = Field(min_length=1, max_length=128)
    channel: str = "customer"
    sample_rate: int = 16000
    context: dict = Field(default_factory=dict)
    audio_b64: str = Field(description="PCM16 mono little-endian, idealmente 1 s")


def token_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode(), expected.encode())


def require_token(request: Request) -> str:
    settings: Settings = request.app.state.settings
    if not settings.api_token:
        return "anonymous-dev"
    if not token_matches(request.headers.get("authorization", ""), f"Bearer {settings.api_token}"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido")
    return "api-client"


def record_timings(app: FastAPI, timings: dict[str, float], total: float) -> None:
    rec: LatencyRecorder = app.state.metrics
    for stage, ms in timings.items():
        rec.observe(stage, ms)
    rec.observe("server_total", total)
    if total > app.state.settings.latency_budget_ms:
        rec.incr("budget_exceeded")
    rec.incr("inferences")


def create_app(settings: Settings | None = None, sas_issuer: SasIssuer | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loaded = model_store.load(settings.model_path, strict=settings.strict_model)
        app.state.settings = settings
        app.state.model = loaded
        app.state.runtime = CausalRuntime(loaded.artifact)
        app.state.metrics = LatencyRecorder()
        app.state.sessions = 0
        app.state.publisher = EventPublisher(settings.servicebus_fqdn, settings.servicebus_queue,
                                             settings.outbox_path)
        app.state.sas = sas_issuer or SasIssuer(settings.storage_account_url, settings.recordings_container,
                                                settings.sas_ttl_minutes)
        log_event("startup", model_version=loaded.version, model_source=loaded.source,
                  events=app.state.publisher.mode, region=settings.data_region)
        yield
        await app.state.publisher.close()

    app = FastAPI(title="Vox-Causal AI — Inference API", version="1.0.0", lifespan=lifespan)
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:  # noqa: C901 - solo declara rutas
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        m = app.state.model
        return {"status": "ready", "model_version": m.version, "model_source": m.source,
                "degraded": m.source != "registry"}

    @app.get("/metrics")
    async def metrics(_: str = Depends(require_token)):
        s = app.state.settings
        snap = app.state.metrics.snapshot()
        snap.update(active_sessions=app.state.sessions, max_sessions=s.max_sessions,
                    latency_budget_ms=s.latency_budget_ms, model_version=app.state.model.version)
        return snap

    @app.get("/v1/model")
    async def model_info(_: str = Depends(require_token)):
        m = app.state.model
        return {
            "model_name": m.artifact["model_name"], "version": m.version, "source": m.source,
            "sha256": m.sha256, "data_region": app.state.settings.data_region,
            "treatments": {k: {"label": v["label"], "ate": v["ate"]} for k, v in m.artifact["treatments"].items()},
        }

    @app.post("/v1/infer")
    async def infer(req: InferRequest, _: str = Depends(require_token)):
        return _rest_infer(app, req)

    @app.post("/v1/recordings/{call_ref}/access")
    async def recording_access(call_ref: str, who: str = Depends(require_token)):
        if not call_ref.isalnum() or len(call_ref) > 64:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "call_ref inválido")
        try:
            return app.state.sas.issue_read_url(f"{call_ref}.wav", requested_by=who)
        except SasNotConfiguredError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    @app.websocket("/v1/stream")
    async def stream(ws: WebSocket, token: str = Query(default="")):
        await StreamHandler(app, ws, record_timings, token_matches).run(token)


def _rest_infer(app: FastAPI, req: InferRequest) -> dict:
    import time

    settings: Settings = app.state.settings
    t0 = time.perf_counter()
    try:
        check_channel(req.channel)
        fmt = AudioFormat.parse({"sample_rate": req.sample_rate, "channels": 1})
        audio = base64.b64decode(req.audio_b64, validate=True)
    except ChannelPolicyError as exc:
        audit("channel_rejected", channel=req.channel)
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    session = CallSession(call_ref=pseudonymize(req.call_id, settings.pseudonym_key), runtime=app.state.runtime,
                          fmt=fmt, window_ms=settings.window_ms, hop_ms=settings.hop_ms)
    session.update_context(req.context)
    session.push_audio(audio)
    payload, timings = session.infer()
    total = (time.perf_counter() - t0) * 1000
    record_timings(app, timings, total)
    payload.update(model_version=app.state.model.version, model_source=app.state.model.source,
                   timings_ms={k: round(v, 3) for k, v in {**timings, "server_total": total}.items()})
    return payload


app = create_app()
