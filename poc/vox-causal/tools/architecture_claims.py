"""Trazabilidad diagrama ↔ código.

Cada afirmación que aparece en los diagramas C4 (niveles 1, 2 y 3) y en el diagrama del
pipeline se declara aquí como una comprobación ejecutable contra el código fuente, los
Dockerfile o el script de despliegue. Si alguien cambia el código y el diagrama queda
desactualizado, la prueba `tests/architecture/test_traceability.py` falla en CI.

Uso:  python tools/architecture_claims.py            → imprime el resultado y escribe docs/TRAZABILIDAD.md
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs/voxfeatures", "services/inference_api", "services/batch_pipeline"):
    sys.path.insert(0, str(ROOT / p))

API = ROOT / "services" / "inference_api"
BATCH = ROOT / "services" / "batch_pipeline"
DEPLOY = (ROOT / "deploy" / "azure" / "deploy.sh").read_text()
VERIFY = (ROOT / "deploy" / "azure" / "verify.sh").read_text()


def src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def has(text: str, *needles: str) -> bool:
    return all(n in text for n in needles)


def imports(folder: Path) -> set[str]:
    found: set[str] = set()
    for py in folder.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


@dataclass
class Claim:
    id: str
    diagram: str
    element: str
    statement: str
    evidence: str
    check: Callable[[], bool]
    status: str = "Implementado"  # o "Diseño productivo"


CLAIMS: list[Claim] = []


def claim(id_, diagram, element, statement, evidence, status="Implementado"):
    def deco(fn):
        CLAIMS.append(Claim(id_, diagram, element, statement, evidence, fn, status))
        return fn
    return deco


def _settings():
    keep = {k: os.environ.pop(k) for k in list(os.environ) if k in {
        "MAX_SESSIONS", "WINDOW_MS", "HOP_MS", "SAS_TTL_MINUTES", "LATENCY_BUDGET_MS", "DATA_REGION"}}
    try:
        from app.config import Settings
        return Settings()
    finally:
        os.environ.update(keep)


# ───────────────────────────── C4 Nivel 1 — Contexto ─────────────────────────────
@claim("N1-01", "C4 N1", "Cliente que llama", "Solo se analiza el canal del cliente", "app/privacy.py")
def _():
    from app.privacy import ALLOWED_CHANNEL
    return ALLOWED_CHANNEL == "customer"


@claim("N1-02", "C4 N1", "Operador", "La voz del operador se rechaza (EU AI Act art. 5.1.f)", "app/privacy.py")
def _():
    from app.privacy import ChannelPolicyError, check_channel
    try:
        check_channel("operator")
    except ChannelPolicyError as e:
        return "AI Act" in str(e)
    return False


@claim("N1-03", "C4 N1", "Supervisor", "Recibe explicación post-llamada y accede a grabaciones con SAS",
       "pipeline/explain.py · app/sas.py")
def _():
    return has(src("services/batch_pipeline/pipeline/explain.py"), "def explain") and \
        has(src("services/inference_api/app/main.py"), "/v1/recordings/{call_ref}/access")


@claim("N1-04", "C4 N1", "Equipo MLOps", "Entrena, aprueba (control de calidad) y promueve modelos",
       "pipeline/train.py · tools/promote_model.py")
def _():
    return has(src("services/batch_pipeline/pipeline/train.py"), "quality_gate_passed") and \
        (ROOT / "tools" / "promote_model.py").exists()


@claim("N1-05", "C4 N1", "Plataforma de telefonía", "Envía audio PCM16 y contexto por WebSocket seguro (WSS)",
       "app/ws_handler.py · deploy.sh (ingress HTTPS)")
def _():
    from app.stream import AudioFormat
    return AudioFormat.parse({"encoding": "pcm_s16le"}).sample_rate == 16000 and \
        has(src("services/inference_api/app/main.py"), '@app.websocket("/v1/stream")') and \
        has(DEPLOY, "--ingress external")


@claim("N1-06", "C4 N1", "Azure OpenAI", "Solo redacta la explicación; si falla se usa plantilla (no decide la causa)",
       "pipeline/explain.py")
def _():
    s = src("services/batch_pipeline/pipeline/explain.py")
    return has(s, "template_explanation", '"template"', "AzureOpenAI") and "openai" not in imports(API / "app")


@claim("N1-07", "C4 N1", "Microsoft Entra ID", "Autenticación sin claves: identidades administradas",
       "DefaultAzureCredential en sas.py, events.py, worker.py")
def _():
    return all("DefaultAzureCredential" in src(f) for f in (
        "services/inference_api/app/sas.py", "services/inference_api/app/events.py",
        "services/batch_pipeline/pipeline/worker.py"))


@claim("N1-08", "C4 N1", "Log Analytics", "Logs JSON a stdout recolectados por Log Analytics", "app/telemetry.py · deploy.sh")
def _():
    return has(src("services/inference_api/app/telemetry.py"), "json.dumps", "sys.stdout") and \
        has(DEPLOY, "log-analytics workspace create")


# ───────────────────────────── C4 Nivel 2 — Contenedores ─────────────────────────────
@claim("N2-01", "C4 N2", "API de inferencia", "FastAPI sobre Python 3.12 en contenedor propio", "inference_api/Dockerfile")
def _():
    return has(src("services/inference_api/Dockerfile"), "FROM python:3.12-slim") and \
        "fastapi" in src("services/inference_api/requirements.txt")


@claim("N2-02", "C4 N2", "API de inferencia", "1 vCPU por réplica, 1 a 10 réplicas, escala con 150 conexiones",
       "deploy.sh paso 11")
def _():
    return has(DEPLOY, "--cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 10",
               "--scale-rule-http-concurrency 150")


@claim("N2-03", "C4 N2", "API de inferencia", "Imagen sin DoWhy/EconML/pandas/scikit-learn", "inference_api/requirements.txt")
def _():
    reqs = "\n".join(line.split("#")[0] for line in src("services/inference_api/requirements.txt").lower().splitlines())
    return not any(p in reqs for p in ("dowhy", "econml", "pandas", "scikit-learn"))


@claim("N2-04", "C4 N2", "Cola call-closed", "Service Bus solo con Entra ID; API = Sender, batch = Receiver",
       "deploy.sh paso 8")
def _():
    return has(DEPLOY, "--disable-local-auth true", 'QUEUE="call-closed"',
               '"$ID_API_PRINCIPAL" ServicePrincipal "Azure Service Bus Data Sender"',
               '"$ID_BATCH_PRINCIPAL" ServicePrincipal "Azure Service Bus Data Receiver"')


@claim("N2-05", "C4 N2", "Worker post-llamada", "Container Apps Job en la zona batch", "deploy.sh paso 12 · pipeline/worker.py")
def _():
    return has(DEPLOY, 'job "$JOB_WORKER" "$ENV_BATCH"', "JOB_MODE=worker")


@claim("N2-06", "C4 N2", "Entrenamiento causal", "Container Apps Job con DoWhy + EconML en la zona batch",
       "deploy.sh · batch_pipeline/requirements.txt")
def _():
    r = src("services/batch_pipeline/requirements.txt")
    return has(DEPLOY, 'job "$JOB_TRAIN" "$ENV_BATCH"', "JOB_MODE=train") and has(r, "dowhy", "econml")


@claim("N2-07", "C4 N2", "Registro de modelos", "Versionado + SHA-256 + puntero production; copia en Blob model-registry",
       "pipeline/registry.py")
def _():
    s = src("services/batch_pipeline/pipeline/registry.py")
    return has(s, "model.json.sha256", "production.json", 'container: str = "model-registry"')


@claim("N2-08", "C4 N2", "Blob Storage", "TLS ≥ 1.2, solo HTTPS, sin claves compartidas, sin acceso público",
       "deploy.sh paso 7")
def _():
    return has(DEPLOY, "--min-tls-version TLS1_2", "--https-only true", "--allow-shared-key-access false",
               "--allow-blob-public-access false")


@claim("N2-09", "C4 N2", "Blob Storage", "Retención de grabaciones: borrado a los 30 días (UK GDPR)", "deploy.sh paso 7")
def _():
    return has(DEPLOY, '"daysAfterModificationGreaterThan":30', '"prefixMatch":["recordings/"]')


@claim("N2-10", "C4 N2", "Región", "Todos los recursos en UK South (residencia de datos)", "deploy.sh · config.py")
def _():
    return has(DEPLOY, 'LOCATION="${LOCATION:-uksouth}"') and _settings().data_region == "uksouth"


@claim("N2-11", "C4 N2", "Zonas A y B", "VNets separadas (10.10/16 y 10.20/16) sin peering", "deploy.sh paso 3")
def _():
    return has(DEPLOY, "rt:10.10", "batch:10.20") and "peering create" not in DEPLOY


@claim("N2-12", "C4 N2", "Zona B", "Entorno batch sin ingreso público (internal-only)", "deploy.sh paso 10")
def _():
    return bool(re.search(r'-n "\$ENV_BATCH".*?--internal-only true', DEPLOY, re.S))


@claim("N2-13", "C4 N2", "Contrato entre zonas", "Único contrato: model.json + SHA-256 dentro de la imagen de la API",
       "inference_api/Dockerfile")
def _():
    d = src("services/inference_api/Dockerfile")
    return has(d, "model.json", "model.json.sha256") and "batch_pipeline" not in d


@claim("N2-14", "C4 N2", "Transversal", "Key Vault con RBAC, ACR sin usuario admin, 3 identidades administradas",
       "deploy.sh pasos 4, 6 y 9")
def _():
    return has(DEPLOY, "--enable-rbac-authorization true", "--admin-enabled false", "for who in api batch test")


@claim("N2-15", "C4 N2", "Gateway", "Azure API Management (WebSocket requiere nivel Developer o superior)",
       "README · diseño productivo", status="Diseño productivo")
def _():
    return "apim create" not in DEPLOY and "API Management" in src("README.md")


@claim("N2-16", "C4 N2", "Red privada", "Private Endpoints para Storage, Service Bus y Key Vault",
       "README · diseño productivo", status="Diseño productivo")
def _():
    return "private-endpoint create" not in DEPLOY and "Private Endpoints" in src("README.md")


# ───────────────────────────── C4 Nivel 3 — API de inferencia ─────────────────────────────
@claim("N3A-01", "C4 N3 API", "Borde WebSocket/REST", "Token Bearer comparado en tiempo constante", "app/main.py")
def _():
    return has(src("services/inference_api/app/main.py"), "hmac.compare_digest")


@claim("N3A-02", "C4 N3 API", "Borde WebSocket/REST", "Admisión: 180 sesiones por réplica; cierre 1013 si está llena; 1008 política",
       "app/config.py · app/ws_handler.py")
def _():
    from app import ws_handler
    return _settings().max_sessions == 180 and ws_handler.WS_TRY_AGAIN_LATER == 1013 and \
        ws_handler.WS_POLICY_VIOLATION == 1008


@claim("N3A-03", "C4 N3 API", "Política de privacidad", "Seudonimización HMAC-SHA256 del id de llamada", "app/privacy.py")
def _():
    from app.privacy import pseudonymize
    return len(pseudonymize("x", "k")) == 32 and "hashlib.sha256" in src("services/inference_api/app/privacy.py")


@claim("N3A-04", "C4 N3 API", "Sesión de streaming", "Ventana de 1.000 ms evaluada cada 500 ms, con coalescencia",
       "app/config.py · app/stream.py")
def _():
    s = _settings()
    return s.window_ms == 1000 and s.hop_ms == 500 and "coalesced" in src("services/inference_api/app/stream.py")


@claim("N3A-05", "C4 N3 API", "Sesión de streaming", "El canal del operador se descarta al decodificar", "voxfeatures.pcm16_to_float")
def _():
    import numpy as np
    from voxfeatures import pcm16_to_float
    stereo = np.array([[1000, -32000], [2000, 32000]], dtype="<i2").tobytes()
    out = pcm16_to_float(stereo, channels=2, keep_channel=0)
    return np.allclose(out * 32768, [1000, 2000])


@claim("N3A-06", "C4 N3 API", "Extractor prosódico", "7 rasgos: tono, variación, jitter, energía, var. energía, ZCR, voz",
       "libs/voxfeatures")
def _():
    from voxfeatures import FEATURE_NAMES
    return len(FEATURE_NAMES) == 7


@claim("N3A-07", "C4 N3 API", "Runtime causal", "Solo NumPy: no importa DoWhy/EconML/pandas/scikit-learn ni el batch",
       "tests/architecture/test_isolation.py")
def _():
    return not (imports(API / "app") & {"dowhy", "econml", "pandas", "sklearn", "pipeline"})


@claim("N3A-08", "C4 N3 API", "Runtime causal", "Causa raíz = mayor efecto causal (ATE) entre las causas activas",
       "app/scm_runtime.py")
def _():
    from app.scm_runtime import CausalRuntime, sanitize_context
    art = json.loads(src("services/inference_api/model/model.json"))
    rt = CausalRuntime(art)
    res = rt.infer(sanitize_context({"long_wait": 1, "multi_transfer": 1, "billing_error": 1}, rt.defaults), 0.5)
    best = max(art["treatments"], key=lambda t: art["treatments"][t]["ate"])
    return res.root_cause["cause"] == best


@claim("N3A-09", "C4 N3 API", "Almacén del modelo", "Verifica SHA-256 y esquema; si falla → modo degradado (o no arranca en estricto)",
       "app/model_store.py · Dockerfile STRICT_MODEL=true")
def _():
    return has(src("services/inference_api/app/model_store.py"), "sha256_mismatch", "fallback-rules",
               "ModelUnavailableError") and "STRICT_MODEL=true" in src("services/inference_api/Dockerfile")


@claim("N3A-10", "C4 N3 API", "Publicador de eventos", "Envío no bloqueante a Service Bus (timeout 3 s) con outbox de respaldo",
       "app/events.py")
def _():
    from app import events
    return events.SEND_TIMEOUT_S == 3.0 and has(src("services/inference_api/app/events.py"), "create_task", "_write_outbox")


@claim("N3A-11", "C4 N3 API", "Emisor de SAS", "User Delegation SAS: solo lectura, spr=https, 5 min (máx. 60), clave en caché",
       "app/sas.py")
def _():
    from app.sas import SasIssuer
    s = src("services/inference_api/app/sas.py")
    return _settings().sas_ttl_minutes == 5 and SasIssuer("https://a", "c", 999).ttl.total_seconds() == 3600 and \
        has(s, "user_delegation_key=", "BlobSasPermissions(read=True)", 'protocol="https"', "_key_expiry")


@claim("N3A-12", "C4 N3 API", "Telemetría y auditoría", "Percentiles p50/p95/p99 por etapa y eventos de auditoría",
       "app/telemetry.py")
def _():
    t = src("services/inference_api/app/telemetry.py")
    code = "".join(src(f"services/inference_api/app/{f}") for f in ("model_store.py", "sas.py", "ws_handler.py", "main.py"))
    return has(t, "p50_ms", "p95_ms", "p99_ms") and all(a in code for a in (
        '"model_loaded"', '"model_fallback"', '"sas_issued"', '"channel_rejected"'))


# ───────────────────────────── C4 Nivel 3 — Camino frío ─────────────────────────────
@claim("N3B-01", "C4 N3 batch", "Punto de entrada de jobs", "Modos worker, train y bench", "pipeline/entry.py")
def _():
    return has(src("services/batch_pipeline/pipeline/entry.py"), '"worker"', '"train"', '"bench"')


@claim("N3B-02", "C4 N3 batch", "Generador de datos (SCM)", "3 causas, 3 confusores, mediador estrés; ATE verdadero por do()",
       "pipeline/synthetic.py")
def _():
    from pipeline import synthetic
    return len(synthetic.TREATMENTS) == 3 and len(synthetic.CONFOUNDERS) == 3 and synthetic.MEDIATOR == "stress"


@claim("N3B-03", "C4 N3 batch", "Identificación y estimación", "DoWhy (backdoor) + EconML LinearDML", "pipeline/train.py")
def _():
    return has(src("services/batch_pipeline/pipeline/train.py"), "identify_effect", "backdoor.econml.dml.LinearDML",
               "get_backdoor_variables")


@claim("N3B-04", "C4 N3 batch", "Refutación", "Placebo, causa común aleatoria y subconjunto de datos", "pipeline/train.py")
def _():
    return has(src("services/batch_pipeline/pipeline/train.py"), "placebo_treatment_refuter", "random_common_cause",
               "data_subset_refuter")


@claim("N3B-05", "C4 N3 batch", "Control de calidad", "Publica solo si error ATE ≤ 0,05 y refutaciones aprobadas; si no → rejected/",
       "pipeline/train.py · pipeline/registry.py")
def _():
    from pipeline import train
    return train.ATE_ERROR_MAX == 0.05 and has(src("services/batch_pipeline/pipeline/train.py"), "write_rejected")


@claim("N3B-06", "C4 N3 batch", "Calibración prosódica", "Usa la MISMA librería de rasgos que la API (sin desfase)",
       "pipeline/train.py · libs/voxfeatures")
def _():
    return "voxfeatures" in imports(BATCH / "pipeline") and "voxfeatures" in imports(API / "app")


@claim("N3B-07", "C4 N3 batch", "Worker post-llamada", "Consume Service Bus (o outbox local) y escribe auditoría", "pipeline/worker.py")
def _():
    return has(src("services/batch_pipeline/pipeline/worker.py"), "get_queue_receiver", "complete_message", "_write_audit")


@claim("N3B-08", "C4 N3 batch", "Explicador", "Azure OpenAI con identidad administrada; plantilla si no hay acceso",
       "pipeline/explain.py")
def _():
    return has(src("services/batch_pipeline/pipeline/explain.py"), "get_bearer_token_provider", "template_explanation")


@claim("N3B-09", "C4 N3 batch", "Promoción", "Verifica SHA-256 antes de copiar el modelo a la imagen de la API",
       "tools/promote_model.py")
def _():
    return has(src("tools/promote_model.py"), "hashlib.sha256", "huella no coincide")


# ───────────────────────────── Pipeline MLOps ─────────────────────────────
@claim("PL-01", "Pipeline", "Carril A", "Ingesta → validación → preprocesamiento → rasgos → modelo → entrega → evento",
       "app/ws_handler.py · app/stream.py")
def _():
    w = src("services/inference_api/app/ws_handler.py")
    return has(w, "_handshake", "check_channel", "push_audio", "infer()", "send_json", "_publish_summary")


@claim("PL-02", "Pipeline", "Respaldo", "Silencio/mala calidad → estrés estimado desde el contexto", "app/scm_runtime.py")
def _():
    return has(src("services/inference_api/app/scm_runtime.py"), "MIN_VOICED_RATIO", '"context-fallback"')


@claim("PL-03", "Pipeline", "Carril B", "Promoción vía CI (lint, pruebas, cobertura ≥ 85 %, imágenes)", "ci/vox-causal-ci.yml")
def _():
    return has(src("ci/vox-causal-ci.yml"), "ruff check", "--cov-fail-under=85", "docker build")


@claim("PL-04", "Pipeline", "Verificación en nube", "verify.sh prueba HTTP→HTTPS, TLS<1.2, SAS manipulada, aislamiento",
       "deploy/azure/verify.sh")
def _():
    return has(VERIFY, "--tls-max 1.1", "sp=rw", "peering list", "internal")


@claim("PL-05", "Pipeline", "Telemetría", "Log Analytics con retención de 30 días", "deploy.sh paso 2")
def _():
    return has(DEPLOY, "--retention-time 30")


@claim("PL-06", "Pipeline", "Carril B", "Todas las refutaciones del modelo en producción aprobadas", "model/metrics.json")
def _():
    m = measured()
    return m["refutations_passed"] == m["refutations_total"] > 0


# ───────────────────────────── Cifras medidas (se leen de archivos, no se escriben a mano) ─────────
def measured() -> dict:
    m = json.loads(src("services/inference_api/model/metrics.json"))
    sweep = json.loads(src("bench/results/sweep_1vcpu.json"))
    adm = json.loads(src("bench/results/admission_1vcpu.json"))
    stages = json.loads(src("bench/results/server_stages.json"))
    refs = [r for v in m["treatments"].values() for r in v["refutations"].values()]
    return {
        "stages": stages,
        "refutations_passed": sum(r["passed"] for r in refs),
        "refutations_total": len(refs),
        "dataset": m["dataset"],
        "model_version": m["version"],
        "ate_error_dml": {t: v["error_dml"] for t, v in m["treatments"].items()},
        "ate_error_naive": {t: v["error_naive"] for t, v in m["treatments"].items()},
        "stress_mae": m["stress_calibration"]["mae"],
        "stress_r2": m["stress_calibration"]["r2"],
        "p95_100": next(r["p95_ms"] for r in sweep if r["streams"] == 100),
        "p95_180": next(r["p95_ms"] for r in adm if r["streams"] == 180),
        "overload": next(r for r in adm if r["streams"] == 400),
    }


def run_all() -> list[tuple[Claim, bool, str]]:
    out = []
    for c in CLAIMS:
        try:
            ok, err = bool(c.check()), ""
        except Exception as exc:  # noqa: BLE001
            ok, err = False, f"{type(exc).__name__}: {exc}"
        out.append((c, ok, err))
    return out


def write_markdown(results, path: Path) -> None:
    m = measured()
    lines = [
        "# Trazabilidad diagrama ↔ código",
        "",
        "Generado por `python tools/architecture_claims.py`. Cada fila es una comprobación ejecutable;",
        "la prueba `tests/architecture/test_traceability.py` falla si alguna deja de cumplirse.",
        "",
        f"**Resultado: {sum(ok for _, ok, _ in results)} de {len(results)} afirmaciones verificadas.**",
        "",
        "| ID | Diagrama | Elemento | Afirmación | Estado | Evidencia | ✔ |",
        "|---|---|---|---|---|---|---|",
    ]
    for c, ok, err in results:
        lines.append(f"| {c.id} | {c.diagram} | {c.element} | {c.statement} | {c.status} | `{c.evidence}` | "
                     f"{'✔' if ok else '✘ ' + err} |")
    lines += [
        "",
        "## Cifras usadas en los diagramas (leídas de archivos de resultados)",
        "",
        f"- Modelo en producción: `{m['model_version']}`",
        "- Error de ATE (DML): " + ", ".join(f"{k} {v:.4f}" for k, v in m["ate_error_dml"].items()),
        "- Error de ATE (correlacional): " + ", ".join(f"{k} {v:.4f}" for k, v in m["ate_error_naive"].items()),
        f"- Estimador prosódico: MAE {m['stress_mae']} · R² {m['stress_r2']}",
        f"- Latencia p95 extremo a extremo: 100 llamadas {m['p95_100']} ms · 180 llamadas {m['p95_180']} ms",
        f"- Sobrecarga 400 ofrecidas: {m['overload']['p95_ms']} ms p95, "
        f"{m['overload']['errors'].get('closed_1013', 0)} derivadas (1013)",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    results = run_all()
    for c, ok, err in results:
        print(f"{'✔' if ok else '✘'} {c.id:7s} {c.diagram:12s} {c.statement}{'  ← ' + err if err else ''}")
    write_markdown(results, ROOT / "docs" / "TRAZABILIDAD.md")
    failed = [c.id for c, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verificadas" + (f" · fallan: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
