"""Failure drills (task.md Day 3, implementation-plan §6): a source down -> degraded badge;
Gemini 429 -> template. FAULT_INJECT names the sources to break."""

from types import SimpleNamespace

import pytest

from app import config
from app.agents import alert_writer, gemini_client
from app.api.live import _data_status
from app.services import ingest_weather
from app.services.pipeline import _status

EVENT = {"zone": "City of Elmina", "level": "RED", "eta_min": 20, "rain_rate_max": 38.4}


def inject(monkeypatch, faults: str):
    real = config.get_settings()
    fake = SimpleNamespace(**{k: getattr(real, k) for k in type(real).model_fields})
    fake.fault_inject, fake.gemini_api_key = faults, "test-key"
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    monkeypatch.setattr(gemini_client, "get_settings", lambda: fake)


def test_gemini_down_falls_back_to_template(monkeypatch):
    inject(monkeypatch, "gemini")
    assert alert_writer.write_alerts([EVENT]) == [None]  # None = render the Jinja template


def test_open_meteo_down_marks_run_and_badge_degraded(monkeypatch):
    inject(monkeypatch, "open_meteo")
    with pytest.raises(config.InjectedFault):
        ingest_weather.fetch_open_meteo([{"id": "z1", "lat": 3.18, "lon": 101.49}])
    sources = {"radar": "ok", "nowcast": "ok", "met_warnings": "ok", "open_meteo": "failed"}
    assert _status(sources) == "degraded"
    assert _data_status({"sources": sources})["open_meteo"] == "degraded"


@pytest.mark.parametrize("source", ["radar", "met_warnings"])
def test_any_core_source_down_degrades(source):
    sources = {"radar": "ok", "nowcast": "ok", "met_warnings": "ok", "open_meteo": "ok", source: "failed"}
    assert _status(sources) == "degraded" and _data_status({"sources": sources})[source] == "degraded"
