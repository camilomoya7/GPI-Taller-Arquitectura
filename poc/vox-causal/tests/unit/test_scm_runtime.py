from app.model_store import FALLBACK_MODEL
from app.scm_runtime import CausalRuntime, sanitize_context
from pipeline.synth_audio import synth_speech
from voxfeatures import extract


def test_sanitize_context_binarizes_and_clips():
    ctx = sanitize_context({"long_wait": "1", "multi_transfer": 0.2, "tenure_years": 99, "billing_error": "x"},
                           {"tenure_years": 5})
    assert ctx["long_wait"] == 1.0 and ctx["multi_transfer"] == 0.0
    assert ctx["tenure_years"] == 40.0 and ctx["billing_error"] == 0.0
    assert sanitize_context(None, {"tenure_years": 5})["tenure_years"] == 5.0


def test_root_cause_is_largest_causal_effect(artifact):
    rt = CausalRuntime(artifact)
    ctx = sanitize_context({"long_wait": 1, "multi_transfer": 1, "billing_error": 1}, rt.defaults)
    res = rt.infer(ctx, 0.5)
    effects = [c["effect"] for c in res.causes]
    assert effects == sorted(effects, reverse=True)
    assert res.root_cause["cause"] == max(artifact["treatments"], key=lambda t: artifact["treatments"][t]["ate"])


def test_no_active_cause_gives_no_root_cause(artifact):
    rt = CausalRuntime(artifact)
    res = rt.infer(sanitize_context({}, rt.defaults), 0.2)
    assert res.root_cause is None and res.causes == []


def test_risk_increases_with_causes_and_stress(artifact):
    rt = CausalRuntime(artifact)
    calm = rt.infer(sanitize_context({"tenure_years": 8}, rt.defaults), 0.1)
    bad = rt.infer(sanitize_context({"long_wait": 1, "multi_transfer": 1, "tenure_years": 1}, rt.defaults), 0.9)
    assert bad.churn_risk > calm.churn_risk + 0.2
    assert bad.risk_level in {"medium", "high"}


def test_missing_prosody_falls_back_to_context(artifact):
    rt = CausalRuntime(artifact)
    res = rt.infer(sanitize_context({"long_wait": 1}, rt.defaults), None)
    assert res.stress_source == "context-fallback"
    assert res.stress == res.expected_stress
    assert res.unexplained_stress is False


def test_unexplained_stress_is_flagged(artifact):
    rt = CausalRuntime(artifact)
    res = rt.infer(sanitize_context({}, rt.defaults), 0.95)
    assert res.unexplained_stress is True


def test_stress_estimate_tracks_true_stress(artifact, rng):
    rt = CausalRuntime(artifact)
    low = rt.stress_from_prosody(extract(synth_speech(0.1, 1.0, rng)))
    high = rt.stress_from_prosody(extract(synth_speech(0.9, 1.0, rng)))
    assert high - low > 0.5


def test_silence_returns_none(artifact):
    import numpy as np
    assert CausalRuntime(artifact).stress_from_prosody(extract(np.zeros(16000))) is None


def test_fallback_rules_model_works(rng):
    rt = CausalRuntime(FALLBACK_MODEL)
    s = rt.stress_from_prosody(extract(synth_speech(0.8, 1.0, rng)))
    assert 0.0 <= s <= 1.0
    res = rt.infer(sanitize_context({"billing_error": 1}, rt.defaults), s)
    assert res.root_cause["cause"] == "billing_error"
