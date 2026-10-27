"""Registro de modelos: el ÚNICO contrato entre el camino frío y el caliente.

Estructura (equivalente local de Azure ML Model Registry):

    registry/vox-causal-scm/
        <version>/model.json        artefacto que consume la API
        <version>/model.json.sha256 huella para verificar integridad
        <version>/metrics.json      evidencia de calidad (ATE, refutaciones)
        production.json             puntero a la versión aprobada
        rejected/<version>.json     intentos que no pasaron el control de calidad

La API nunca lee datos ni colas del batch: solo recibe un model.json aprobado,
que se copia dentro de su imagen al desplegar (despliegue inmutable).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODEL_NAME = "vox-causal-scm"


def _dump(path: Path, obj: dict) -> bytes:
    data = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def publish(registry_dir: Path, artifact: dict, metrics: dict) -> Path:
    base = Path(registry_dir) / MODEL_NAME
    vdir = base / artifact["version"]
    data = _dump(vdir / "model.json", artifact)
    digest = hashlib.sha256(data).hexdigest()
    (vdir / "model.json.sha256").write_text(f"{digest}  model.json\n")
    _dump(vdir / "metrics.json", metrics)
    _dump(
        base / "production.json",
        {"model_name": MODEL_NAME, "version": artifact["version"], "sha256": digest,
         "path": f"{artifact['version']}/model.json"},
    )
    return vdir / "model.json"


def write_rejected(registry_dir: Path, metrics: dict) -> Path:
    path = Path(registry_dir) / MODEL_NAME / "rejected" / f"{metrics['version']}.json"
    _dump(path, metrics)
    return path


def resolve_production(registry_dir: Path) -> tuple[Path, str]:
    base = Path(registry_dir) / MODEL_NAME
    pointer = json.loads((base / "production.json").read_text())
    return base / pointer["path"], pointer["sha256"]


def upload_to_blob(registry_dir: Path, account_url: str, container: str = "model-registry") -> int:  # pragma: no cover
    """Sube el registro a Blob Storage (equivalente a publicar en Azure ML Model Registry)."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(account_url, credential=DefaultAzureCredential())
    client = svc.get_container_client(container)
    count = 0
    for path in Path(registry_dir).rglob("*"):
        if path.is_file():
            client.upload_blob(str(path.relative_to(registry_dir)), path.read_bytes(), overwrite=True)
            count += 1
    return count
