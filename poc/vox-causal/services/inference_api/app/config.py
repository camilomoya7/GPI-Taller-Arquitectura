"""Configuración por variables de entorno (12-factor). Los secretos vienen de Key Vault en Azure."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model_path: Path = field(default_factory=lambda: Path(os.getenv("MODEL_PATH", "model/model.json")))
    strict_model: bool = field(default_factory=lambda: _bool("STRICT_MODEL", False))
    api_token: str = field(default_factory=lambda: os.getenv("API_TOKEN", ""))
    pseudonym_key: str = field(default_factory=lambda: os.getenv("PSEUDONYM_KEY", "dev-only-key"))
    window_ms: int = field(default_factory=lambda: int(os.getenv("WINDOW_MS", "1000")))
    hop_ms: int = field(default_factory=lambda: int(os.getenv("HOP_MS", "500")))
    latency_budget_ms: float = field(default_factory=lambda: float(os.getenv("LATENCY_BUDGET_MS", "200")))
    max_sessions: int = field(default_factory=lambda: int(os.getenv("MAX_SESSIONS", "180")))
    servicebus_fqdn: str = field(default_factory=lambda: os.getenv("SERVICEBUS_FQDN", ""))
    servicebus_queue: str = field(default_factory=lambda: os.getenv("SERVICEBUS_QUEUE", ""))
    outbox_path: Path = field(default_factory=lambda: Path(os.getenv("OUTBOX_PATH", "var/outbox/events.jsonl")))
    storage_account_url: str = field(default_factory=lambda: os.getenv("STORAGE_ACCOUNT_URL", ""))
    recordings_container: str = field(default_factory=lambda: os.getenv("RECORDINGS_CONTAINER", "recordings"))
    sas_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("SAS_TTL_MINUTES", "5")))
    data_region: str = field(default_factory=lambda: os.getenv("DATA_REGION", "uksouth"))


def get_settings() -> Settings:
    return Settings()
