"""Agent guardrails (spec §6.4) and Alert Writer validation."""

import ast
from datetime import datetime, timezone
from pathlib import Path

from app.agents import alert_writer, report_analyst, tools
from app.auth import User

AGENTS_DIR = Path(__file__).resolve().parent.parent / "app" / "agents"


def test_agents_never_import_risk_engine():
    for path in AGENTS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
                assert not ((node.module or "").endswith("risk") or "risk" in names), path.name
            if isinstance(node, ast.Import):
                assert not any(a.name.endswith("risk") for a in node.names), path.name


def test_agents_never_write_predictions():
    for path in AGENTS_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "insert_predictions" not in src and 'table("predictions")' not in src, path.name


def test_draft_warning_is_admin_only():
    user, admin = User("u1", "user"), User("a1", "admin")
    assert "draft_warning" not in tools.available(user)
    assert "draft_warning" in tools.available(admin)
    assert "error" in tools.call(user, "draft_warning", {"zone": "elmina", "level": "RED"})


EVENT = {"zone": "City of Elmina", "district": "Petaling", "level": "RED", "rain_rate_mmh": 38, "eta_min": 20,
         "ml_probability_3h": None}


def test_writer_accepts_grounded_text():
    assert alert_writer.valid(EVENT, {"message_en": "Intense rain (~38 mm/h) in ~20 min. Avoid underpasses.",
                                      "message_ms": "Hujan lebat (~38 mm/j) dalam ~20 minit. Elakkan terowong."})


def test_writer_rejects_invented_numbers_and_long_text():
    assert not alert_writer.valid(EVENT, {"message_en": "Rain of 80 mm/h in 20 min.", "message_ms": "Hujan 38."})
    assert not alert_writer.valid(EVENT, {"message_en": "x" * 300, "message_ms": "ok"})
    assert not alert_writer.valid(EVENT, {"message_en": "", "message_ms": "ok"})


def test_writer_falls_back_without_gemini():
    assert alert_writer.write_alerts([EVENT]) == [None]  # no GEMINI_API_KEY in tests -> template


def test_report_stats_are_computed_not_generated():
    zones = [{"id": "a", "name": "Elmina"}, {"id": "b", "name": "Denai Alam"}]
    preds = [{"zone_id": "a", "level": "RED", "rain_rate_max": 38.4, "p_ml": 0.8},
             {"zone_id": "a", "level": "AMBER", "rain_rate_max": 12.0, "p_ml": 0.5},
             {"zone_id": "b", "level": "GREEN", "rain_rate_max": 0.0, "p_ml": 0.1}]
    warns = [{"zone_id": "a", "level": "RED", "sent_at": "2026-10-18T06:40:00+00:00"}]
    stats = report_analyst.compute_stats(zones, preds, warns)
    top = stats["rows"][0]
    assert top["zone"] == "Elmina" and top["red_runs"] == 1 and top["amber_runs"] == 1
    assert top["peak_rain_rate_mmh"] == 38.4 and top["alerts_sent"] == 1
    assert stats["totals"] == {"alerts_sent": 1, "red_alerts": 1, "zones_with_red": 1}
    md = report_analyst.to_markdown("HUDA Report", datetime(2026, 10, 17, tzinfo=timezone.utc),
                                    datetime(2026, 10, 18, tzinfo=timezone.utc), stats, None)
    assert "| Elmina | 2 | 1 | 1 | 1 | 38.4 | 0.8 |" in md
    assert report_analyst.to_csv(stats).splitlines()[0] == ",".join(report_analyst.CSV_FIELDS)
