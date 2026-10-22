# HUDA — ML

`notebooks/train_classifier.ipynb` trains the flood-rain classifier and writes `models/lgbm_v1.txt` + `models/features.json`.

## Run in Colab

1. Open the notebook in Colab, then in the first code cell set `HUDA_REPO` (or `!git clone <repo> /content/huda`).
2. Run all. Downloads are cached in `ml/data/` (git-ignored); the full 15-zone pull takes a while and uses roughly half of Open-Meteo's free daily quota.
3. Read the **positive rate** printout (step 4) before trusting any metric, and record the label threshold you settle on in `docs/architecture.md` §5.2.
4. Commit `models/lgbm_v1.txt` and `models/features.json`, copy them into `server/models/`, then redeploy the Space.
5. Put the printed `amber_p` / `red_p` cut-offs into Admin → Settings.

## Two things the smoke test found (18 Oct 2026)

A 2-zone, 2023–2025 trial run of this notebook showed:

- **Forecast features must not come from ECMWF.** From 2017 the Open-Meteo Archive *is* the stitched ECMWF IFS forecast, so `ecmwf_ifs`/`best_match` historical forecasts are byte-identical to the label series (ROC-AUC 1.0 = leakage). The notebook uses **GFS** (`gfs_seamless`, archived from ~2021-03) and asserts the two series differ. The backend fetches the same model live (`features.json` → `forecast_model`).
- **30 mm/3 h is very rare in this data**: 0.06 % of hours at City of Elmina (20 mm/3 h: 0.43 %). Expect to lower the label threshold.
- With honest features, the trial gave **test ROC-AUC 0.63**. The full run has more zones but training only starts in 2021 (GFS coverage), so the 0.75 target in spec §11 is at risk. If it isn't reached, report the real number; the cut list's rules-only fallback still works.

## Full run (23 Oct 2026) — `lgbm_v1`

Run locally (same notebook cells) on all 15 zones, 2016–2025 Archive + GFS forecast features.

| | |
| --- | --- |
| Label | **≥ 20 mm in the next 3 h.** 30 mm was 0.07 % of hours (914 positives over 1.31 M); 20 mm is 0.29 % |
| Leakage guard | GFS forecast equals the Archive on 48.7 % of hours (mostly dry hours); the guard fails at 80 % |
| Split | train 2021-04 → 2022 (230 k rows, 557 positives) · valid 2023 (131 k, 443) · test 2024–25 (263 k, 1,366) |
| Validation | ROC-AUC 0.732 · PR-AUC 0.037 |
| **Test** | **ROC-AUC 0.706** · PR-AUC 0.026 (base rate 0.52 %) · Brier 0.020 |
| Cut-offs | `amber_p` **0.612** (top 2 % of zone-hours: precision ~5 %, recall 16–29 %) · `red_p` **0.93** (top 0.3 %: precision ~10 %, recall 4–9 %) |

The 0.75 target is not met. No threshold reaches 50 % precision, so the notebook now caps how often each level fires instead of chasing precision (its old rule returned amber 0.0 / red 0.999). Because the model is weak on its own, an ML-only RED needs a JPS sensor to agree (implementation-plan-v2 D18), and the live Settings must use these cut-offs: the old 0.40 / 0.70 would flag 3.3 % / 1.5 % of zone-hours.
