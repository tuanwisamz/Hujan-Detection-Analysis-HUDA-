# Hugging Face Space (Docker SDK). Build context = server/ (deployed with git subtree).
FROM python:3.11-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
# HF Spaces run containers as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --chown=user app ./app
COPY --chown=user models ./models
USER user
# MALLOC_ARENA_MAX: pipeline runs on worker threads; glibc's per-thread arenas
# otherwise keep freed numpy memory and grow until a 512 MB host is OOM-killed.
ENV MODEL_PATH=/app/models/lgbm_v1.txt \
    RADAR_CACHE_DIR=/tmp/huda_radar \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2
EXPOSE 7860
# Render sets $PORT; HF Spaces doesn't, so fall back to 7860.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*'"]
