---
title: HUDA API
emoji: 🌧️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# HUDA API (FastAPI)

Backend for HUDA — Hujan Detection Analysis. See `docs/` in the main repo.

## Local development

```bash
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # pysteps needs a C compiler; optional locally
cp .env.example .env                                          # fill in keys
.venv/Scripts/uvicorn app.main:app --reload --port 7860
.venv/Scripts/pytest -q
```

API docs: http://localhost:7860/api/v1/docs

## Trigger a run by hand

```bash
# live run
curl -X POST localhost:7860/api/v1/internal/ingest -H "X-Cron-Secret: $CRON_SECRET"
# demo: synthetic storm over City of Elmina (turns it RED)
curl -X POST localhost:7860/api/v1/internal/ingest -H "X-Cron-Secret: $CRON_SECRET" \
     -H "Content-Type: application/json" -d '{"fixture": "synthetic"}'
```

Set `pipeline_enabled=false` in Admin → Settings during the demo so the next live run doesn't overwrite the replay.

## Deploy to the Hugging Face Space

Copy the trained model in first (`models/` is part of the image), then push this folder:

```bash
mkdir -p server/models && cp ml/models/lgbm_v1.txt ml/models/features.json server/models/
git subtree push --prefix server space main
```

Without a model file the API runs rules-only (`model_version: "rules_only"`).
Secrets go in the Space settings, never in this repo (the Space is public).
