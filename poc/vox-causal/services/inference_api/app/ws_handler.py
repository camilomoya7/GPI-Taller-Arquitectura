"""Manejador del protocolo WebSocket de streaming (una instancia por llamada).

Protocolo:
  cliente → {"type":"start","call_id","channel":"customer","audio":{...},"context":{...}}
  servidor → {"type":"ready", ...}
  cliente → tramas binarias PCM16 (cualquier tamaño)      servidor → {"type":"inference", ...} cada salto
  cliente → {"type":"context","context":{...}}           servidor → {"type":"context_ack"}
  cliente → {"type":"stop"}                               servidor → {"type":"summary"} y cierre

Códigos de cierre: 1008 política (token, canal del operador, protocolo) · 1013 sin capacidad.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .privacy import ChannelPolicyError, check_channel, pseudonymize
from .stream import AudioFormat, CallSession
from .telemetry import audit, log_event

WS_POLICY_VIOLATION = 1008
WS_TRY_AGAIN_LATER = 1013


class StreamHandler:
    def __init__(self, app: FastAPI, ws: WebSocket, record: Callable, token_matches: Callable) -> None:
        self.app, self.ws, self.record, self.token_matches = app, ws, record, token_matches
        self.settings = app.state.settings
        self.session: CallSession | None = None

    async def run(self, token: str) -> None:
        await self.ws.accept()
        if not self._authorized(token):
            await self.ws.close(code=WS_POLICY_VIOLATION, reason="unauthorized")
            return
        if self.app.state.sessions >= self.settings.max_sessions:
            # Protege el SLO de latencia: mejor rechazar y que otra réplica atienda.
            self.app.state.metrics.incr("sessions_rejected_capacity")
            await self.ws.close(code=WS_TRY_AGAIN_LATER, reason="capacity")
            return
        self.app.state.sessions += 1
        self.app.state.metrics.incr("sessions_opened")
        try:
            if await self._handshake():
                await self._loop()
        except WebSocketDisconnect:
            pass
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log_event("stream_protocol_error", error=type(exc).__name__)
            await self._safe_close(WS_POLICY_VIOLATION, "protocol_error")
        finally:
            self.app.state.sessions -= 1
            self._publish_summary()
            self.session = None  # el audio en memoria se descarta: nunca se persiste en el camino caliente

    def _authorized(self, token: str) -> bool:
        expected = self.settings.api_token
        if not expected:
            return True
        header = self.ws.headers.get("authorization", "")
        return self.token_matches(header, f"Bearer {expected}") or self.token_matches(token, expected)

    async def _handshake(self) -> bool:
        start = json.loads(await self.ws.receive_text())
        if start.get("type") != "start":
            await self._safe_close(WS_POLICY_VIOLATION, "expected start")
            return False
        try:
            check_channel(start.get("channel", "customer"))
            fmt = AudioFormat.parse(start.get("audio"))
        except ChannelPolicyError as exc:
            audit("channel_rejected", channel=start.get("channel"))
            return await self._reject("channel_forbidden", str(exc))
        except ValueError as exc:
            return await self._reject("bad_audio_format", str(exc))

        call_id = str(start.get("call_id") or uuid.uuid4())
        self.session = CallSession(
            call_ref=pseudonymize(call_id, self.settings.pseudonym_key), runtime=self.app.state.runtime,
            fmt=fmt, window_ms=self.settings.window_ms, hop_ms=self.settings.hop_ms)
        self.session.update_context(start.get("context"))
        model = self.app.state.model
        await self.ws.send_json({"type": "ready", "call_ref": self.session.call_ref,
                                 "model_version": model.version, "model_source": model.source,
                                 "window_ms": self.settings.window_ms, "hop_ms": self.settings.hop_ms})
        return True

    async def _reject(self, code: str, detail: str) -> bool:
        await self.ws.send_json({"type": "error", "code": code, "detail": detail})
        await self._safe_close(WS_POLICY_VIOLATION, code)
        return False

    async def _loop(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await self._on_audio(msg["bytes"])
            elif not await self._on_control(json.loads(msg.get("text") or "{}")):
                return

    async def _on_audio(self, data: bytes) -> None:
        t0 = time.perf_counter()
        if not self.session.push_audio(data):
            return
        payload, timings = self.session.infer()
        total = (time.perf_counter() - t0) * 1000
        self.record(self.app, timings, total)
        payload["timings_ms"] = {k: round(v, 3) for k, v in {**timings, "server_total": total}.items()}
        await self.ws.send_json(payload)

    async def _on_control(self, control: dict) -> bool:
        kind = control.get("type")
        if kind == "context":
            self.session.update_context(control.get("context"))
            await self.ws.send_json({"type": "context_ack", "context": self.session.context})
        elif kind == "stop":
            model = self.app.state.model
            await self.ws.send_json({**self.session.summary(model.version, model.source), "type": "summary"})
            await self.ws.close()
            return False
        return True

    def _publish_summary(self) -> None:
        if self.session is None or self.session.seq == 0:
            return
        model = self.app.state.model
        event = self.session.summary(model.version, model.source)
        self.app.state.publisher.publish_nowait(event)
        log_event("call_closed", call_ref=self.session.call_ref, windows=self.session.seq,
                  coalesced=self.session.coalesced, risk=event["final"]["churn_risk"])

    async def _safe_close(self, code: int, reason: str) -> None:
        try:
            await self.ws.close(code=code, reason=reason)
        except RuntimeError:  # pragma: no cover - el cliente ya cerró
            pass
