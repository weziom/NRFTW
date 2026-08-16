#!/usr/bin/env python3
"""Backfill the Foxdale 5 leg into the already-built 2023.json (which had
it marked 'unavailable' since the club's own season-tracking spreadsheet
only ever had Half Marathon + Peel Hill for 2023, later joined by Ramsey
10K and Killer Mile via backfill_2023_ramsey_killer.py).

Source: the club's official results PDF (results/FOXDALE 5 2023 RESULTS.pdf),
transcribed into foxdale5_2023_data.py. Its time column is "MM.SS" (period,
not colon) - parsed by parse_foxdale_time() below, distinct from every
other race's HH:MM:SS.

Only backfills entrants already on the 2023 series roster - most rows in
the source are one-off local runners who never ran Half Marathon or Peel
Hill and so were never part of the series (expected, not an anomaly).
"""

import json
import re
from pathlib import Path

from foxdale5_2023_data import FOXDALE5_2023
from pull_results import (
    match_by_full_name, normalize_name, parse_time_to_seconds, resolve_alias,
    seconds_to_hms, write_league_pdf,
)

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "2023.json"
ANOMALIES_PATH = BASE_DIR / "anomalies" / "2023.txt"
FOXDALE_SOURCE = "results/FOXDALE 5 2023 RESULTS.pdf (club results PDF)"


def parse_foxdale_time(text):
    m = re.match(r"^(\d+)\.(\d{2})$", text.strip())
    if not m:
        return None
    minutes, seconds = map(int, m.groups())
    return minutes * 60 + seconds


def build_foxdale_entries():
    entries = []
    for position, first, surname, club, category, time_text in FOXDALE5_2023:
        name = f"{first} {surname}"
        entries.append({
            "position": position,
            "name": name,
            "category": category,
            "club": club,
            "time": time_text,
            "seconds": parse_foxdale_time(time_text),
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

    print("Loading Foxdale 5 2023 (transcribed from results PDF)...")
    foxdale_entries = build_foxdale_entries()
    foxdale_matched, foxdale_anomalies = match_by_full_name(roster, foxdale_entries, "Foxdale 5 (2023 results PDF)")
    anomalies = [a for a in foxdale_anomalies if a["type"] != "no_result"]

    for e in all_entrants:
        key = normalize_name(resolve_alias(e["name"]))
        foxdale = foxdale_matched.get(key)
        if foxdale and foxdale["seconds"] is not None:
            e["races"]["foxdale_5"] = {
                "position": foxdale["position"], "time": seconds_to_hms(foxdale["seconds"]), "category": foxdale["category"],
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

    data["races"]["foxdale_5"]["status"] = "complete"
    data["races"]["foxdale_5"]["source"] = FOXDALE_SOURCE
    data["races"]["foxdale_5"]["finishers"] = len(foxdale_entries)

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

    backfilled = sum(1 for e in all_entrants if foxdale_matched.get(normalize_name(resolve_alias(e["name"]))))
    print(f"Foxdale 5 backfilled for {backfilled}/{len(all_entrants)} series entrants")
    print(f"Anomalies flagged: {len(anomalies)}")
    for a in anomalies:
        print(f"  [{a['type']}] {a['detail']}")

    with open(ANOMALIES_PATH, "a") as f:
        f.write(
            "\n[foxdale5_backfill] Foxdale 5 backfilled from the club's official results PDF "
            f"({FOXDALE_SOURCE}) and matched onto the existing series roster by name - most entrants "
            "in that source were one-off local runners never on the series roster, not logged here. "
            f"Matched {backfilled}/{len(all_entrants)} roster entrants. The source PDF's row 75 prints "
            "the name as 'Marek Orgalewski' - clearly a typo/OCR error for 'Marek Rogalewski' (who "
            "ran every other 2023 race and every other year under that spelling) - corrected during "
            "transcription so it matches. Trail Run still has no 2023 source and remains unavailable.\n"
        )
        for a in anomalies:
            f.write(f"[{a['type']}] {a['detail']}\n")


if __name__ == "__main__":
    main()
