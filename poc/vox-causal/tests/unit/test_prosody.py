import numpy as np
from pipeline.synth_audio import interleave_stereo, synth_speech, to_pcm16
from voxfeatures import FEATURE_NAMES, extract, pcm16_to_float


def _mean_features(stress, rng, n=12):
    return np.mean([extract(synth_speech(stress, 1.0, rng)).as_vector() for _ in range(n)], axis=0)


def test_pitch_and_energy_increase_with_stress(rng):
    low, high = _mean_features(0.1, rng), _mean_features(0.9, rng)
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    assert high[idx["f0_mean_hz"]] > low[idx["f0_mean_hz"]] + 50
    assert high[idx["energy_db"]] > low[idx["energy_db"]] + 5
    assert high[idx["jitter"]] > low[idx["jitter"]]


def test_f0_estimate_is_close_to_pure_tone():
    t = np.arange(16000) / 16000
    f = extract(0.3 * np.sin(2 * np.pi * 150 * t))
    assert abs(f.f0_mean_hz - 150) < 3
    assert f.voiced_ratio > 0.9


def test_silence_has_no_voicing():
    f = extract(np.zeros(16000, dtype=np.float32))
    assert f.voiced_ratio == 0.0 and f.f0_mean_hz == 0.0


def test_too_short_signal_returns_defaults():
    f = extract(np.zeros(100, dtype=np.float32))
    assert f.energy_db == -90.0 and f.voiced_ratio == 0.0


def test_pcm_decoding_keeps_only_customer_channel(rng):
    customer = synth_speech(0.2, 0.5, rng)
    operator = synth_speech(0.9, 0.5, rng)
    mono = pcm16_to_float(interleave_stereo(customer, operator), channels=2, keep_channel=0)
    expected = pcm16_to_float(to_pcm16(customer))
    assert np.allclose(mono, expected[: len(mono)], atol=1e-4)


def test_feature_dict_is_serializable(rng):
    d = extract(synth_speech(0.5, 1.0, rng)).as_dict()
    assert set(d) == set(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in d.values())
