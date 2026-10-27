"""Carga del artefacto causal aprobado, con verificación de integridad y respaldo.

El artefacto llega dentro de la imagen (despliegue inmutable), así que la API no
necesita acceso a la red, colas ni almacenamiento del pipeline batch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .telemetry import audit

REQUIRED_KEYS = {"model_name", "version", "treatments", "risk_model", "stress_model", "stress_expectation"}

# Modelo de reglas de respaldo: valores conservadores para operar en modo degradado
# si el artefacto falta o no pasa la verificación de integridad.
FALLBACK_MODEL: dict = {
    "model_name": "vox-causal-fallback-rules",
    "version": "fallback-1",
    "treatments": {
        "long_wait": {"label": "Espera prolongada (> 5 min en cola)", "ate": 0.10,
                      "playbook": "Reconocer la espera y ofrecer devolución de llamada prioritaria."},
        "multi_transfer": {"label": "Múltiples transferencias entre áreas", "ate": 0.10,
                           "playbook": "Tomar propiedad del caso y evitar nuevas transferencias."},
        "billing_error": {"label": "Error de facturación reportado", "ate": 0.10,
                          "playbook": "Validar el cobro y emitir nota de crédito si corresponde."},
    },
    "risk_model": {
        "features": ["long_wait", "multi_transfer", "billing_error", "repeat_contact",
                     "tenure_years", "issue_technical", "stress"],
        "intercept": 0.2,
        "coef": {"long_wait": 0.08, "multi_transfer": 0.08, "billing_error": 0.08,
                 "repeat_contact": 0.05, "tenure_years": -0.015, "issue_technical": 0.0, "stress": 0.25},
    },
    "stress_model": None,
    "stress_expectation": {
        "features": ["long_wait", "multi_transfer", "billing_error", "repeat_contact"],
        "intercept": 0.2,
        "coef": {"long_wait": 0.25, "multi_transfer": 0.2, "billing_error": 0.15, "repeat_contact": 0.1},
        "residual_std": 0.1,
    },
    "context_defaults": {"tenure_years": 5.0, "repeat_contact": 0, "issue_technical": 0},
}


@dataclass(frozen=True)
class LoadedModel:
    artifact: dict
    source: str  # "registry" | "fallback-rules"
    sha256: str | None

    @property
    def version(self) -> str:
        return self.artifact["version"]


class ModelUnavailableError(RuntimeError):
    pass


def load(path: Path, strict: bool = False) -> LoadedModel:
    reason = None
    try:
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        sha_file = Path(str(path) + ".sha256")
        if sha_file.exists():
            expected = sha_file.read_text().split()[0]
            if expected != digest:
                reason = "sha256_mismatch"
        artifact = json.loads(raw)
        if reason is None and not REQUIRED_KEYS.issubset(artifact):
            reason = "schema_invalid"
        if reason is None:
            audit("model_loaded", model=artifact["model_name"], version=artifact["version"], sha256=digest)
            return LoadedModel(artifact=artifact, source="registry", sha256=digest)
    except FileNotFoundError:
        reason = "artifact_missing"
    except (json.JSONDecodeError, UnicodeDecodeError):
        reason = "artifact_corrupt"

    audit("model_fallback", reason=reason, path=str(path), strict=strict)
    if strict:
        raise ModelUnavailableError(reason)
    return LoadedModel(artifact=FALLBACK_MODEL, source="fallback-rules", sha256=None)
