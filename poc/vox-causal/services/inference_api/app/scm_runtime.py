"""Evaluación en tiempo real del modelo causal YA AJUSTADO (sin DoWhy/EconML).

En el camino caliente no se descubre el DAG ni se reestiman efectos: eso es
costoso y ocurre en el pipeline batch. Aquí solo se evalúan fórmulas cerradas
con NumPy, lo que cuesta microsegundos y permite cumplir el presupuesto < 200 ms.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from voxfeatures import ProsodyFeatures

TREATMENTS = ("long_wait", "multi_transfer", "billing_error")
CONTEXT_KEYS = (*TREATMENTS, "repeat_contact", "tenure_years", "issue_technical")
UNEXPLAINED_Z = 2.0
MIN_VOICED_RATIO = 0.10


def sanitize_context(raw: dict | None, defaults: dict) -> dict[str, float]:
    ctx: dict[str, float] = {}
    raw = raw or {}
    for key in CONTEXT_KEYS:
        value = raw.get(key, defaults.get(key, 0))
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(defaults.get(key, 0))
        if key == "tenure_years":
            ctx[key] = float(np.clip(value, 0.0, 40.0))
        else:
            ctx[key] = 1.0 if value >= 0.5 else 0.0
    return ctx


@dataclass
class Inference:
    stress: float
    stress_source: str
    expected_stress: float
    unexplained_stress: bool
    churn_risk: float
    risk_level: str
    root_cause: dict | None
    causes: list[dict]


class CausalRuntime:
    def __init__(self, artifact: dict) -> None:
        self.artifact = artifact
        sm = artifact.get("stress_model")
        if sm:
            self._mean = np.asarray(sm["mean"], dtype=np.float64)
            self._scale = np.asarray(sm["scale"], dtype=np.float64)
            self._coef = np.asarray(sm["coef"], dtype=np.float64)
            self._intercept = float(sm["intercept"])
        else:
            self._coef = None
        self.defaults = artifact.get("context_defaults", {})

    def expected_stress(self, ctx: dict[str, float]) -> float:
        se = self.artifact["stress_expectation"]
        value = se["intercept"] + sum(se["coef"][k] * ctx.get(k, 0.0) for k in se["features"])
        return float(np.clip(value, 0.0, 1.0))

    def stress_from_prosody(self, feats: ProsodyFeatures) -> float | None:
        if feats.voiced_ratio < MIN_VOICED_RATIO:
            return None  # silencio o audio de mala calidad: respaldo al contexto
        if self._coef is None:
            # Regla de respaldo: energía y tono normalizados.
            e = np.clip((feats.energy_db + 35.0) / 20.0, 0, 1)
            f = np.clip((feats.f0_mean_hz - 100.0) / 140.0, 0, 1)
            return float(0.5 * e + 0.5 * f)
        z = (feats.as_vector() - self._mean) / self._scale
        return float(np.clip(z @ self._coef + self._intercept, 0.0, 1.0))

    def infer(self, ctx: dict[str, float], stress: float | None) -> Inference:
        expected = self.expected_stress(ctx)
        source = "prosody"
        if stress is None:
            stress, source = expected, "context-fallback"

        rm = self.artifact["risk_model"]
        values = {**ctx, "stress": stress}
        risk = rm["intercept"] + sum(rm["coef"][k] * values.get(k, 0.0) for k in rm["features"])
        risk = float(np.clip(risk, 0.0, 1.0))

        sd = self.artifact["stress_expectation"].get("residual_std", 0.1) or 0.1
        unexplained = source == "prosody" and (stress - expected) > UNEXPLAINED_Z * max(sd, 0.05)

        causes = []
        for t in TREATMENTS:
            if ctx.get(t, 0.0) >= 0.5:
                info = self.artifact["treatments"][t]
                causes.append({"cause": t, "label": info["label"], "effect": round(float(info["ate"]), 4),
                               "playbook": info["playbook"]})
        causes.sort(key=lambda c: c["effect"], reverse=True)
        level = "high" if risk >= 0.5 else "medium" if risk >= 0.3 else "low"
        return Inference(
            stress=round(stress, 4), stress_source=source, expected_stress=round(expected, 4),
            unexplained_stress=bool(unexplained), churn_risk=round(risk, 4), risk_level=level,
            root_cause=causes[0] if causes else None, causes=causes,
        )
