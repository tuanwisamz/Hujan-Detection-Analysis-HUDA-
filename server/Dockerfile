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
ENV MODEL_PATH=/app/models/lgbm_v1.txt \
    RADAR_CACHE_DIR=/tmp/huda_radar \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers"]
