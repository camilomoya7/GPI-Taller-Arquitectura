import base64
from urllib.parse import parse_qs, urlparse

import pytest
from app.sas import SasIssuer, SasNotConfiguredError
from azure.storage.blob import UserDelegationKey


class FakeBlobService:
    """Simula BlobServiceClient.get_user_delegation_key (Entra ID) sin red."""

    def __init__(self):
        self.calls = 0

    def get_user_delegation_key(self, start, expiry):
        self.calls += 1
        k = UserDelegationKey()
        k.signed_oid = "11111111-1111-1111-1111-111111111111"
        k.signed_tid = "22222222-2222-2222-2222-222222222222"
        k.signed_start = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        k.signed_expiry = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
        k.signed_service = "b"
        k.signed_version = "2024-11-04"
        k.value = base64.b64encode(b"0" * 32).decode()
        return k


def _issuer(svc=None, url="https://stvoxcausal.blob.core.windows.net", ttl=5):
    return SasIssuer(url, "recordings", ttl, service_client=svc or FakeBlobService())


def test_user_delegation_sas_is_https_only_read_only_and_short_lived():
    res = _issuer().issue_read_url("abc123.wav", requested_by="supervisor")
    q = parse_qs(urlparse(res["url"]).query)
    assert urlparse(res["url"]).scheme == "https"
    assert q["spr"] == ["https"]          # solo HTTPS: cifrado en tránsito obligatorio
    assert q["sp"] == ["r"]               # mínimo privilegio: solo lectura
    assert "skoid" in q and "sktid" in q  # firmada con Entra ID (User Delegation), no con clave de cuenta
    assert q["sr"] == ["b"]               # un único blob
    assert res["sas_type"] == "user_delegation" and res["permissions"] == "r"


def test_delegation_key_is_cached():
    svc = FakeBlobService()
    issuer = _issuer(svc)
    issuer.issue_read_url("a.wav", "x")
    issuer.issue_read_url("b.wav", "x")
    assert svc.calls == 1


def test_not_configured_raises():
    with pytest.raises(SasNotConfiguredError):
        SasIssuer("", "recordings", 5).issue_read_url("a.wav", "x")


def test_plain_http_account_rejected():
    with pytest.raises(ValueError):
        _issuer(url="http://stvoxcausal.blob.core.windows.net").issue_read_url("a.wav", "x")


def test_ttl_is_bounded():
    assert SasIssuer("https://a.blob.core.windows.net", "c", 999).ttl.total_seconds() == 3600
