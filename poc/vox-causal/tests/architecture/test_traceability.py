"""Los diagramas no pueden contradecir al código: cada afirmación se verifica en CI."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "architecture_claims", Path(__file__).resolve().parents[2] / "tools" / "architecture_claims.py")
claims = importlib.util.module_from_spec(_spec)
sys.modules["architecture_claims"] = claims
_spec.loader.exec_module(claims)


@pytest.mark.parametrize("c", claims.CLAIMS, ids=[c.id for c in claims.CLAIMS])
def test_claim_holds(c):
    assert c.check(), f"{c.id}: {c.statement} — revisar {c.evidence}"


def test_measured_figures_are_consistent():
    m = claims.measured()
    assert all(v <= 0.05 for v in m["ate_error_dml"].values())
    assert m["p95_180"] < 200 and m["overload"]["pct_under_200ms"] == 100.0
