"""Promueve la versión aprobada del registro a la imagen de la API (despliegue inmutable).

Verifica la huella SHA-256 antes de copiar. La promoción queda registrada como un
commit en Git, lo que da trazabilidad de qué modelo corre en producción y quién lo aprobó.

Uso:  python tools/promote_model.py --registry registry
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "services" / "inference_api" / "model", ROOT / "tests" / "fixtures"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", type=Path, default=ROOT / "registry")
    a = p.parse_args()
    base = a.registry / "vox-causal-scm"
    pointer = json.loads((base / "production.json").read_text())
    model = base / pointer["path"]
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if digest != pointer["sha256"]:
        print(f"ERROR: huella no coincide ({digest} != {pointer['sha256']})", file=sys.stderr)
        return 1
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(model, target / "model.json")
        shutil.copy(model.with_name("model.json.sha256"), target / "model.json.sha256")
        shutil.copy(model.with_name("metrics.json"), target / "metrics.json")
    print(f"Promovido {pointer['model_name']} {pointer['version']} (sha256 {digest[:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
