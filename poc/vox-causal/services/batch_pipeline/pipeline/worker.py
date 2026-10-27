"""Worker del camino frío: consume eventos `call.closed` y registra la auditoría.

Fuentes de eventos:
  * Azure Service Bus (SERVICEBUS_FQDN + SERVICEBUS_QUEUE), con identidad administrada.
  * Emulación local: archivo JSONL (OUTBOX_PATH) que escribe la API cuando no hay Service Bus.

Por cada evento genera la explicación para el supervisor y escribe un registro de
auditoría (JSONL local o Blob Storage "audit" si AUDIT_BLOB_ACCOUNT_URL está definido).

Uso:  python -m pipeline.worker --once
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from .explain import explain

log = logging.getLogger("vox.batch.worker")


def process(event: dict) -> dict:
    text, source = explain(event)
    return {
        "type": "call.explained",
        "call_ref": event.get("call_ref"),
        "model_version": event.get("model_version"),
        "final": event.get("final"),
        "explanation": text,
        "explanation_source": source,
        "processed_at": datetime.now(UTC).isoformat(),
    }


def _read_local(outbox: Path, offset_file: Path) -> list[dict]:
    if not outbox.exists():
        return []
    start = int(offset_file.read_text()) if offset_file.exists() else 0
    lines = outbox.read_text(encoding="utf-8").splitlines()
    offset_file.write_text(str(len(lines)))
    return [json.loads(line) for line in lines[start:] if line.strip()]


def _read_servicebus(max_messages: int) -> list[dict]:  # pragma: no cover - requiere Azure
    from azure.identity import DefaultAzureCredential
    from azure.servicebus import ServiceBusClient

    events = []
    with ServiceBusClient(os.environ["SERVICEBUS_FQDN"], DefaultAzureCredential()) as client:
        with client.get_queue_receiver(os.environ["SERVICEBUS_QUEUE"], max_wait_time=5) as rx:
            for msg in rx.receive_messages(max_message_count=max_messages, max_wait_time=5):
                events.append(json.loads(str(msg)))
                rx.complete_message(msg)
    return events


def _write_audit(records: list[dict], audit_path: Path) -> None:
    account = os.getenv("AUDIT_BLOB_ACCOUNT_URL")
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    if account:  # pragma: no cover - requiere Azure
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient(account, credential=DefaultAzureCredential())
        name = f"explanations/{datetime.now(UTC):%Y/%m/%d/%H%M%S%f}.jsonl"
        svc.get_blob_client("audit", name).upload_blob(lines.encode("utf-8"))
        return
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(lines)


def run_once(max_messages: int = 100) -> list[dict]:
    if os.getenv("SERVICEBUS_FQDN") and os.getenv("SERVICEBUS_QUEUE"):
        events = _read_servicebus(max_messages)
    else:
        outbox = Path(os.getenv("OUTBOX_PATH", "var/outbox/events.jsonl"))
        events = _read_local(outbox, outbox.with_suffix(".offset"))
    records = [process(e) for e in events if e.get("type") == "call.closed"]
    if records:
        _write_audit(records, Path(os.getenv("AUDIT_PATH", "var/audit/explanations.jsonl")))
    for r in records:
        log.info(json.dumps({"event": "call_explained", "call_ref": r["call_ref"],
                             "source": r["explanation_source"]}))
    return records


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="procesa lo pendiente y termina")
    p.add_argument("--max", type=int, default=100)
    args = p.parse_args()
    records = run_once(args.max)
    for r in records:
        print(r["explanation"])
    print(f"eventos procesados: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
