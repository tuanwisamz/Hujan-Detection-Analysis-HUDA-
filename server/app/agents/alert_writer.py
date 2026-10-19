"""Alert Writer (spec FR-20): level-change events -> bilingual EN/BM alert text.

Structured input only (no tools). The model writes text; it never chooses the
level. Output is rejected — and the Jinja template used instead — if it is too
long or mentions numbers that aren't in the input.
"""

import json
import logging
import re

from ..config import get_settings
from .gemini_client import GeminiUnavailable, generate_json

log = logging.getLogger("huda")

MAX_LANG_CHARS = 250  # leaves room for header + footer within the 600-char message (D6)

SYSTEM = """You write short flood-rain alerts for residents of Malaysian townships.
For each event, write one English message (message_en) and one Bahasa Melayu message (message_ms).
Rules:
- Each message at most 250 characters, plain text, no emoji, no markdown.
- State the expected intensity and ETA exactly as given (mm/h; "mm/j" in BM; minutes).
- End with ONE clear recommended action.
- Use only the numbers provided. Never invent data. Never change or restate a different level.
Return a JSON array with one object per event, in the same order."""

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"message_en": {"type": "string"}, "message_ms": {"type": "string"}},
        "required": ["message_en", "message_ms"],
    },
}


def event(zone: dict, level: str, prediction: dict | None) -> dict:
    p = prediction or {}
    rate = p.get("rain_rate_max")
    return {
        "zone": zone["name"], "district": zone.get("district"), "level": level,
        "rain_rate_mmh": round(rate) if rate is not None else None,
        "eta_min": p.get("eta_min"),
        "ml_probability_3h": p.get("p_ml"),
    }


def _allowed_numbers(ev: dict) -> set[str]:
    nums = {"3"}  # "next 3 h" is standard wording
    for v in (ev.get("rain_rate_mmh"), ev.get("eta_min")):
        if v is not None:
            nums.add(str(int(v)))
    if ev.get("ml_probability_3h") is not None:
        nums.add(str(round(ev["ml_probability_3h"] * 100)))
    return nums


def valid(ev: dict, text: dict) -> bool:
    allowed = _allowed_numbers(ev)
    for lang in ("message_en", "message_ms"):
        msg = (text.get(lang) or "").strip()
        if not msg or len(msg) > MAX_LANG_CHARS:
            return False
        if any(n not in allowed for n in re.findall(r"\d+", msg)):
            return False
    return True


def write_alerts(events: list[dict]) -> list[dict | None]:
    """One call for all events. Returns {message_en, message_ms} or None (= use template) per event."""
    if not events:
        return []
    try:
        out = generate_json(json.dumps(events, ensure_ascii=False), system=SYSTEM, schema=SCHEMA,
                            model=get_settings().gemini_lite_model, agent="alert_writer")
    except GeminiUnavailable as exc:
        log.info("alert writer fallback to template: %s", exc)
        return [None] * len(events)
    if not isinstance(out, list) or len(out) != len(events):
        return [None] * len(events)
    return [{"message_en": t["message_en"].strip(), "message_ms": t["message_ms"].strip()}
            if isinstance(t, dict) and valid(ev, t) else None for ev, t in zip(events, out)]
