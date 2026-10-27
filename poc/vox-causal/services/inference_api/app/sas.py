"""Acceso temporal a grabaciones mediante User Delegation SAS (restricción 1).

Por qué así:
* Una SAS NO cifra: es un token de autorización. El cifrado en tránsito lo da TLS.
  Por eso cada SAS se emite con ``spr=https`` (el servicio rechaza HTTP) y la cuenta
  exige TLS 1.2 como mínimo.
* Se usa User Delegation SAS (firmada con Microsoft Entra ID mediante la identidad
  administrada), no SAS con clave de cuenta: la cuenta tiene deshabilitado el acceso
  por clave compartida, puede revocarse y queda trazada en Entra ID.
* Mínimo privilegio: solo lectura, un blob, expiración corta (5 min por defecto).
* Esta operación es de plano de control (supervisor que escucha una grabación):
  NO está en el camino de inferencia en vivo y no afecta la latencia < 200 ms.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from .telemetry import audit


class SasNotConfiguredError(RuntimeError):
    pass


class SasIssuer:
    def __init__(self, account_url: str, container: str, ttl_minutes: int, service_client=None) -> None:
        self.account_url = account_url.rstrip("/")
        self.container = container
        self.ttl = timedelta(minutes=max(1, min(ttl_minutes, 60)))
        self._client = service_client
        self._key = None
        self._key_expiry: datetime | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.account_url)

    def _service(self):
        if self._client is None:  # pragma: no cover - requiere Azure
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient

            self._client = BlobServiceClient(self.account_url, credential=DefaultAzureCredential())
        return self._client

    def _delegation_key(self, now: datetime):
        # La clave de delegación se cachea (válida 1 h) para no pedirla en cada solicitud.
        with self._lock:
            if self._key is None or self._key_expiry is None or now + self.ttl >= self._key_expiry:
                start = now - timedelta(minutes=5)
                expiry = now + timedelta(hours=1)
                self._key = self._service().get_user_delegation_key(start, expiry)
                self._key_expiry = expiry
            return self._key

    def issue_read_url(self, blob_name: str, requested_by: str) -> dict:
        if not self.configured:
            raise SasNotConfiguredError("STORAGE_ACCOUNT_URL no configurado")
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        if not self.account_url.startswith("https://"):
            raise ValueError("La cuenta de almacenamiento debe usar https://")
        now = datetime.now(UTC)
        expiry = now + self.ttl
        account_name = urlparse(self.account_url).hostname.split(".")[0]
        token = generate_blob_sas(
            account_name=account_name,
            container_name=self.container,
            blob_name=blob_name,
            user_delegation_key=self._delegation_key(now),
            permission=BlobSasPermissions(read=True),
            start=now - timedelta(minutes=1),
            expiry=expiry,
            protocol="https",
        )
        audit("sas_issued", blob=f"{self.container}/{blob_name}", permissions="r",
              protocol="https", expires_at=expiry.isoformat(), requested_by=requested_by)
        return {
            "url": f"{self.account_url}/{self.container}/{blob_name}?{token}",
            "expires_at": expiry.isoformat(),
            "permissions": "r",
            "protocol": "https",
            "sas_type": "user_delegation",
        }
