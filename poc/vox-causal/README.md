# Vox-Causal AI — Prueba de concepto de integración en Azure

Motor de **inferencia causal + análisis prosódico en tiempo real** para identificar la causa raíz del
riesgo de fuga (churn) durante una llamada, preparado para integrarse en la plataforma SaaS de
Alloxentric SpA (Microsoft Azure, UK South).
Caso PIA · Gestión de Proyectos Informáticos 2026-II · UTEM.

> Resultados medidos (ATE, latencia, concurrencia, cobertura): **[docs/EVIDENCIA.md](docs/EVIDENCIA.md)**
> Diagramas C4 y pipeline: **[docs/diagrams/](docs/diagrams/)** · Trazabilidad diagrama ↔ código: **[docs/TRAZABILIDAD.md](docs/TRAZABILIDAD.md)**

## Diagramas (generados desde el código)

| Diagrama | Archivo |
|---|---|
| C4 Nivel 1 — Contexto | `docs/diagrams/C4_N1_Contexto.png` |
| C4 Nivel 2 — Contenedores (dos zonas aisladas) | `docs/diagrams/C4_N2_Contenedores.png` |
| C4 Nivel 3 — Componentes de la API (camino caliente) | `docs/diagrams/C4_N3_Componentes_API.png` |
| C4 Nivel 3 — Componentes del pipeline batch (camino frío) | `docs/diagrams/C4_N3_Componentes_Batch.png` |
| Pipeline MLOps e inferencia | `docs/diagrams/Pipeline_MLOps_Inferencia.png` |

Las cifras de los diagramas se leen de `model/metrics.json` y `bench/results/`, y cada afirmación se
verifica contra el código (`tools/architecture_claims.py`; prueba `tests/architecture/test_traceability.py`).
Regenerar: `bash tools/render_diagrams.sh`.

## Idea central: dos caminos aislados

| | Camino caliente (tiempo real) | Camino frío (batch / asíncrono) |
|---|---|---|
| Objetivo | Diagnóstico al operador en **< 200 ms** | Aprender y validar el modelo causal; explicar y auditar |
| Qué hace | Voz del cliente → rasgos prosódicos → modelo causal **ya ajustado** → causa raíz | Datos → DAG + DoWhy/EconML → refutación → control de calidad → registro; explicación post-llamada |
| Código | `services/inference_api` (FastAPI, NumPy) | `services/batch_pipeline` (DoWhy, EconML, Azure OpenAI opcional) |
| Azure | Container Apps `cae-rt` (VNet propia, réplicas 1–10) | Container Apps Jobs en `cae-batch` (VNet propia, sin ingreso público) |
| Contrato | — recibe solo el **modelo aprobado** (JSON + SHA-256) dentro de su imagen — | — publica ese modelo; recibe eventos por Service Bus — |

**Por qué se separan:** Service Bus (asíncrono), Azure OpenAI (cientos de ms a segundos) y la
estimación causal (segundos a minutos) no caben en 200 ms. Fuera del camino en vivo, la inferencia
cuesta ~2,4 ms (p95). Además, la restricción 2 exige que un reentrenamiento nunca compita por
recursos con la API: por eso tienen imagen, cómputo, red, identidad y permisos distintos.

## Estructura

```
poc/vox-causal/
├── libs/voxfeatures/           Rasgos prosódicos compartidos (evita desfase entrenamiento/servicio)
├── services/
│   ├── inference_api/          Camino caliente: FastAPI + WebSocket, SAS, telemetría, privacidad
│   │   ├── app/                main, ws_handler, stream, scm_runtime, model_store, sas, events, privacy, telemetry
│   │   └── model/              Modelo aprobado (model.json + sha256 + metrics.json)
│   └── batch_pipeline/         Camino frío: synthetic, train, registry, worker, explain, entry
├── tests/                      unit · integration · batch · architecture (aislamiento)
├── bench/                      Benchmark WebSocket de latencia/concurrencia + resultados
├── tools/                      Demo, promoción de modelo, trazabilidad y generación de diagramas
├── deploy/azure/               deploy.sh · verify.sh · teardown.sh
├── erv/                        EVM (evm.py), modelo financiero (finance.py), informe Word (report/) y resultados (out/)
├── ci/vox-causal-ci.yml        Workflow de GitHub Actions (copiar a .github/workflows/)
└── docs/                       EVIDENCIA.md · TRAZABILIDAD.md · diagrams/ (PNG + fuentes)
```

## Ejecutar localmente (≈ 10 min)

Requisitos: Python 3.12.

```bash
cd poc/vox-causal
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r services/inference_api/requirements.txt -r services/batch_pipeline/requirements.txt
pip install ./libs/voxfeatures pytest pytest-cov pytest-asyncio httpx ruff radon

# 1) Pruebas + cobertura
pytest -q --cov

# 2) (Opcional) Reentrenar el modelo causal y promoverlo (≈ 8 min)
(cd services/batch_pipeline && python -m pipeline.train --registry ../../registry)
python tools/promote_model.py --registry registry

# 3) Levantar la API (otra terminal)
bash tools/run_api_local.sh

# 4) Demo de llamada en vivo y rechazo del canal del operador
python tools/simulate_call.py --scenario escalation
python tools/simulate_call.py --scenario operator_channel

# 5) Benchmark de concurrencia
python bench/ws_load.py --sweep 100,180,400 --seconds 20

# 6) Camino frío: procesar los eventos que dejó la API
(cd services/batch_pipeline && OUTBOX_PATH=../../var/outbox/events.jsonl python -m pipeline.worker --once)
```

Alternativa con Docker: `docker compose up --build api` y `docker compose run --rm worker`.

## Desplegar en Azure (≈ 25 min)

Requisitos: Azure CLI ≥ 2.60, `az login` con una suscripción donde tengan rol **Owner**, Python 3.12 (para `verify.sh`).

```bash
cd poc/vox-causal
bash deploy/azure/deploy.sh          # crea todo en UK South
bash deploy/azure/verify.sh | tee docs/evidencia-azure.txt   # pruebas de R1 y R2 en la nube
bash deploy/azure/teardown.sh        # elimina todo al terminar la demo
```

Opciones: `LOCATION=ukwest` si la suscripción restringe regiones (las suscripciones académicas suelen
tener una lista de regiones permitidas); `BUILD_MODE=docker` si ACR Tasks no está habilitado en la
suscripción (requiere Docker local); `USE_KEYVAULT=false` para usar secretos de Container Apps en lugar de Key Vault.

**Recursos que crea:** grupo de recursos, Log Analytics, 2 VNets sin peering, ACR Basic, 3 identidades
administradas, Storage (TLS 1.2, solo HTTPS, sin claves, sin acceso público, retención de 30 días),
Service Bus Basic (solo Entra ID), Key Vault (RBAC), 3 entornos de Container Apps, la API y 3 jobs.

**Costo estimado de la demo:** del orden de US$1–2 por día con la API en 1 réplica (ACR Basic ≈ US$0,17/día;
Container Apps de consumo cubierto en gran parte por la cuota gratuita mensual; Service Bus Basic, Storage
y Key Vault con consumo marginal). Verificar en la calculadora de precios de Azure y ejecutar `teardown.sh` al terminar.

### Alcance de la prueba de concepto y restricciones de la suscripción

| Componente del diseño | En la PoC | Motivo |
|---|---|---|
| Azure API Management | Ingreso HTTPS/WSS de Container Apps (TLS 1.2+, token Bearer) | El nivel Consumption de APIM no admite WebSocket; el nivel Developer cuesta ≈ US$50/mes y no tiene SLA. El diseño productivo lo incluye. |
| Azure OpenAI | Integrado con identidad administrada; respaldo por plantilla | Las suscripciones académicas tienen acceso/cuota restringidos a Azure OpenAI. El código lo usa si se configura `AZURE_OPENAI_ENDPOINT`. |
| GPU | Inferencia en CPU (~2,4 ms p95) | Sin cuota de GPU en suscripciones académicas; además la medición muestra que la CPU basta para el camino caliente. |
| Private Endpoints | Redes separadas + identidades + TLS | Cada Private Endpoint tiene costo mensual y requiere zonas DNS privadas; se incluye en el diseño productivo. |
| Datos reales de llamadas | Datos sintéticos con efecto causal conocido | Los audios de clientes son datos personales (UK GDPR); además, el error de ATE solo se puede medir con efecto verdadero conocido. |
| 1.500 llamadas simultáneas | Capacidad medida por réplica (180) + autoescalado a 10 réplicas + control de admisión | Una prueba de 1.500 conexiones requiere cuota de núcleos superior a la de la suscripción académica. |

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health`, `/ready` | Vida y disponibilidad (indica si opera en modo degradado) |
| GET | `/metrics` | p50/p95/p99 por etapa, sesiones activas, rechazos por capacidad |
| GET | `/v1/model` | Versión, SHA-256 y efectos causales del modelo en uso |
| POST | `/v1/infer` | Inferencia puntual (audio base64, 1 s) |
| WS | `/v1/stream` | Streaming: `start` → audio PCM16 → `inference` cada 500 ms → `stop` → `summary` |
| POST | `/v1/recordings/{call_ref}/access` | URL temporal (User Delegation SAS, solo lectura, solo HTTPS, 5 min) |

Cierres WebSocket: `1008` política (token, canal del operador, protocolo) · `1013` réplica sin capacidad.

## Informe ERV (Word)

```bash
python erv/evm.py && python erv/finance.py        # EVM y evaluación económica → erv/out/
python erv/report/build.py                         # informe en dos pasadas (índice con páginas) → erv/report/*.docx y *.pdf
python erv/report/verify_report.py                 # comprueba que cada cifra del informe coincide con los resultados
```
Copiar `erv/report/Informe_ERV_VoxCausal_Grupo1.docx` (y su PDF) a `/docs/erv/` en la raíz del repositorio.
