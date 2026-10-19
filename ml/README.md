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
