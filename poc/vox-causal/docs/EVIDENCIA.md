# Evidencia medida — Vox-Causal AI (prueba de concepto)

Todas las cifras de este documento se obtuvieron ejecutando el código de este repositorio.
Entorno de medición local: Linux, Intel Xeon 2,1 GHz, **API limitada a 1 núcleo** (`taskset`) para
reproducir una réplica de 1 vCPU de Azure Container Apps; el cliente de carga corre en otro núcleo.
Las mediciones dentro de Azure UK South se generan con `deploy/azure/verify.sh` (job `bench`).

## 1. Precisión causal — KPI: error de ATE ≤ 0,05

**Definición operativa del KPI.** El ATE se mide en la escala de **probabilidad de fuga (churn) a 90 días**
(0 a 1). Error = |ATE estimado − ATE verdadero|. El ATE verdadero se conoce porque el dataset de prueba
proviene de un modelo causal estructural con ecuaciones conocidas: se simulan las intervenciones
do(T=1) y do(T=0) sobre las mismas unidades y el mismo ruido. Sin un efecto verdadero conocido, el
error de ATE no se puede medir; por eso el KPI se valida sobre datos de prueba con efecto conocido.

Dataset: 50.000 llamadas, semilla 7; robustez con 5 réplicas (semillas 7 a 11).
Estimador de producción: Double Machine Learning (EconML `LinearDML`) vía DoWhy, ajuste por criterio backdoor.

| Causa raíz (tratamiento) | ATE verdadero | Correlacional (diferencia simple) | Error correlacional | DoWhy + EconML DML | **Error DML** | Error máx. en 5 réplicas | Conjunto de ajuste (backdoor) |
|---|---|---|---|---|---|---|---|
| Espera prolongada | 0,1224 | 0,1787 | **0,0562 ✘** | 0,1247 | **0,0022 ✔** | 0,0049 | antigüedad, contacto repetido |
| Múltiples transferencias | 0,1299 | 0,1375 | 0,0076 | 0,1259 | **0,0040 ✔** | 0,0040 | contacto repetido |
| Error de facturación | 0,1374 | 0,1058 | 0,0316 | 0,1368 | **0,0006 ✔** | 0,0076 | antigüedad |

**Hallazgo clave (correlación vs. causalidad):** el enfoque correlacional **incumple el KPI** (error 0,056 > 0,05)
y además **invierte el orden de las causas**: ordena espera > transferencias > facturación, cuando el orden
causal real es facturación > transferencias > espera. Un operador guiado por correlaciones atacaría
primero la causa de menor impacto.

### Pruebas de refutación (DoWhy) — todas aprobadas

| Tratamiento | Placebo (efecto debe ser ≈ 0) | Causa común aleatoria (no debe moverse) | Subconjunto 80 % (estable) |
|---|---|---|---|
| Espera prolongada | 0,0007 ✔ | 0,1272 (=0,1272) ✔ | 0,1271 ✔ |
| Múltiples transferencias | −0,0005 ✔ | 0,1254 (=0,1254) ✔ | 0,1252 ✔ |
| Error de facturación | 0,0008 ✔ | 0,1397 (=0,1397) ✔ | 0,1392 ✔ |

Control de calidad del pipeline: si algún error > 0,05 o falla una refutación, **el modelo no se publica**
(se guarda en `registry/…/rejected/`) y la API sigue con la versión anterior. Probado en
`tests/batch/test_batch_pipeline.py::test_full_training_run_publishes_and_gate_rejects`.

### Estimador prosódico (voz → estrés)
Calibrado con 800 clips sintéticos de estrés conocido, evaluado en 400 clips no vistos:
**MAE = 0,041 · R² = 0,969** (escala 0–1).

## 2. Latencia — KPI: < 200 ms (restricción 1)

Costo por etapa en el servidor, perfil aislado sin red (`bench/stage_profile.py`, 1 núcleo, 20.000 inferencias,
archivo `bench/results/server_stages.json`): rasgos p95 1,86 ms · modelo p95 0,09 ms · **total p95 2,01 ms**.

Costo por etapa bajo carga real (20.000 inferencias durante el barrido de concurrencia, `/metrics`):

| Etapa | p50 | p95 | p99 |
|---|---|---|---|
| Rasgos prosódicos (ventana 1 s) | 1,46 ms | 2,26 ms | 3,11 ms |
| Evaluación del modelo causal precalculado | 0,055 ms | 0,10 ms | 0,16 ms |
| **Total servidor** | **1,56 ms** | **2,40 ms** | **3,30 ms** |

Latencia extremo a extremo (trama enviada → diagnóstico recibido), llamadas en tiempo real, 1 vCPU:

| Llamadas simultáneas | p50 | p95 | p99 | % < 200 ms |
|---|---|---|---|---|
| 100 | 3,4 ms | 9,0 ms | 14,5 ms | 100 % |
| 180 (tope por réplica) | 6,1 ms | 23,1 ms | 46,9 ms | 100 % |
| 200 | 8,1 ms | 43,2 ms | 65,5 ms | 100 % |
| 250 (sin control de admisión) | 46,0 ms | 235 ms | 332 ms | 92,3 % |
| 300 (sin control de admisión) | 1.290 ms | 4.032 ms | 4.992 ms | 14,9 % |

Interpretación: el cómputo por ventana es mínimo; el límite lo pone la saturación de CPU por
conexiones. Por eso cada réplica tiene **control de admisión (180 sesiones)**.

## 3. Concurrencia — KPI: 1.500 llamadas sin degradación

Prueba de sobrecarga con control de admisión (1 réplica, 400 llamadas ofrecidas):

| Ofrecidas | Aceptadas | p95 aceptadas | % < 200 ms | Derivadas a otra réplica (cierre 1013) |
|---|---|---|---|---|
| 400 | 180 | 59,4 ms | 100 % | 220 |

La réplica **nunca se degrada**: lo que excede su capacidad se rechaza de inmediato para que el
balanceador lo asigne a otra réplica, y el autoescalado (regla HTTP, 150 conexiones por réplica) agrega réplicas.

**Dimensionamiento para 1.500 llamadas:** ⌈1.500 / 180⌉ = 9 réplicas de 1 vCPU + 1 de redundancia
(N+1) = **10 réplicas** (`--max-replicas 10`). Este número alimenta el OPEX del capítulo económico.

## 4. Seguridad y privacidad (restricción 1 y normativa)

| Control | Evidencia |
|---|---|
| SAS de delegación de usuario (Entra ID), `spr=https`, `sp=r`, 5 min | `tests/unit/test_sas.py`; en Azure: `verify.sh` |
| SAS por HTTP / manipulada / escritura → rechazo | `verify.sh` (Azure) |
| Cuenta sin claves compartidas ni acceso público, TLS ≥ 1.2 | `deploy.sh` paso 7; `verify.sh` |
| Retención de grabaciones 30 días (UK GDPR) | política de ciclo de vida en `deploy.sh` |
| Seudonimización HMAC-SHA256 del id de llamada | `tests/unit/test_model_store_privacy_events.py` |
| Canal del operador rechazado (EU AI Act art. 5.1.f) | `test_stream_rejects_operator_channel`, `test_operator_voice_does_not_influence_result` |
| Audio en vivo nunca persistido en el camino caliente | `ws_handler.py` (descartado al cerrar sesión) |
| Integridad del modelo (SHA-256) y modo degradado | `test_tampered_artifact_falls_back` |

## 5. Aislamiento estricto (restricción 2)

| Control | Evidencia |
|---|---|
| La API no importa DoWhy/EconML/pandas/sklearn ni código batch | `tests/architecture/test_isolation.py` (falla el CI si se rompe) |
| Imágenes separadas; dependencias API ≈ 135 MB vs batch ≈ 928 MB | `requirements.txt` de cada servicio |
| Único contrato: modelo aprobado (JSON + SHA-256) dentro de la imagen | `services/inference_api/Dockerfile` |
| Mensajería de una vía (API = Sender, batch = Receiver) | roles RBAC en `deploy.sh` paso 8 |
| VNets separadas sin peering; entorno batch solo interno | `deploy.sh` pasos 3 y 10; `verify.sh` |

## 6. Calidad de software

| Métrica | Valor |
|---|---|
| Pruebas automatizadas | 114 aprobadas (unitarias, integración, batch, arquitectura y 51 de trazabilidad) |
| Cobertura de código (líneas + ramas) | **96 %** |
| Lint (ruff: estilo, errores, seguridad `S`, complejidad) | 0 hallazgos |
| Complejidad ciclomática promedio (radon) | A (2,67); máxima 12 (`train.run`) |
| Índice de mantenibilidad (radon) | todos los módulos en grado A |
| Tamaño | 1.447 líneas de código fuente (SLOC) |
