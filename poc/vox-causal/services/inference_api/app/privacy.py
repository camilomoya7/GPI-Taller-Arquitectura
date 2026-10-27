"""Protección de datos (UK GDPR / EU AI Act).

* Seudonimización: el identificador de la llamada se reemplaza por un HMAC-SHA256
  con clave secreta (Key Vault). Logs, eventos y auditoría solo ven el seudónimo.
* Solo se analiza el canal del CLIENTE. El análisis de emociones de trabajadores
  está prohibido en la UE (AI Act, art. 5.1.f), por lo que el canal del operador se
  rechaza o se descarta antes de cualquier procesamiento.
* El audio en vivo nunca se escribe a disco en el camino caliente (minimización).
"""

from __future__ import annotations

import hashlib
import hmac

ALLOWED_CHANNEL = "customer"
FORBIDDEN_CHANNELS = {"agent", "operator", "employee", "worker"}


def pseudonymize(call_id: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), call_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


class ChannelPolicyError(ValueError):
    """El cliente pidió analizar un canal no permitido."""


def check_channel(channel: str) -> None:
    ch = (channel or "").strip().lower()
    if ch in FORBIDDEN_CHANNELS:
        raise ChannelPolicyError(
            "Política de privacidad: no se analiza la voz del operador (EU AI Act art. 5.1.f)."
        )
    if ch != ALLOWED_CHANNEL:
        raise ChannelPolicyError("Canal inválido: solo se acepta 'customer'.")
