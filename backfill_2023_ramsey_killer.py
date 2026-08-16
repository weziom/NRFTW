#!/usr/bin/env python3
"""Backfill the Ramsey 10K and Killer Mile legs into the already-built
2023.json (from build_2020_2023_results.py), which had both marked
'unavailable' since the club's own season-tracking spreadsheet only ever
had Half Marathon + Peel Hill for 2023.

Sources:
  - Ramsey 10K: raceresult event 255883 (https://my.raceresult.com/255883/),
    "No Rest For the Wicked 10k", 2023-08-15.
  - Killer Mile: the club's official results PDF (results/killer_mile_2023.pdf),
    transcribed into killer_mile_2023_data.py.

Only backfills entrants already on the 2023 series roster (the existing
half_marathon/marathon leagues) - most rows in both sources are one-off
local/junior runners who never ran Half Marathon or Peel Hill and so were
never part of the series, which is expected and not logged as an anomaly
(same convention as build_historic_results.py's Marathon/Half + 10K
backfill for other years).
"""

import json
from pathlib import Path

from killer_mile_2023_data import KILLER_MILE_2023
from pull_results import (
    fetch_10k_race, match_by_full_name, normalize_name, parse_time_to_seconds,
    resolve_alias, seconds_to_hms, write_league_pdf,
)

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "2023.json"
ANOMALIES_PATH = BASE_DIR / "anomalies" / "2023.txt"

RAMSEY_EVENT_ID = 255883
RAMSEY_SOURCE_URL = f"https://my.raceresult.com/{RAMSEY_EVENT_ID}/"
KILLER_MILE_SOURCE_URL = (
    "https://static1.squarespace.com/static/50c834e5e4b0a53fd189c25c/t/"
    "64de49da24e05d1f3c65c484/1692289498487/Killer+Mile+2023+-+Results+v3.pdf"
)


def build_killer_mile_entries():
    entries = []
    for position, first, surname, time, category, club in KILLER_MILE_2023:
        name = f"{first} {surname}"
        entries.append({
            "position": position,
            "name": name,
            "category": category,
            "club": club,
            "time": time,
            "seconds": parse_time_to_seconds(time),
            "key": normalize_name(resolve_alias(name)),
        })
    return entries


def main():
    data = json.loads(JSON_PATH.read_text())
    all_entrants = [e for lg in ("half_marathon", "marathon") for e in data["leagues"][lg]]

    roster = [{
        "key": normalize_name(resolve_alias(e["name"])),
        "name": e["name"],
        "club": e["club"],
        "category": None,
    } for e in all_entrants]

    print(f"Fetching Ramsey 10K from raceresult event {RAMSEY_EVENT_ID}...")
    ramsey_entries = fetch_10k_race(event_id=RAMSEY_EVENT_ID, use_cache=True)
    ramsey_matched, ramsey_anomalies = match_by_full_name(roster, ramsey_entries, "Ramsey 10K (raceresult 2023)")

    print("Loading Killer Mile 2023 (transcribed from results PDF)...")
    killer_entries = build_killer_mile_entries()
    killer_matched, killer_anomalies = match_by_full_name(roster, killer_entries, "Killer Mile (2023 results PDF)")

    # Most people in either source were never on the series roster at all
    # (one-off local/junior entrants) - "no_result" there just means "not
    # in this race source", not a data-quality problem.
    anomalies = [a for a in ramsey_anomalies + killer_anomalies if a["type"] != "no_result"]

    for e in all_entrants:
        key = normalize_name(resolve_alias(e["name"]))
        ramsey = ramsey_matched.get(key)
        killer = killer_matched.get(key)
        if ramsey:
            e["races"]["ramsey_10k"] = {
                "position": ramsey["position"], "time": seconds_to_hms(ramsey["seconds"]), "category": ramsey["category"],
            }
        if killer:
            e["races"]["killer_mile"] = {
                "position": killer["position"], "time": seconds_to_hms(killer["seconds"]), "category": killer["category"],
            }

        cumulative_seconds = 0
        completed = 0
        for r in e["races"].values():
            if r and r.get("time"):
                cumulative_seconds += parse_time_to_seconds(r["time"])
                completed += 1
        e["cumulative_seconds"] = cumulative_seconds
        e["cumulative_time"] = seconds_to_hms(cumulative_seconds)
        e["races_completed"] = completed

    data["leagues"]["half_marathon"].sort(key=lambda e: e["cumulative_seconds"])
    data["leagues"]["marathon"].sort(key=lambda e: e["cumulative_seconds"])

    data["races"]["ramsey_10k"]["status"] = "complete"
    data["races"]["ramsey_10k"]["source"] = RAMSEY_SOURCE_URL
    data["races"]["ramsey_10k"]["finishers"] = len(ramsey_entries)

    data["races"]["killer_mile"]["status"] = "complete"
    data["races"]["killer_mile"]["source"] = KILLER_MILE_SOURCE_URL
    data["races"]["killer_mile"]["finishers"] = len(killer_entries)

    league_pdfs = {}
    for league_key in ("half_marathon", "marathon"):
        entrants_list = data["leagues"][league_key]
        if not entrants_list:
            continue
        filename = f"{league_key}_2023.pdf"
        write_league_pdf(league_key, entrants_list, data["races"], event_name=data["event"], filename=filename)
        league_pdfs[league_key] = f"pdfs/{filename}"
    data["league_pdfs"] = league_pdfs
    JSON_PATH.write_text(json.dumps(data, indent=2))

    ramsey_backfilled = sum(1 for e in all_entrants if ramsey_matched.get(normalize_name(resolve_alias(e["name"]))))
    killer_backfilled = sum(1 for e in all_entrants if killer_matched.get(normalize_name(resolve_alias(e["name"]))))
    print(f"Ramsey 10K backfilled for {ramsey_backfilled}/{len(all_entrants)} series entrants")
    print(f"Killer Mile backfilled for {killer_backfilled}/{len(all_entrants)} series entrants")
    print(f"Anomalies flagged: {len(anomalies)}")
    for a in anomalies:
        print(f"  [{a['type']}] {a['detail']}")

    with open(ANOMALIES_PATH, "a") as f:
        f.write(
            "\n[ramsey_10k_killer_mile_backfill] Ramsey 10K and Killer Mile backfilled "
            f"after the fact from independent sources ({RAMSEY_SOURCE_URL}, results/killer_mile_2023.pdf) "
            "and matched onto the existing Half Marathon/Peel Hill roster by name - most entrants in "
            "both sources were one-off local/junior runners never on the series roster, not logged here. "
            f"Ramsey 10K matched {ramsey_backfilled}/{len(all_entrants)} roster entrants; "
            f"Killer Mile matched {killer_backfilled}/{len(all_entrants)}. Foxdale 5 and Trail Run "
            "still have no source for 2023 and remain unavailable.\n"
        )
        for a in anomalies:
            f.write(f"[{a['type']}] {a['detail']}\n")


if __name__ == "__main__":
    main()
