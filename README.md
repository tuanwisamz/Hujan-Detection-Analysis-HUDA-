# HUDA — Hujan Detection Analysis

Township-level flood-rain warnings for Sime Darby Property communities in Peninsular Malaysia: live radar, a 60-minute nowcast, a GREEN / AMBER / RED level per township, and bilingual Telegram alerts.

Docs: [spec](docs/spec.md) · [architecture](docs/architecture.md) · [API](docs/api-spec.md) · [implementation plan + build status](docs/implementation-plan.md) · [task plan](docs/task.md)

## Run it

**Frontend only, no keys needed** (in-memory mock API, real RainViewer radar):

```bash
cd client
npm install
cp .env.example .env.local   # VITE_USE_MOCKS=true
npm run dev                  # http://localhost:5173 — switch user/admin role in the sidebar
```

**Backend:**

```bash
cd server
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # pysteps needs a C compiler; optional locally
cp .env.example .env                                          # Supabase, Clerk, Gemini, Telegram keys
.venv/Scripts/uvicorn app.main:app --reload --port 7860       # docs at /api/v1/docs
.venv/Scripts/pytest -q
```

Then set `VITE_USE_MOCKS=false`, `VITE_CLERK_PUBLISHABLE_KEY` and `VITE_API_BASE_URL` in `client/.env.local`.

**Database:** run `supabase/migrations/*.sql` in order, then `supabase/seed_zones.sql`, in the Supabase SQL editor.

**Demo storm:** `POST /api/v1/internal/ingest` with `{"fixture": "synthetic"}` and the `X-Cron-Secret` header turns City of Elmina RED and sends a Telegram alert. See [server/README.md](server/README.md).

## Layout

```
client/     React 19 + Vite + Tailwind v4 + react-leaflet
server/     FastAPI pipeline, API and Gemini agents (Hugging Face Space)
ml/         Classifier training notebook (Colab) and exported model
supabase/   Schema, pg_cron jobs, zone seed
docs/       Spec, architecture, API, plans
```
