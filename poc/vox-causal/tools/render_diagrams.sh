#!/usr/bin/env bash
# Regenera la trazabilidad y todos los diagramas desde el código y los resultados medidos.
# Requiere: Graphviz (dot) para los C4 y Node.js + Playwright (Chromium) para el pipeline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python tools/architecture_claims.py      # falla si alguna afirmación del diagrama no se cumple
python tools/build_diagrams.py           # C4 N1, N2, N3 API, N3 batch
python tools/render_pipeline.py          # Pipeline MLOps e inferencia
