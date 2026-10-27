"""Proceso generador de datos (SCM) con efectos causales conocidos.

Modela la relación entre las causas operativas de una llamada y la fuga del
cliente (churn a 90 días). Como las ecuaciones estructurales son conocidas, el
efecto causal verdadero (ATE) se calcula de forma exacta simulando las
intervenciones do(T=1) y do(T=0) sobre las mismas unidades y el mismo ruido.
Eso permite medir el error de ATE del estimador, que es el KPI del caso.

Grafo causal (DAG):

    tenure_years ──► long_wait ──► stress ──► churn
         │               └──────────────────────▲
         │          repeat_contact ─► long_wait  │
         │               ▲   └──► multi_transfer ┤
    issue_technical ─────┘            ▲          │
         └────────────────────────────┘          │
    tenure_years ──► billing_error ──► stress     │
    tenure_years ────────────────────────────────┘

Tratamientos (causas raíz accionables): long_wait, multi_transfer, billing_error.
Confusores: tenure_years (antigüedad), repeat_contact, issue_technical.
Mediador: stress (medido en vivo con la prosodia de la voz del cliente).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TREATMENTS = ("long_wait", "multi_transfer", "billing_error")
CONFOUNDERS = ("tenure_years", "repeat_contact", "issue_technical")
MEDIATOR = "stress"
OUTCOME = "churn"

DAG_EDGES = [
    ("tenure_years", "long_wait"),
    ("tenure_years", "billing_error"),
    ("tenure_years", "churn"),
    ("issue_technical", "repeat_contact"),
    ("issue_technical", "multi_transfer"),
    ("repeat_contact", "long_wait"),
    ("repeat_contact", "multi_transfer"),
    ("repeat_contact", "stress"),
    ("repeat_contact", "churn"),
    ("long_wait", "stress"),
    ("long_wait", "churn"),
    ("multi_transfer", "stress"),
    ("multi_transfer", "churn"),
    ("billing_error", "stress"),
    ("billing_error", "churn"),
    ("stress", "churn"),
]

# Coeficientes estructurales (escala de probabilidad).
_STRESS = {"base": 0.20, "long_wait": 0.25, "multi_transfer": 0.20, "billing_error": 0.15, "repeat_contact": 0.10}
_CHURN = {
    "base": 0.22,
    "long_wait": 0.06,
    "multi_transfer": 0.08,
    "billing_error": 0.10,
    "repeat_contact": 0.05,
    "tenure_years": -0.02,
    "stress": 0.25,
}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class SyntheticDataset:
    data: pd.DataFrame
    true_ate: dict[str, float]


def _stress(df: pd.DataFrame, noise: np.ndarray) -> np.ndarray:
    s = _STRESS["base"] + noise
    for k in ("long_wait", "multi_transfer", "billing_error", "repeat_contact"):
        s = s + _STRESS[k] * df[k].to_numpy()
    return np.clip(s, 0.0, 1.0)


def _churn_prob(df: pd.DataFrame, stress: np.ndarray) -> np.ndarray:
    p = np.full(len(df), _CHURN["base"]) + _CHURN["stress"] * stress
    for k in ("long_wait", "multi_transfer", "billing_error", "repeat_contact", "tenure_years"):
        p = p + _CHURN[k] * df[k].to_numpy()
    return np.clip(p, 0.0, 1.0)


def generate(n: int = 50_000, seed: int = 7) -> SyntheticDataset:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"tenure_years": rng.uniform(0, 10, n)})
    df["issue_technical"] = rng.binomial(1, 0.4, n)
    df["repeat_contact"] = rng.binomial(1, _sigmoid(-1.0 + 0.8 * df["issue_technical"]))
    df["long_wait"] = rng.binomial(1, _sigmoid(1.0 - 0.4 * df["tenure_years"] + 0.6 * df["repeat_contact"]))
    df["multi_transfer"] = rng.binomial(
        1, _sigmoid(-1.2 + 1.5 * df["issue_technical"] + 0.4 * df["repeat_contact"])
    )
    df["billing_error"] = rng.binomial(1, _sigmoid(-1.6 + 0.12 * df["tenure_years"]))

    stress_noise = rng.normal(0.0, 0.08, n)
    churn_u = rng.uniform(0.0, 1.0, n)
    df["stress"] = _stress(df, stress_noise)
    df["churn"] = (churn_u < _churn_prob(df, df["stress"].to_numpy())).astype(int)

    true_ate: dict[str, float] = {}
    for t in TREATMENTS:
        p = {}
        for value in (0, 1):
            cf = df.copy()
            cf[t] = value
            s_cf = _stress(cf, stress_noise)
            p[value] = _churn_prob(cf, s_cf)
        true_ate[t] = float(np.mean(p[1] - p[0]))
    return SyntheticDataset(data=df, true_ate=true_ate)
