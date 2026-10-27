# Imagen del CAMINO FRÍO (entrenamiento causal + worker de explicación/auditoría).
# Contexto de build: la raíz de poc/vox-causal
#   docker build -f services/batch_pipeline/Dockerfile -t vox-batch .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY libs/voxfeatures /tmp/voxfeatures
COPY services/batch_pipeline/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt /tmp/voxfeatures && rm -rf /tmp/voxfeatures

COPY services/batch_pipeline/pipeline ./pipeline
# Cliente de carga para medir latencia DENTRO de la región (job de benchmark).
COPY bench/__init__.py bench/ws_load.py ./bench/
RUN useradd --uid 10002 --no-create-home batchuser && mkdir -p /srv/var /srv/registry && chown -R batchuser /srv
USER batchuser

# JOB_MODE=worker (por defecto) | train | bench  — ver pipeline/entry.py
CMD ["python", "-m", "pipeline.entry"]
