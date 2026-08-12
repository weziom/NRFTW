#!/usr/bin/env python3
"""
One-off build of 2025.json, the archived 'Bell Burton No Rest For the Wicked
2025' results, from the two pre-merged season CSVs in results/:
  - 2025_half_marathon.csv (Half Marathon league, 91 runners)
  - 2025_marathon.csv (Marathon league, 12 runners)

Unlike pull_results.py, there's no per-race name-matching to do here - each
CSV row already has every race's time for that runner, transcribed from the
final 2025 leaderboard spreadsheets (results/2025_result_final.jpg and
results/2025_result_final_marathon.jpg). This script just parses times,
recomputes each runner's total from the individual race splits (so the
TOTAL column always matches what's shown, the same invariant the live
2026 pipeline maintains), and writes anomalies_2025.txt for anything that
didn't reconcile cleanly during transcription.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pull_results import parse_time_to_seconds, seconds_to_hms

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = BASE_DIR / "2025.json"
ANOMALIES_PATH = BASE_DIR / "anomalies_2025.txt"

RACE_LABELS = {
    "peel_hill": "Peel Hill",
    "marathon_half": "Marathon / Half Marathon",
    "ramsey_10k": "Ramsey 10K",
    "killer_mile": "Killer Mile",
    "foxdale_5": "Foxdale 5",
    "trail_run": "Trail",
}
RACE_ORDER = ["marathon_half", "peel_hill", "ramsey_10k", "killer_mile", "foxdale_5", "trail_run"]


def age_group_from_cat(cat):
    """'MSnr' -> 'Senior', 'M35-39' -> '35-39', 'F55-59' -> '55-59'."""
    if not cat:
        return None
    body = cat[1:] if cat[0] in "MF" else cat
    return "Senior" if body.lower() == "snr" else body


def build_entrant(row, league, contest, main_time_field, age_group, anomalies, source_label):
    seconds = {
        "peel_hill": parse_time_to_seconds(row["peel_hill"]),
        "marathon_half": parse_time_to_seconds(row[main_time_field]),
        "ramsey_10k": parse_time_to_seconds(row["ramsey_10k"]),
        "killer_mile": parse_time_to_seconds(row["killer_mile"]),
        "foxdale_5": parse_time_to_seconds(row["foxdale_5"]),
        "trail_run": parse_time_to_seconds(row["trail_run"]),
    }
    races = {
        "peel_hill": {"position": None, "time": seconds_to_hms(seconds["peel_hill"]), "category": None},
        "marathon_half": {
            "contest": contest,
            "bib": None,
            "rank": None,
            "time": seconds_to_hms(seconds["marathon_half"]),
            "category": age_group,
        },
        "ramsey_10k": {"position": None, "time": seconds_to_hms(seconds["ramsey_10k"]), "category": None},
        "killer_mile": {"position": None, "time": seconds_to_hms(seconds["killer_mile"]), "category": None},
        "foxdale_5": {"position": None, "time": seconds_to_hms(seconds["foxdale_5"]), "category": None},
        "trail_run": {"position": None, "time": seconds_to_hms(seconds["trail_run"]), "category": None},
    }

    cumulative_seconds = sum(seconds.values())
    printed_total = parse_time_to_seconds(row["total"])
    name = f"{row['first_name'].strip()} {row['surname'].strip()}"
    if printed_total is not None and printed_total != cumulative_seconds:
        anomalies.append({
            "type": "total_mismatch",
            "detail": (
                f"'{name}' ({source_label}, position {row['position']}): the original 2025 "
                f"spreadsheet's TOTAL ({seconds_to_hms(printed_total)}) doesn't match the sum of "
                f"the six race splits ({seconds_to_hms(cumulative_seconds)}). Showing the "
                "recomputed sum so it matches the race times displayed; verify against the "
                "original spreadsheet if available."
            ),
        })

    return {
        "name": name,
        "club": row["club"].strip(),
        "gender": row["gender"] or "Unknown",
        "age_group": age_group or "Unknown",
        "league": league,
        "races": races,
        "races_completed": sum(1 for v in races.values() if v and v.get("time")),
        "cumulative_seconds": cumulative_seconds,
        "cumulative_time": seconds_to_hms(cumulative_seconds),
    }


def load_half_marathon(anomalies):
    entrants = []
    with (RESULTS_DIR / "2025_half_marathon.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entrants.append(build_entrant(
                row, "half_marathon", "half_marathon", "half", None, anomalies, "Half Marathon"
            ))
    return entrants


def load_marathon(anomalies):
    entrants = []
    with (RESULTS_DIR / "2025_marathon.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            age_group = age_group_from_cat(row["age_cat"])
            entrants.append(build_entrant(
                row, "marathon", "marathon", "marathon", age_group, anomalies, "Marathon"
            ))
    return entrants


def main():
    anomalies = []

    half_marathon = load_half_marathon(anomalies)
    marathon = load_marathon(anomalies)

    half_marathon.sort(key=lambda e: e["cumulative_seconds"])
    marathon.sort(key=lambda e: e["cumulative_seconds"])

    anomalies.append({
        "type": "transcription_note",
        "detail": (
            "Both 2025 source spreadsheets (results/2025_result_final.jpg, "
            "results/2025_result_final_marathon.jpg) have their 'First Name' and 'Surname' "
            "column headers swapped relative to the actual data in those columns - corrected "
            "during transcription into results/2025_half_marathon.csv and results/2025_marathon.csv."
        ),
    })
    anomalies.append({
        "type": "transcription_note",
        "detail": (
            "Half Marathon rows 57 (Sharon Shimmin), 58 (Elaine McCormack) and 61 (Alan MacNair): "
            "the Trail Run time was not clearly legible in the scanned image and was reconstructed "
            "by subtracting the other five race times from the printed TOTAL. Internally consistent, "
            "but worth verifying against the original spreadsheet if available."
        ),
    })

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    races = {key: {"label": RACE_LABELS[key], "status": "complete", "source": "2025 archive", "finishers": None} for key in RACE_ORDER}
    races["peel_hill"]["finishers"] = len(half_marathon) + len(marathon)
    races["marathon_half"]["finishers"] = len(half_marathon) + len(marathon)

    output = {
        "event": "Bell Burton No Rest For the Wicked 2025",
        "logo": "images/logo.jpg",
        "generated_at": generated_at,
        "races": races,
        "leagues": {"marathon": marathon, "half_marathon": half_marathon, "unassigned": []},
        "league_pdfs": {},
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    anomaly_lines = [f"Bell Burton No Rest For the Wicked 2025 - anomalies as of {generated_at}", ""]
    for a in anomalies:
        anomaly_lines.append(f"[{a['type']}] {a['detail']}")
    ANOMALIES_PATH.write_text("\n".join(anomaly_lines) + "\n", encoding="utf-8")

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Wrote {ANOMALIES_PATH}")
    print(f"  Half Marathon league: {len(half_marathon)}, Marathon league: {len(marathon)}")
    print(f"  Anomalies flagged: {len(anomalies)}")
    for a in anomalies:
        print(f"    [{a['type']}] {a['detail']}")


if __name__ == "__main__":
    main()
