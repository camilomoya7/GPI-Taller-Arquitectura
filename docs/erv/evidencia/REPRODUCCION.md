# Reproducción de la PoC Vox-Causal AI del equipo (27-10-2026)

## Versión analizada

| Elemento | Valor |
|---|---|
| Paquete | `Entrega_Parte2_Grupo1.zip` (SHA-256 `745424e26c248ef1d808df0b9ede6e3a1e6466e93ff3957996e3bf6d3947aeec`) |
| Ruta | `Proyecto-GPI/poc/vox-causal/` (versión de 114 pruebas) |
| Versión anterior reproducida | `vox-causal-poc.zip` (62 pruebas) |
| Diferencias | `services/` y `libs/` idénticos (mismo código de ejecución). Nuevos: `tests/architecture/test_traceability.py` (52 pruebas), `tools/architecture_claims.py`, `tools/build_diagrams.py`, `tools/render_diagrams.sh`, `tools/render_pipeline.py`, `bench/stage_profile.py`, `bench/results/server_stages.json`, `docs/diagrams/`, `docs/TRAZABILIDAD.md`, `erv/` (EVM y modelo financiero de la Parte 2) |

Se extrajo en una carpeta temporal aislada, fuera del repositorio TryAIGap. No se modificó el código de la PoC ni el de TryAIGap.
**No se ejecutaron** `deploy/azure/deploy.sh`, `verify.sh` ni `teardown.sh`, y no se crearon recursos en Azure.

## Entorno

| Elemento | Valor |
|---|---|
| Sistema | Windows 10 (19045), CPU Intel de 12 núcleos lógicos |
| Python | 3.12.4, entorno virtual propio con los `requirements.txt` fijados de ambos servicios |
| Versiones clave | dowhy 0.14, econml 0.17.0, fastapi 0.162.0, numpy 2.4.6, pandas 3.1.0, scikit-learn 1.9.1 |
| Aislamiento de CPU (benchmark) | API con afinidad a 1 núcleo (`ProcessorAffinity = 1`, equivalente de `taskset`); cliente de carga en otro núcleo |
| Diferencias con el entorno del equipo | Linux + Xeon 2,1 GHz + `uvloop` (documentado) frente a Windows + bucle Proactor de asyncio (reproducido); equipo de escritorio con otros procesos activos |

## Comandos

```text
pip install -r services/inference_api/requirements.txt -r services/batch_pipeline/requirements.txt
pip install ./libs/voxfeatures pytest pytest-cov pytest-asyncio httpx ruff radon
PYTHONUTF8=1 pytest -q --cov                      # 114/114 en 340 s
ruff check .
radon cc -s -a services libs
uvicorn app.main:app --port 8765 --http httptools # MAX_SESSIONS=180, STRICT_MODEL=true, afinidad 1 núcleo
python bench/ws_load.py --sweep 100,180,250 --seconds 20
python bench/ws_load.py --streams 180 --seconds 20   # 5 corridas
python bench/ws_load.py --streams 100 --seconds 20   # 3 corridas
python -m pipeline.train --registry <registro temporal>   # 50.000 llamadas, semilla 7, 5 réplicas
```

El benchmark y el entrenamiento se ejecutaron sobre la versión de 62 pruebas; como `services/` y `libs/` son
idénticos en la versión de 114 pruebas, esos resultados aplican a ambas.

## Resultados

| Indicador | Documentado por el equipo | Reproducido | Clasificación |
|---|---|---|---|
| Pruebas | 114 aprobadas | 114/114 (`pytest_114_cobertura.txt`); requiere `PYTHONUTF8=1` en Windows (`read_text()` sin `encoding`) | Reproducido |
| Pruebas nuevas | 52 | 51 afirmaciones de diagramas (N1 8, N2 16, N3 API 12, N3 batch 9, pipeline 6) + 1 de consistencia de cifras | Reproducido |
| Cobertura líneas + ramas | 95,9 % | 96 % (980 sentencias, 146 ramas; `cobertura_114.json`) | Reproducido |
| Ruff | 0 | 0 | Reproducido |
| Complejidad (radon) | A (2,66); máx. 12 | A (2,66); máx. grado C en `train.run` | Reproducido |
| Error ATE DML (espera / transferencias / facturación) | 0,0022 / 0,0040 / 0,0006 | 0,0022 / 0,0040 / 0,0006; máx. en 5 réplicas 0,0049 / 0,0040 / 0,0076; refutaciones y gate aprobados | Reproducido |
| Servidor por ventana p50 / p95 / p99 | 1,44 / 2,01 / 2,60 ms (`server_stages.json`) | 1,90 / 2,91 / 3,70 ms (20.000 inferencias) | Reproducido (orden de magnitud) |
| Extremo a extremo, 100 llamadas, p50 / p95 / p99 | 3,4 / 9,0 / 14,5 ms | 12,7–13,5 / 31,0–32,0 / 38,1–42,5 ms en 3 corridas, 100 % < 200 ms (una corrida inicial de calentamiento: p95 610 ms) | Reproducido con otra cifra |
| Extremo a extremo, 180 llamadas, p95 | 23,1 ms (p50 6,1; p99 46,9) | 912 / 90 / 524 / 2.827 / 63 ms en 5 corridas; solo 2 cumplen < 200 ms y < 250 ms | **No reproducido** |
| Control de admisión | 400 ofrecidas → 180 aceptadas, p95 59,4 ms | 250 ofrecidas → 180 aceptadas, 70 rechazadas (1013), p95 57,3 ms | Reproducido |
| 1.500 llamadas concurrentes | Dimensionamiento: 10 réplicas (⌈1.500/180⌉ + 1) | Sin prueba | **Sin verificar** (cálculo, no medición) |
| Mediciones en Azure UK South | Previstas con `verify.sh` | No ejecutadas | **Sin verificar** |

Nota: `test_measured_figures_are_consistent` comprueba las cifras **guardadas** en `bench/results/` y en
`model/metrics.json`; no vuelve a medir la latencia. Las 51 afirmaciones de trazabilidad son comprobaciones
estáticas del código frente a los diagramas.

## Umbrales de latencia

- KPI oficial del caso (enunciado GPI 2026-II): **< 250 ms**.
- Meta interna de la PoC (restricción R1 del incidente): **< 200 ms**.

## Lectura

El costo de cómputo por ventana, la precisión causal, la calidad del código, la trazabilidad de los diagramas
y el control de admisión se reproducen. La capacidad de 180 sesiones por réplica no se reproduce de forma
estable en este equipo; 100 sesiones por réplica es la capacidad estable observada y se usa como escenario
pesimista del modelo financiero (16 réplicas). La escala de 1.500 llamadas y cualquier cifra en Azure siguen
sin verificar.

## Archivos de esta carpeta

| Archivo | Contenido |
|---|---|
| `pytest_114_cobertura.txt` | Salida de pytest (114/114), cobertura, Ruff y radon de la versión de 114 pruebas |
| `cobertura_114.json` | Cobertura detallada de la versión de 114 pruebas |
| `cobertura_62_version_anterior.json` | Cobertura de la versión anterior (62 pruebas) |
| `bench_sweep.json`, `corridas.txt` | Barrido y corridas individuales del benchmark |
| `metrics_entrenamiento.json` | Salida del entrenamiento reproducido |
| `manifiesto_poc_sha256.txt` | Huella SHA-256 de cada archivo de la PoC analizada |
