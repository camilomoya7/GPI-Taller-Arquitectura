import json

import numpy as np
import pytest
from pipeline import registry, synthetic, train, worker
from pipeline.explain import explain, template_explanation


def test_true_ate_matches_structural_equations():
    ds = synthetic.generate(n=20_000, seed=1)
    # efecto total = efecto directo + efecto mediado por el estrés (sin recorte apreciable)
    assert ds.true_ate["long_wait"] == pytest.approx(0.06 + 0.25 * 0.25, abs=0.005)
    assert ds.true_ate["multi_transfer"] == pytest.approx(0.08 + 0.25 * 0.20, abs=0.005)
    assert ds.true_ate["billing_error"] == pytest.approx(0.10 + 0.25 * 0.15, abs=0.005)


def test_confounding_makes_correlation_misleading():
    df = synthetic.generate(n=30_000, seed=2).data
    naive = df.loc[df.long_wait == 1, "churn"].mean() - df.loc[df.long_wait == 0, "churn"].mean()
    assert naive > 0.15  # la correlación exagera el efecto real (~0.12)


@pytest.mark.slow
def test_dowhy_econml_ate_error_within_kpi():
    ds = synthetic.generate(n=8_000, seed=3)
    est = train._estimate_treatment(ds.data, "billing_error", refute=False)
    assert est["backdoor_set"] == ["tenure_years"]
    assert abs(est["linear_dml"] - ds.true_ate["billing_error"]) <= train.ATE_ERROR_MAX


@pytest.mark.slow
def test_stress_calibration_quality():
    cal = train.calibrate_stress(n_train=150, n_test=80, seed=5)
    assert cal["metrics"]["mae"] < 0.1 and cal["metrics"]["r2"] > 0.8
    assert len(cal["coef"]) == len(cal["feature_names"])


def test_risk_and_expectation_models():
    df = synthetic.generate(n=10_000, seed=4).data
    rm = train.fit_risk_model(df)
    assert rm["coef"]["stress"] > 0.15 and rm["coef"]["tenure_years"] < 0
    se = train.fit_stress_expectation(df)
    assert se["coef"]["long_wait"] == pytest.approx(0.25, abs=0.02)


def test_registry_publish_and_resolve(tmp_path):
    art = {"model_name": "vox-causal-scm", "version": "v1", "x": 1}
    path = registry.publish(tmp_path, art, {"version": "v1"})
    resolved, sha = registry.resolve_production(tmp_path)
    assert resolved == path and len(sha) == 64
    assert sha in (path.parent / "model.json.sha256").read_text()
    rej = registry.write_rejected(tmp_path, {"version": "v2", "quality_gate_passed": False})
    assert rej.exists()


EVENT = {
    "type": "call.closed", "call_ref": "f" * 32, "model_version": "v1",
    "final": {"churn_risk": 0.62, "risk_level": "high", "unexplained_stress": True,
              "root_cause": {"label": "Error de facturación reportado", "effect": 0.137,
                             "playbook": "Validar el cobro."}},
}


def test_template_explanation():
    text = template_explanation(EVENT)
    assert "alto" in text and "facturación" in text and "estrés vocal no explicado" in text
    assert "No se identificó" in template_explanation({**EVENT, "final": {"churn_risk": 0.1}})


def test_explain_without_openai_uses_template(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    assert explain(EVENT)[1] == "template"


def test_worker_processes_local_outbox(tmp_path, monkeypatch):
    outbox = tmp_path / "events.jsonl"
    outbox.write_text(json.dumps(EVENT) + "\n" + json.dumps({"type": "other"}) + "\n")
    monkeypatch.setenv("OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("SERVICEBUS_FQDN", raising=False)
    records = worker.run_once()
    assert len(records) == 1 and records[0]["explanation_source"] == "template"
    assert worker.run_once() == []  # no reprocesa (offset)
    assert (tmp_path / "audit.jsonl").read_text().count("call.explained") == 1


def test_synthetic_data_is_reproducible():
    a = synthetic.generate(n=500, seed=9).data
    b = synthetic.generate(n=500, seed=9).data
    assert np.array_equal(a.values, b.values)


@pytest.mark.slow
def test_full_training_run_publishes_and_gate_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "REFUTE_SIMULATIONS", 3)
    monkeypatch.setattr(train, "calibrate_stress", _small_calibration)
    metrics, passed = train.run(tmp_path, n=15_000, seed=7, replicas=2)
    assert passed and metrics["quality_gate_passed"]
    model_path, sha = registry.resolve_production(tmp_path)
    artifact = json.loads(model_path.read_text())
    assert set(artifact["treatments"]) == set(synthetic.TREATMENTS)
    for t in synthetic.TREATMENTS:
        assert metrics["treatments"][t]["error_dml"] <= train.ATE_ERROR_MAX
        assert all(r["passed"] for r in metrics["treatments"][t]["refutations"].values())

    # Con una tolerancia imposible el modelo NO se publica (la API sigue con la versión anterior).
    monkeypatch.setattr(train, "ATE_ERROR_MAX", 0.0)
    _, passed = train.run(tmp_path / "r2", n=6_000, seed=8, replicas=1)
    assert not passed
    assert list((tmp_path / "r2" / "vox-causal-scm" / "rejected").glob("*.json"))
    assert not (tmp_path / "r2" / "vox-causal-scm" / "production.json").exists()


_ORIGINAL_CALIBRATE = train.calibrate_stress


def _small_calibration():
    return _ORIGINAL_CALIBRATE(n_train=120, n_test=60, seed=5)


def test_job_entry_modes(tmp_path, monkeypatch):
    from pipeline import entry

    monkeypatch.delenv("SERVICEBUS_FQDN", raising=False)
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "none.jsonl"))
    monkeypatch.setenv("JOB_MODE", "worker")
    assert entry.main() == 0
    monkeypatch.setenv("JOB_MODE", "desconocido")
    assert entry.main() == 2
