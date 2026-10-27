"""Seed JPS stations for the zone states (architecture.md §3.2, implementation-plan-v2 D21). Re-runnable.

    python -m scripts.seed_sensors          # write to sensor_stations
    python -m scripts.seed_sensors --dry    # print what would change

Stations come from the 4 InfoBanjir rain and river pages. Coordinates: data.gov.my's
station list where the JPS ID or the station name matches (exact, 'verified'), otherwise the 0.1° cell the ID
encodes ('grid'). Stations an admin already placed are never moved.
Needs supabase/migrations/0004_additional.sql.
"""

import argparse
from collections import Counter

from app import repo
from app.services import ingest_sensors
from app.services.pipeline import station_row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    readings, pages = ingest_sensors.fetch_all()
    print("pages:", pages)
    official = ingest_sensors.official_coords()
    rows = {}
    for r in readings:
        row = station_row(r)
        exact = (official.get(r["station_id"].strip("_"))
                 or official.get(ingest_sensors.name_key(r.get("name"), r.get("state"))))
        if exact:
            row |= {"lat": exact[0], "lon": exact[1], "location_quality": "verified", "location_source": "datagovmy"}
        rows[row["id"]] = row
    existing = {s["id"]: s for s in repo.list_stations()}
    new = [r for sid, r in rows.items() if sid not in existing]
    upgrade = [r for sid, r in rows.items() if sid in existing and r["location_source"] == "datagovmy"
               and existing[sid]["location_quality"] == "grid"]
    print(f"{len(rows)} stations seen · {len(new)} new · {len(upgrade)} get exact coordinates")
    print("by kind/quality:", Counter((r["kind"], r["location_quality"]) for r in rows.values()))
    print("no location at all:", sum(1 for r in rows.values() if r["lat"] is None))
    if args.dry:
        return
    repo.add_stations(new)
    for r in upgrade:
        repo.update_station(r["id"], {k: r[k] for k in ("lat", "lon", "location_quality", "location_source")})
    print("done")


if __name__ == "__main__":
    main()
