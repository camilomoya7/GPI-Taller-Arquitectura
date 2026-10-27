"""Pipeline batch (camino frío): entrenamiento causal, validación y publicación.

Etapas:
  1. Datos: genera el dataset de prueba con efectos causales conocidos.
  2. Identificación: DoWhy identifica el estimando por criterio backdoor sobre el DAG.
  3. Estimación: regresión lineal ajustada y Double Machine Learning (EconML LinearDML).
  4. Refutación: tratamiento placebo, causa común aleatoria y subconjunto de datos.
  5. Calibración prosódica: rasgos de voz → estrés, sobre audio sintético etiquetado.
  6. Control de calidad: |ATE estimado − ATE verdadero| ≤ 0.05 y refutaciones aprobadas.
  7. Publicación: artefacto JSON versionado + SHA-256 en el registro de modelos.

Si el control de calidad falla, el modelo NO se publica (código de salida 2) y
la API de inferencia sigue usando la versión anterior.

Uso:  python -m pipeline.train --registry ../../registry
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import numpy as np
import voxfeatures
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from voxfeatures import FEATURE_NAMES, extract

from . import registry, synth_audio, synthetic

ATE_ERROR_MAX = 0.05
REFUTATION_TOLERANCE = 0.01
REFUTE_SIMULATIONS = 20

LABELS = {
    "long_wait": "Espera prolongada (> 5 min en cola)",
    "multi_transfer": "Múltiples transferencias entre áreas",
    "billing_error": "Error de facturación reportado",
}
PLAYBOOKS = {
    "long_wait": "Reconocer la espera y ofrecer compensación o devolución de llamada prioritaria.",
    "multi_transfer": "Evitar nueva transferencia: tomar propiedad del caso y escalar internamente.",
    "billing_error": "Validar el cobro en línea y emitir nota de crédito si corresponde.",
}

log = logging.getLogger("vox.batch.train")


def _graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_edges_from(synthetic.DAG_EDGES)
    return g


def _estimate_treatment(df, treatment: str, refute: bool) -> dict:
    from dowhy import CausalModel

    model = CausalModel(data=df, treatment=treatment, outcome=synthetic.OUTCOME, graph=_graph())
    estimand = model.identify_effect(proceed_when_unidentifiable=True)
    backdoor = sorted(estimand.get_backdoor_variables())

    linear = model.estimate_effect(
        estimand, method_name="backdoor.linear_regression", confidence_intervals=True
    )
    dml = model.estimate_effect(
        estimand,
        method_name="backdoor.econml.dml.LinearDML",
        method_params={
            "init_params": {
                "model_y": LinearRegression(),
                "model_t": LogisticRegression(max_iter=1000),
                "discrete_treatment": True,
                "cv": 3,
                "random_state": 0,
            },
            "fit_params": {},
        },
    )
    naive = float(df.loc[df[treatment] == 1, "churn"].mean() - df.loc[df[treatment] == 0, "churn"].mean())
    try:
        ci = [float(v) for v in np.ravel(linear.get_confidence_intervals())]
    except Exception:  # pragma: no cover - depende de la versión de DoWhy
        ci = []

    result = {
        "backdoor_set": backdoor,
        "naive_correlational": naive,
        "linear_regression": float(linear.value),
        "linear_dml": float(dml.value),
        "ci95_linear": ci,
    }
    if refute:
        result["refutations"] = _refute(model, estimand, linear)
    return result


def _refute(model, estimand, estimate) -> dict:
    out = {}
    placebo = model.refute_estimate(
        estimand, estimate, method_name="placebo_treatment_refuter",
        placebo_type="permute", num_simulations=REFUTE_SIMULATIONS, random_seed=1,
    )
    out["placebo_treatment"] = {
        "new_effect": float(placebo.new_effect),
        "passed": abs(float(placebo.new_effect)) < REFUTATION_TOLERANCE,
        "criterio": "el efecto con tratamiento permutado debe ser ≈ 0",
    }
    rcc = model.refute_estimate(
        estimand, estimate, method_name="random_common_cause", num_simulations=REFUTE_SIMULATIONS, random_seed=1
    )
    out["random_common_cause"] = {
        "new_effect": float(rcc.new_effect),
        "passed": abs(float(rcc.new_effect) - float(estimate.value)) < REFUTATION_TOLERANCE,
        "criterio": "agregar un confusor aleatorio no debe mover la estimación",
    }
    subset = model.refute_estimate(
        estimand, estimate, method_name="data_subset_refuter",
        subset_fraction=0.8, num_simulations=REFUTE_SIMULATIONS, random_seed=1,
    )
    out["data_subset"] = {
        "new_effect": float(subset.new_effect),
        "passed": abs(float(subset.new_effect) - float(estimate.value)) < REFUTATION_TOLERANCE,
        "criterio": "la estimación debe ser estable en subconjuntos del 80%",
    }
    return out


def calibrate_stress(n_train: int = 800, n_test: int = 400, seed: int = 11) -> dict:
    """Ajusta rasgos prosódicos → estrés con audio sintético de estrés conocido."""
    rng = np.random.default_rng(seed)

    def corpus(n):
        y = rng.uniform(0, 1, n)
        X = np.vstack([extract(synth_audio.synth_speech(s, 1.0, rng)).as_vector() for s in y])
        return X, y

    X_tr, y_tr = corpus(n_train)
    X_te, y_te = corpus(n_test)
    mean, scale = X_tr.mean(axis=0), X_tr.std(axis=0) + 1e-9
    reg = Ridge(alpha=1.0).fit((X_tr - mean) / scale, y_tr)
    pred = np.clip(reg.predict((X_te - mean) / scale), 0, 1)
    return {
        "feature_names": list(FEATURE_NAMES),
        "mean": mean.round(6).tolist(),
        "scale": scale.round(6).tolist(),
        "coef": reg.coef_.round(6).tolist(),
        "intercept": round(float(reg.intercept_), 6),
        "metrics": {
            "mae": round(float(mean_absolute_error(y_te, pred)), 4),
            "r2": round(float(r2_score(y_te, pred)), 4),
            "n_train": n_train,
            "n_test": n_test,
        },
    }


def fit_risk_model(df) -> dict:
    cols = [*synthetic.TREATMENTS, "repeat_contact", "tenure_years", "issue_technical", "stress"]
    reg = LinearRegression().fit(df[cols], df[synthetic.OUTCOME])
    return {
        "type": "linear_probability",
        "features": cols,
        "intercept": round(float(reg.intercept_), 6),
        "coef": {c: round(float(v), 6) for c, v in zip(cols, reg.coef_, strict=True)},
    }


def fit_stress_expectation(df) -> dict:
    """Estrés esperado según las causas conocidas (para detectar estrés no explicado)."""
    cols = [*synthetic.TREATMENTS, "repeat_contact"]
    reg = LinearRegression().fit(df[cols], df[synthetic.MEDIATOR])
    resid = df[synthetic.MEDIATOR] - reg.predict(df[cols])
    return {
        "features": cols,
        "intercept": round(float(reg.intercept_), 6),
        "coef": {c: round(float(v), 6) for c, v in zip(cols, reg.coef_, strict=True)},
        "residual_std": round(float(resid.std()), 6),
    }


def run(registry_dir: Path, n: int = 50_000, seed: int = 7, replicas: int = 5) -> tuple[dict, bool]:
    t0 = time.perf_counter()
    ds = synthetic.generate(n=n, seed=seed)
    df = ds.data
    log.info("dataset generado n=%d seed=%d", n, seed)

    treatments: dict[str, dict] = {}
    passed = True
    for t in synthetic.TREATMENTS:
        est = _estimate_treatment(df, t, refute=True)
        true = ds.true_ate[t]
        est["true_ate"] = true
        est["error_linear"] = abs(est["linear_regression"] - true)
        est["error_dml"] = abs(est["linear_dml"] - true)
        est["error_naive"] = abs(est["naive_correlational"] - true)
        refutations_ok = all(r["passed"] for r in est["refutations"].values())
        est["gate_passed"] = est["error_dml"] <= ATE_ERROR_MAX and refutations_ok
        passed &= est["gate_passed"]
        treatments[t] = est
        log.info("%s ATE verdadero=%.4f DML=%.4f error=%.4f", t, true, est["linear_dml"], est["error_dml"])

    # Robustez: repetir la estimación con otras semillas (sin refutaciones).
    replica_errors = {t: [] for t in synthetic.TREATMENTS}
    for r in range(1, replicas):
        rep = synthetic.generate(n=n, seed=seed + r)
        for t in synthetic.TREATMENTS:
            e = _estimate_treatment(rep.data, t, refute=False)
            replica_errors[t].append(abs(e["linear_dml"] - rep.true_ate[t]))
    for t in synthetic.TREATMENTS:
        errs = [treatments[t]["error_dml"], *replica_errors[t]]
        treatments[t]["error_dml_replicas"] = {
            "n": len(errs), "mean": float(np.mean(errs)), "max": float(np.max(errs)),
        }
        passed &= float(np.max(errs)) <= ATE_ERROR_MAX

    stress_model = calibrate_stress()
    risk_model = fit_risk_model(df)

    created = datetime.now(UTC).replace(microsecond=0)
    version = created.strftime("%Y.%m.%d-%H%M%S")
    artifact = {
        "model_name": "vox-causal-scm",
        "version": version,
        "created_at": created.isoformat(),
        "feature_lib_version": voxfeatures.__version__,
        "dag": {"edges": synthetic.DAG_EDGES, "mediator": synthetic.MEDIATOR, "outcome": synthetic.OUTCOME},
        "treatments": {
            t: {
                "label": LABELS[t],
                "playbook": PLAYBOOKS[t],
                "ate": round(treatments[t]["linear_dml"], 6),
                "estimator": "backdoor.econml.dml.LinearDML",
            }
            for t in synthetic.TREATMENTS
        },
        "risk_model": risk_model,
        "stress_expectation": fit_stress_expectation(df),
        "stress_model": {k: v for k, v in stress_model.items() if k != "metrics"},
        "context_defaults": {
            "tenure_years": round(float(df["tenure_years"].median()), 3),
            "repeat_contact": 0,
            "issue_technical": 0,
        },
    }
    metrics = {
        "model_name": artifact["model_name"],
        "version": version,
        "dataset": {"n": n, "seed": seed, "replicas": replicas},
        "ate_error_max": ATE_ERROR_MAX,
        "treatments": treatments,
        "stress_calibration": stress_model["metrics"],
        "quality_gate_passed": bool(passed),
        "duration_s": round(time.perf_counter() - t0, 1),
    }
    if passed:
        registry.publish(registry_dir, artifact, metrics)
    else:
        registry.write_rejected(registry_dir, metrics)
    return metrics, passed


def main() -> int:
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("dowhy").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description="Entrena, valida y publica el modelo causal")
    p.add_argument("--registry", type=Path, default=Path("registry"))
    p.add_argument("--n", type=int, default=50_000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--replicas", type=int, default=5)
    args = p.parse_args()
    metrics, passed = run(args.registry, n=args.n, seed=args.seed, replicas=args.replicas)
    print(json.dumps({"version": metrics["version"], "quality_gate_passed": passed}, ensure_ascii=False))
    if os.getenv("REGISTRY_BLOB_ACCOUNT_URL"):
        registry.upload_to_blob(args.registry, os.environ["REGISTRY_BLOB_ACCOUNT_URL"])
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
