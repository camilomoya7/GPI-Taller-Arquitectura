# /docs/erv — Informe ERV Vox-Causal AI (Alloxentric SpA) · Entrega Parte 3

Grupo N.º 1 · Sección 411 · GPI 2026-II · Docente: Dr. Oscar Eduardo Magna Veloso

Caso de estudio independiente del proyecto TryAIGap: la prueba de concepto vive aislada en `/poc/vox-causal`
y no comparte código, datos ni cronograma con la aplicación TryAIGap.

## Entregables

| Entregable | Archivo |
|---|---|
| Informe ERV final (14 páginas, 8 capítulos) | `Informe_ERV_Alloxentric_VoxCausal_FINAL.docx` / `.pdf` |
| Presentación ejecutiva (10 diapositivas, 12 min) | `Presentacion_ERV_Alloxentric_VoxCausal_FINAL.pptx` |
| Modelo financiero único (fórmulas vivas, 0 errores) | `Modelo_Financiero_ERV_Alloxentric_VoxCausal.xlsx` |
| Diagramas C4 (N1–N3), pipeline, EVM y finanzas | `diagramas/` |
| Evidencia de reproducción de la PoC (114 pruebas) | `evidencia/REPRODUCCION.md` |
| Fuente del modelo financiero y datos EVM | `modelo_financiero/` |

## Cifras oficiales (escenario Base, GBP, 36 meses, tasa 12 %)

CAPEX £64.533 (800 HH × £73,33 + 10 % de reserva) · OPEX estable £3.164/mes · VAN £174.125 ·
TIR anual 160,4 % · payback 15,5 meses · B/C 2,17. Las mismas cifras están en el informe, la presentación y el Excel.

> `poc/vox-causal/erv/` contiene el modelo financiero y el EVM de la **Parte 2** (VAN £375.780), conservados
> sin cambios como parte de la versión exacta de la PoC analizada. **No son las cifras oficiales de la Parte 3**:
> el modelo unificado (tabla 6.1 del informe) reemplaza sus supuestos de precios, tarifa, tasa y demanda.
> El EVM del proyecto de integración (AC simulado) se toma de `poc/vox-causal/erv/out/evm.json`.

## Estado verificado

| Afirmación | Estado |
|---|---|
| 114 pruebas, cobertura 96 %, Ruff 0, complejidad A (2,66), 51/51 afirmaciones de diagramas | Reproducido localmente |
| Error ATE ≤ 0,05 (datos sintéticos de efecto conocido) | Reproducido localmente |
| Latencia de servidor p95 2,9 ms; extremo a extremo con 100 llamadas por réplica p95 31–32 ms | Reproducido localmente (Windows, 1 núcleo) |
| 180 llamadas por réplica con p95 23,1 ms | Documentado por el equipo; no reproducido de forma estable |
| 1.500 llamadas concurrentes | Sin verificar (dimensionamiento de 10 réplicas, sin prueba) |
| Despliegue y verificación en Azure (`deploy.sh`, `verify.sh`) | Configurado; no ejecutado |
| Workflow `.github/workflows/vox-causal-ci.yml` | Configurado; se ejecuta solo con cambios en `poc/vox-causal/**` |
