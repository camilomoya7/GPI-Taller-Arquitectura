# Imagen del CAMINO CALIENTE (API de inferencia en tiempo real).
# Contexto de build: la raíz de poc/vox-causal
#   docker build -f services/inference_api/Dockerfile -t vox-inference-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY libs/voxfeatures /tmp/voxfeatures
COPY services/inference_api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt /tmp/voxfeatures && rm -rf /tmp/voxfeatures

COPY services/inference_api/app ./app
# Único contrato con el camino frío: el artefacto aprobado y su huella SHA-256.
COPY services/inference_api/model/model.json services/inference_api/model/model.json.sha256 ./model/

RUN useradd --uid 10001 --no-create-home appuser && mkdir -p /srv/var && chown appuser /srv/var
USER appuser

ENV MODEL_PATH=/srv/model/model.json \
    STRICT_MODEL=true \
    DATA_REGION=uksouth
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"
# Un proceso por réplica: se escala horizontalmente (réplicas) según conexiones concurrentes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--loop", "uvloop", "--http", "httptools"]
