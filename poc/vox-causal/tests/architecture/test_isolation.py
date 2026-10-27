"""Pruebas de arquitectura: verifican el AISLAMIENTO ESTRICTO (restricción 2).

Si alguien agrega por error una dependencia del batch a la API (o viceversa),
estas pruebas fallan en CI y el cambio no se puede integrar.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services" / "inference_api"
BATCH = ROOT / "services" / "batch_pipeline"

HEAVY_OR_BATCH = {"dowhy", "econml", "sklearn", "pandas", "networkx", "openai", "pipeline", "torch"}


def _imports(folder: Path) -> set[str]:
    found = set()
    for py in folder.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_api_does_not_import_batch_or_training_libraries():
    leaked = _imports(API / "app") & HEAVY_OR_BATCH
    assert not leaked, f"La API importa dependencias del camino frío: {leaked}"


def test_batch_does_not_import_api():
    assert "app" not in _imports(BATCH / "pipeline")


def test_api_requirements_exclude_training_stack():
    lines = (API / "requirements.txt").read_text().lower().splitlines()
    reqs = "\n".join(line.split("#")[0] for line in lines)
    for pkg in ("dowhy", "econml", "scikit-learn", "pandas", "openai"):
        assert pkg not in reqs, f"{pkg} no debe instalarse en la imagen de la API"


def test_api_image_does_not_copy_batch_code():
    dockerfile = (API / "Dockerfile").read_text()
    assert "batch_pipeline" not in dockerfile


def test_only_contract_between_paths_is_model_artifact():
    dockerfile = (API / "Dockerfile").read_text()
    assert "model.json" in dockerfile  # el modelo aprobado entra a la imagen (despliegue inmutable)
