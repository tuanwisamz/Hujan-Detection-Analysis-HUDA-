"""Replay archived storms under the old and new RED rules (implementation-plan-v2 D16).

    python -m scripts.replay_red            # synthetic storm + every storm in radar-archive
    python -m scripts.replay_red --limit 20 # only the 20 most recent archived storms

Reads Supabase Storage (service key from .env); writes nothing. Weather, MET warnings and
sensors are left out, so the counts isolate the radar rules.
"""

import argparse
from datetime import datetime, timezone

from app import repo
from app.models import AppSettings, Thresholds
from app.services import nowcast, storage, synthetic
from app.services.pipeline import compute_zone_results


def old_rule_red(result: dict, th: Thresholds) -> bool:
    """The rule before v2: any pixel >= red_rate_mmh at any step."""
    rate = result["explanation"]["inputs"]["rain_rate_max"]
    return rate is not None and rate >= th.red_rate_mmh


def replay(name: str, observed, zones: list[dict], settings: AppSettings) -> tuple[int, int]:
    forecast, _ = nowcast.nowcast(observed)
    results = compute_zone_results(zones, observed, forecast, {}, {}, {}, settings, observed[-1].ts)
    old = [r for r in results.values() if old_rule_red(r, settings.thresholds)]
    new = [r for r in results.values() if r["level"] == "RED"]
    names = {z["id"]: z["name"] for z in zones}
    detail = ", ".join(f"{names[r['zone_id']]} ({r['explanation']['rule']})" for r in new) or "-"
    print(f"{name:<22} old RED {len(old):>2}  new RED {len(new):>2}  {detail}")
    return len(old), len(new)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    settings = repo.get_app_settings()
    zones = repo.list_zones()
    totals = [replay("synthetic", synthetic.storm_grids(datetime(2026, 10, 18, 6, 40, tzinfo=timezone.utc)),
                     zones, settings)]
    files = sorted(f["name"] for f in storage.sb().storage.from_(storage.ARCHIVE_BUCKET).list("", {"limit": 1000})
                   if f["name"].endswith(".npz"))
    for name in files[-args.limit:] if args.limit else files:
        ts = datetime.strptime(name, "%Y%m%dT%H%MZ.npz").replace(tzinfo=timezone.utc)
        grids = storage.load_archived(ts, tolerance_min=1)
        if grids and len(grids) >= 2:
            totals.append(replay(name, grids, zones, settings))
    print(f"\n{len(totals)} storms · old RED zone-runs {sum(o for o, _ in totals)} · "
          f"new RED zone-runs {sum(n for _, n in totals)}")


if __name__ == "__main__":
    main()
