"""LightGBM flood-rain classifier (spec FR-11/FR-12).

Top-3 contributions use LightGBM's built-in SHAP values (`pred_contrib=True`),
so the `shap` package isn't needed at serve time. If the model file is missing,
predict() returns None and the risk engine runs on rules only (cut-list item 4).
"""

import json
import logging
import math
from pathlib import Path

import numpy as np

from ..config import get_settings
from .features import FEATURE_NAMES

log = logging.getLogger("huda")

_model = None
_meta: dict = {}


def load(path: Path | None = None) -> bool:
    global _model, _meta
    path = Path(path or get_settings().model_path)
    if not path.exists():
        log.warning("classifier model not found at %s; running rules-only", path)
        _model, _meta = None, {}
        return False
    import lightgbm as lgb

    _model = lgb.Booster(model_file=str(path))
    meta_path = path.with_name("features.json")
    _meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"features": FEATURE_NAMES}
    _meta.setdefault("version", path.stem)
    log.info("loaded classifier %s", _meta["version"])
    return True


def model_version() -> str | None:
    return _meta.get("version") if _model is not None else None


def forecast_model() -> str | None:
    """Open-Meteo model the forecast-precipitation features must come from (D3)."""
    return _meta.get("forecast_model") if _model is not None else None


def predict(features: dict[str, float]) -> tuple[float | None, list[list]]:
    """(p_ml, top3) where top3 = [[feature, contribution], ...] by |contribution|."""
    if _model is None:
        return None, []
    names = _meta.get("features", FEATURE_NAMES)
    x = np.array([[features.get(n, math.nan) for n in names]], dtype=np.float64)
    p = float(_model.predict(x)[0])
    contrib = _model.predict(x, pred_contrib=True)[0][:-1]  # last column is the bias
    order = np.argsort(-np.abs(contrib))[:3]
    return round(p, 3), [[names[i], round(float(contrib[i]), 3)] for i in order]
