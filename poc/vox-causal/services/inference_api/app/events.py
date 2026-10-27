"""Publicación asíncrona de eventos `call.closed` hacia el camino frío.

La API solo ENVÍA eventos y nunca espera respuesta del batch (aislamiento). El envío
ocurre en segundo plano, con tiempo máximo; si Azure Service Bus no responde, el
evento se guarda en una bandeja local (outbox) para reintento, sin afectar la llamada.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .telemetry import log_event

SEND_TIMEOUT_S = 3.0


class EventPublisher:
    def __init__(self, fqdn: str, queue: str, outbox: Path) -> None:
        self.fqdn, self.queue, self.outbox = fqdn, queue, Path(outbox)
        self._client = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def mode(self) -> str:
        return "azure-servicebus" if self.fqdn and self.queue else "local-outbox"

    def publish_nowait(self, event: dict) -> None:
        task = asyncio.create_task(self._publish(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _publish(self, event: dict) -> None:
        if self.mode == "azure-servicebus":
            try:
                await asyncio.wait_for(self._send_servicebus(event), timeout=SEND_TIMEOUT_S)
                log_event("event_published", mode=self.mode, call_ref=event.get("call_ref"))
                return
            except Exception as exc:  # pragma: no cover - requiere Azure
                log_event("event_publish_failed", mode=self.mode, error=type(exc).__name__)
        self._write_outbox(event)

    def _write_outbox(self, event: dict) -> None:
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        log_event("event_outboxed", call_ref=event.get("call_ref"), path=str(self.outbox))

    async def _send_servicebus(self, event: dict) -> None:  # pragma: no cover - requiere Azure
        from azure.identity.aio import DefaultAzureCredential
        from azure.servicebus import ServiceBusMessage
        from azure.servicebus.aio import ServiceBusClient

        if self._client is None:
            self._client = ServiceBusClient(self.fqdn, DefaultAzureCredential())
        async with self._client.get_queue_sender(self.queue) as sender:
            await sender.send_messages(ServiceBusMessage(json.dumps(event), content_type="application/json"))

    async def close(self) -> None:
        await self.drain()
        if self._client is not None:  # pragma: no cover
            await self._client.close()
