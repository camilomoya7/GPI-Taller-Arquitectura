# Trazabilidad diagrama ↔ código

Generado por `python tools/architecture_claims.py`. Cada fila es una comprobación ejecutable;
la prueba `tests/architecture/test_traceability.py` falla si alguna deja de cumplirse.

**Resultado: 51 de 51 afirmaciones verificadas.**

| ID | Diagrama | Elemento | Afirmación | Estado | Evidencia | ✔ |
|---|---|---|---|---|---|---|
| N1-01 | C4 N1 | Cliente que llama | Solo se analiza el canal del cliente | Implementado | `app/privacy.py` | ✔ |
| N1-02 | C4 N1 | Operador | La voz del operador se rechaza (EU AI Act art. 5.1.f) | Implementado | `app/privacy.py` | ✔ |
| N1-03 | C4 N1 | Supervisor | Recibe explicación post-llamada y accede a grabaciones con SAS | Implementado | `pipeline/explain.py · app/sas.py` | ✔ |
| N1-04 | C4 N1 | Equipo MLOps | Entrena, aprueba (control de calidad) y promueve modelos | Implementado | `pipeline/train.py · tools/promote_model.py` | ✔ |
| N1-05 | C4 N1 | Plataforma de telefonía | Envía audio PCM16 y contexto por WebSocket seguro (WSS) | Implementado | `app/ws_handler.py · deploy.sh (ingress HTTPS)` | ✔ |
| N1-06 | C4 N1 | Azure OpenAI | Solo redacta la explicación; si falla se usa plantilla (no decide la causa) | Implementado | `pipeline/explain.py` | ✔ |
| N1-07 | C4 N1 | Microsoft Entra ID | Autenticación sin claves: identidades administradas | Implementado | `DefaultAzureCredential en sas.py, events.py, worker.py` | ✔ |
| N1-08 | C4 N1 | Log Analytics | Logs JSON a stdout recolectados por Log Analytics | Implementado | `app/telemetry.py · deploy.sh` | ✔ |
| N2-01 | C4 N2 | API de inferencia | FastAPI sobre Python 3.12 en contenedor propio | Implementado | `inference_api/Dockerfile` | ✔ |
| N2-02 | C4 N2 | API de inferencia | 1 vCPU por réplica, 1 a 10 réplicas, escala con 150 conexiones | Implementado | `deploy.sh paso 11` | ✔ |
| N2-03 | C4 N2 | API de inferencia | Imagen sin DoWhy/EconML/pandas/scikit-learn | Implementado | `inference_api/requirements.txt` | ✔ |
| N2-04 | C4 N2 | Cola call-closed | Service Bus solo con Entra ID; API = Sender, batch = Receiver | Implementado | `deploy.sh paso 8` | ✔ |
| N2-05 | C4 N2 | Worker post-llamada | Container Apps Job en la zona batch | Implementado | `deploy.sh paso 12 · pipeline/worker.py` | ✔ |
| N2-06 | C4 N2 | Entrenamiento causal | Container Apps Job con DoWhy + EconML en la zona batch | Implementado | `deploy.sh · batch_pipeline/requirements.txt` | ✔ |
| N2-07 | C4 N2 | Registro de modelos | Versionado + SHA-256 + puntero production; copia en Blob model-registry | Implementado | `pipeline/registry.py` | ✔ |
| N2-08 | C4 N2 | Blob Storage | TLS ≥ 1.2, solo HTTPS, sin claves compartidas, sin acceso público | Implementado | `deploy.sh paso 7` | ✔ |
| N2-09 | C4 N2 | Blob Storage | Retención de grabaciones: borrado a los 30 días (UK GDPR) | Implementado | `deploy.sh paso 7` | ✔ |
| N2-10 | C4 N2 | Región | Todos los recursos en UK South (residencia de datos) | Implementado | `deploy.sh · config.py` | ✔ |
| N2-11 | C4 N2 | Zonas A y B | VNets separadas (10.10/16 y 10.20/16) sin peering | Implementado | `deploy.sh paso 3` | ✔ |
| N2-12 | C4 N2 | Zona B | Entorno batch sin ingreso público (internal-only) | Implementado | `deploy.sh paso 10` | ✔ |
| N2-13 | C4 N2 | Contrato entre zonas | Único contrato: model.json + SHA-256 dentro de la imagen de la API | Implementado | `inference_api/Dockerfile` | ✔ |
| N2-14 | C4 N2 | Transversal | Key Vault con RBAC, ACR sin usuario admin, 3 identidades administradas | Implementado | `deploy.sh pasos 4, 6 y 9` | ✔ |
| N2-15 | C4 N2 | Gateway | Azure API Management (WebSocket requiere nivel Developer o superior) | Diseño productivo | `README · diseño productivo` | ✔ |
| N2-16 | C4 N2 | Red privada | Private Endpoints para Storage, Service Bus y Key Vault | Diseño productivo | `README · diseño productivo` | ✔ |
| N3A-01 | C4 N3 API | Borde WebSocket/REST | Token Bearer comparado en tiempo constante | Implementado | `app/main.py` | ✔ |
| N3A-02 | C4 N3 API | Borde WebSocket/REST | Admisión: 180 sesiones por réplica; cierre 1013 si está llena; 1008 política | Implementado | `app/config.py · app/ws_handler.py` | ✔ |
| N3A-03 | C4 N3 API | Política de privacidad | Seudonimización HMAC-SHA256 del id de llamada | Implementado | `app/privacy.py` | ✔ |
| N3A-04 | C4 N3 API | Sesión de streaming | Ventana de 1.000 ms evaluada cada 500 ms, con coalescencia | Implementado | `app/config.py · app/stream.py` | ✔ |
| N3A-05 | C4 N3 API | Sesión de streaming | El canal del operador se descarta al decodificar | Implementado | `voxfeatures.pcm16_to_float` | ✔ |
| N3A-06 | C4 N3 API | Extractor prosódico | 7 rasgos: tono, variación, jitter, energía, var. energía, ZCR, voz | Implementado | `libs/voxfeatures` | ✔ |
| N3A-07 | C4 N3 API | Runtime causal | Solo NumPy: no importa DoWhy/EconML/pandas/scikit-learn ni el batch | Implementado | `tests/architecture/test_isolation.py` | ✔ |
| N3A-08 | C4 N3 API | Runtime causal | Causa raíz = mayor efecto causal (ATE) entre las causas activas | Implementado | `app/scm_runtime.py` | ✔ |
| N3A-09 | C4 N3 API | Almacén del modelo | Verifica SHA-256 y esquema; si falla → modo degradado (o no arranca en estricto) | Implementado | `app/model_store.py · Dockerfile STRICT_MODEL=true` | ✔ |
| N3A-10 | C4 N3 API | Publicador de eventos | Envío no bloqueante a Service Bus (timeout 3 s) con outbox de respaldo | Implementado | `app/events.py` | ✔ |
| N3A-11 | C4 N3 API | Emisor de SAS | User Delegation SAS: solo lectura, spr=https, 5 min (máx. 60), clave en caché | Implementado | `app/sas.py` | ✔ |
| N3A-12 | C4 N3 API | Telemetría y auditoría | Percentiles p50/p95/p99 por etapa y eventos de auditoría | Implementado | `app/telemetry.py` | ✔ |
| N3B-01 | C4 N3 batch | Punto de entrada de jobs | Modos worker, train y bench | Implementado | `pipeline/entry.py` | ✔ |
| N3B-02 | C4 N3 batch | Generador de datos (SCM) | 3 causas, 3 confusores, mediador estrés; ATE verdadero por do() | Implementado | `pipeline/synthetic.py` | ✔ |
| N3B-03 | C4 N3 batch | Identificación y estimación | DoWhy (backdoor) + EconML LinearDML | Implementado | `pipeline/train.py` | ✔ |
| N3B-04 | C4 N3 batch | Refutación | Placebo, causa común aleatoria y subconjunto de datos | Implementado | `pipeline/train.py` | ✔ |
| N3B-05 | C4 N3 batch | Control de calidad | Publica solo si error ATE ≤ 0,05 y refutaciones aprobadas; si no → rejected/ | Implementado | `pipeline/train.py · pipeline/registry.py` | ✔ |
| N3B-06 | C4 N3 batch | Calibración prosódica | Usa la MISMA librería de rasgos que la API (sin desfase) | Implementado | `pipeline/train.py · libs/voxfeatures` | ✔ |
| N3B-07 | C4 N3 batch | Worker post-llamada | Consume Service Bus (o outbox local) y escribe auditoría | Implementado | `pipeline/worker.py` | ✔ |
| N3B-08 | C4 N3 batch | Explicador | Azure OpenAI con identidad administrada; plantilla si no hay acceso | Implementado | `pipeline/explain.py` | ✔ |
| N3B-09 | C4 N3 batch | Promoción | Verifica SHA-256 antes de copiar el modelo a la imagen de la API | Implementado | `tools/promote_model.py` | ✔ |
| PL-01 | Pipeline | Carril A | Ingesta → validación → preprocesamiento → rasgos → modelo → entrega → evento | Implementado | `app/ws_handler.py · app/stream.py` | ✔ |
| PL-02 | Pipeline | Respaldo | Silencio/mala calidad → estrés estimado desde el contexto | Implementado | `app/scm_runtime.py` | ✔ |
| PL-03 | Pipeline | Carril B | Promoción vía CI (lint, pruebas, cobertura ≥ 85 %, imágenes) | Implementado | `ci/vox-causal-ci.yml` | ✔ |
| PL-04 | Pipeline | Verificación en nube | verify.sh prueba HTTP→HTTPS, TLS<1.2, SAS manipulada, aislamiento | Implementado | `deploy/azure/verify.sh` | ✔ |
| PL-05 | Pipeline | Telemetría | Log Analytics con retención de 30 días | Implementado | `deploy.sh paso 2` | ✔ |
| PL-06 | Pipeline | Carril B | Todas las refutaciones del modelo en producción aprobadas | Implementado | `model/metrics.json` | ✔ |

## Cifras usadas en los diagramas (leídas de archivos de resultados)

- Modelo en producción: `2026.10.27-183551`
- Error de ATE (DML): long_wait 0.0022, multi_transfer 0.0040, billing_error 0.0006
- Error de ATE (correlacional): long_wait 0.0562, multi_transfer 0.0076, billing_error 0.0316
- Estimador prosódico: MAE 0.0408 · R² 0.969
- Latencia p95 extremo a extremo: 100 llamadas 8.95 ms · 180 llamadas 23.14 ms
- Sobrecarga 400 ofrecidas: 59.36 ms p95, 220 derivadas (1013)
