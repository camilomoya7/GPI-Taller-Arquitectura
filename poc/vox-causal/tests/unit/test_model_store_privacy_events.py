import asyncio
import json

import pytest
from app import model_store
from app.events import EventPublisher
from app.privacy import ChannelPolicyError, check_channel, pseudonymize


def test_loads_verified_artifact(model_dir):
    m = model_store.load(model_dir / "model.json")
    assert m.source == "registry" and m.sha256 and m.version


def test_tampered_artifact_falls_back(model_dir):
    path = model_dir / "model.json"
    data = json.loads(path.read_text())
    data["treatments"]["long_wait"]["ate"] = 0.99  # manipulación
    path.write_text(json.dumps(data))
    m = model_store.load(path)
    assert m.source == "fallback-rules"


def test_tampered_artifact_strict_mode_refuses(model_dir):
    (model_dir / "model.json").write_text("{}")
    with pytest.raises(model_store.ModelUnavailableError):
        model_store.load(model_dir / "model.json", strict=True)


def test_missing_and_corrupt_artifact(tmp_path):
    assert model_store.load(tmp_path / "nope.json").source == "fallback-rules"
    (tmp_path / "bad.json").write_text("{not json")
    assert model_store.load(tmp_path / "bad.json").source == "fallback-rules"


def test_schema_validation(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps({"model_name": "x", "version": "1"}))
    assert model_store.load(tmp_path / "m.json").source == "fallback-rules"


def test_pseudonymization_is_stable_and_keyed():
    a = pseudonymize("call-123", "k1")
    assert a == pseudonymize("call-123", "k1")
    assert a != pseudonymize("call-123", "k2")
    assert "call-123" not in a and len(a) == 32


@pytest.mark.parametrize("channel", ["agent", "operator", "OPERATOR", "employee"])
def test_operator_channel_is_forbidden(channel):
    with pytest.raises(ChannelPolicyError, match="AI Act"):
        check_channel(channel)


def test_unknown_channel_rejected_and_customer_allowed():
    with pytest.raises(ChannelPolicyError):
        check_channel("both")
    check_channel("customer")


def test_local_outbox_publish(tmp_path):
    async def go():
        pub = EventPublisher("", "", tmp_path / "out" / "events.jsonl")
        assert pub.mode == "local-outbox"
        pub.publish_nowait({"type": "call.closed", "call_ref": "abc"})
        await pub.close()
    asyncio.run(go())
    lines = (tmp_path / "out" / "events.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["call_ref"] == "abc"


def test_servicebus_mode_detected(tmp_path):
    assert EventPublisher("ns.servicebus.windows.net", "q", tmp_path / "x").mode == "azure-servicebus"
