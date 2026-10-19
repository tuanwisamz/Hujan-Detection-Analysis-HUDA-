# AGENTS.md — working on HUDA

Read these first, in order: `docs/spec.md` → `docs/architecture.md` → `docs/api-spec.md` → `docs/implementation-plan.md` (build order, decisions D1–D12) → `docs/task.md` (schedule).

## Layout

| Path        | What                                                       | Run                                                         |
| ----------- | ---------------------------------------------------------- | ----------------------------------------------------------- |
| `client/`   | React 19 + Vite + Tailwind v4 (JavaScript, no TypeScript)  | `npm run dev` · `npm run lint` · `npm run build`            |
| `server/`   | FastAPI, Python 3.11                                       | `uvicorn app.main:app --reload --port 7860` · `pytest`      |
| `ml/`       | Classifier training (Colab notebook) + exported model      | Open the notebook in Colab                                  |
| `supabase/` | SQL migrations, zone seed, pg_cron jobs                    | Paste into the Supabase SQL editor in file order            |

## Rules

- **The LLM never sets a risk level.** Levels come only from `server/app/services/risk.py`. Nothing in `server/app/agents/` may import `risk.py` or write `predictions.level` (a test enforces this).
- Keep `palette`, `zone_stats`, `risk` and `alerts.decide` pure: plain inputs, plain outputs, no DB or HTTP.
- Feature code lives once, in `server/app/services/features.py`. The notebook uses the same file.
- Every risk level shown in the UI goes through `client/src/lib/levels.js` / `<RiskBadge>`: colour + icon + text, never colour alone.
- User-visible strings go through `client/src/lib/i18n.js` (EN + BM).
- Secrets live in env vars only. The HF Space repo is public.
- API errors use the envelope `{ "error": { "code", "message", "request_id" } }`.
