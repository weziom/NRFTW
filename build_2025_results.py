#!/usr/bin/env python3
"""
One-off build of 2025.json, the archived 'Bell Burton No Rest For the Wicked
2025' results, from the two pre-merged season CSVs in results/:
  - 2025_half_marathon.csv (Half Marathon league, 91 runners)
  - 2025_marathon.csv (Marathon league, 12 runners)

Those CSVs were transcribed from the final 2025 leaderboard spreadsheets
(results/2025_result_final.jpg and results/2025_result_final_marathon.jpg)
and already have every race's time for every runner. But per Page
Requirements.txt, the Marathon/Half Marathon and 10K (Ramsey 10K) races
also have an authoritative source on raceresult (event 327247 and 351414
respectively) - this script fetches both and uses them to fill in data the
transcribed spreadsheets don't have (bib numbers, rank, and - crucially for
the Half Marathon league, which has no age-category column at all - each
runner's actual age group), matched by full name the same way
pull_results.py matches roster runners against race sources. Where a
raceresult time disagrees with the transcribed spreadsheet, raceresult
wins (it's the live-timed source of record) and the discrepancy is logged.

Peel Hill, Killer Mile, Foxdale 5 and Trail Run have no raceresult source
for 2025, so those stay exactly as transcribed.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pull_results import (
    fetch_10k_race,
    fetch_marathon_half,
    match_by_full_name,
    normalize_name,
    parse_time_to_seconds,
    resolve_alias,
    seconds_to_hms,
    write_league_pdf,
)

EVENT_NAME = "Bell Burton No Rest For the Wicked 2025"

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = BASE_DIR / "2025.json"
ANOMALIES_PATH = BASE_DIR / "anomalies_2025.txt"

MARATHON_HALF_EVENT_ID_2025 = "327247"
RAMSEY_10K_EVENT_ID_2025 = "351414"

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


def load_rows(filename, league, contest, main_time_field, source_label):
    rows = []
    with (RESULTS_DIR / filename).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = f"{row['first_name'].strip()} {row['surname'].strip()}"
            rows.append({
                "row": row,
                "league": league,
                "contest": contest,
                "main_time_field": main_time_field,
                "source_label": source_label,
                "name": name,
                "key": normalize_name(resolve_alias(name)),
                "club": row["club"].strip(),
                "category": row.get("age_cat"),
            })
    return rows


def build_entrant(entry, mh_match, ramsey_match, anomalies):
    row = entry["row"]
    name = entry["name"]
    csv_age_group = age_group_from_cat(row["age_cat"]) if "age_cat" in row else None

    def resolved(race_key, csv_field, override, override_label):
        csv_seconds = parse_time_to_seconds(row[csv_field])
        if override and override.get("seconds") is not None:
            if csv_seconds is not None and csv_seconds != override["seconds"]:
                anomalies.append({
                    "type": "source_mismatch",
                    "detail": (
                        f"'{name}' ({entry['source_label']}): {override_label} on raceresult shows "
                        f"{seconds_to_hms(override['seconds'])} for {RACE_LABELS[race_key]}, but the "
                        f"transcribed 2025 spreadsheet shows {seconds_to_hms(csv_seconds)}. Using the "
                        "raceresult time as the source of record."
                    ),
                })
            return override["seconds"], override.get("category"), override.get("age_group"), override.get("gender")
        return csv_seconds, None, None, None

    mh_seconds, mh_category, mh_age_group, mh_gender = resolved("marathon_half", entry["main_time_field"], mh_match, "raceresult")
    ramsey_seconds, ramsey_category, ramsey_age_group, ramsey_gender = resolved("ramsey_10k", "ramsey_10k", ramsey_match, "raceresult")

    age_group = csv_age_group or mh_age_group or ramsey_age_group
    gender = row.get("gender") or mh_gender or ramsey_gender

    seconds = {
        "peel_hill": parse_time_to_seconds(row["peel_hill"]),
        "marathon_half": mh_seconds,
        "ramsey_10k": ramsey_seconds,
        "killer_mile": parse_time_to_seconds(row["killer_mile"]),
        "foxdale_5": parse_time_to_seconds(row["foxdale_5"]),
        "trail_run": parse_time_to_seconds(row["trail_run"]),
    }
    races = {
        "peel_hill": {"position": None, "time": seconds_to_hms(seconds["peel_hill"]), "category": None},
        "marathon_half": {
            "contest": entry["contest"],
            "bib": mh_match.get("bib") if mh_match else None,
            "rank": mh_match.get("rank") if mh_match else None,
            "time": seconds_to_hms(seconds["marathon_half"]),
            "category": mh_category or row.get("age_cat"),
        },
        "ramsey_10k": {
            "position": ramsey_match.get("position") if ramsey_match else None,
            "time": seconds_to_hms(seconds["ramsey_10k"]),
            "category": ramsey_category,
        },
        "killer_mile": {"position": None, "time": seconds_to_hms(seconds["killer_mile"]), "category": None},
        "foxdale_5": {"position": None, "time": seconds_to_hms(seconds["foxdale_5"]), "category": None},
        "trail_run": {"position": None, "time": seconds_to_hms(seconds["trail_run"]), "category": None},
    }

    cumulative_seconds = sum(seconds.values())
    printed_total = parse_time_to_seconds(row["total"])
    if printed_total is not None and printed_total != cumulative_seconds:
        anomalies.append({
            "type": "total_mismatch",
            "detail": (
                f"'{name}' ({entry['source_label']}, position {row['position']}): the original 2025 "
                f"spreadsheet's TOTAL ({seconds_to_hms(printed_total)}) doesn't match the sum of "
                f"the six race splits ({seconds_to_hms(cumulative_seconds)}). Showing the "
                "recomputed sum so it matches the race times displayed; verify against the "
                "original spreadsheet if available."
            ),
        })

    return {
        "name": name,
        "club": (mh_match or {}).get("club") or row["club"].strip(),
        "gender": gender or "Unknown",
        "age_group": age_group or "Unknown",
        "league": entry["league"],
        "races": races,
        "races_completed": sum(1 for v in races.values() if v and v.get("time")),
        "cumulative_seconds": cumulative_seconds,
        "cumulative_time": seconds_to_hms(cumulative_seconds),
    }


def main():
    anomalies = []

    entries = (
        load_rows("2025_half_marathon.csv", "half_marathon", "half_marathon", "half", "Half Marathon")
        + load_rows("2025_marathon.csv", "marathon", "marathon", "marathon", "Marathon")
    )

    print(f"Fetching 2025 Marathon/Half Marathon from raceresult event {MARATHON_HALF_EVENT_ID_2025}...")
    mh_source_entries = fetch_marathon_half(event_id=MARATHON_HALF_EVENT_ID_2025)
    print(f"Fetching 2025 Ramsey 10K from raceresult event {RAMSEY_10K_EVENT_ID_2025}...")
    ramsey_source_entries = fetch_10k_race(event_id=RAMSEY_10K_EVENT_ID_2025)

    mh_matched, mh_anomalies = match_by_full_name(entries, mh_source_entries, "Marathon/Half Marathon (raceresult 2025)")
    ramsey_matched, ramsey_anomalies = match_by_full_name(entries, ramsey_source_entries, "Ramsey 10K (raceresult 2025)")
    anomalies.extend(mh_anomalies)
    anomalies.extend(ramsey_anomalies)

    entrants = [
        build_entrant(entry, mh_matched.get(entry["key"]), ramsey_matched.get(entry["key"]), anomalies)
        for entry in entries
    ]

    half_marathon = sorted((e for e in entrants if e["league"] == "half_marathon"), key=lambda e: e["cumulative_seconds"])
    marathon = sorted((e for e in entrants if e["league"] == "marathon"), key=lambda e: e["cumulative_seconds"])

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
    races["marathon_half"]["finishers"] = len(mh_source_entries)
    races["marathon_half"]["source"] = f"https://my.raceresult.com/{MARATHON_HALF_EVENT_ID_2025}/"
    races["ramsey_10k"]["finishers"] = len(ramsey_source_entries)
    races["ramsey_10k"]["source"] = f"https://my.raceresult.com/{RAMSEY_10K_EVENT_ID_2025}/"

    league_pdfs = {
        league_key: write_league_pdf(league_key, entrants_list, races, event_name=EVENT_NAME, filename=f"{league_key}_2025.pdf")
        for league_key, entrants_list in [("marathon", marathon), ("half_marathon", half_marathon)]
    }

    output = {
        "event": EVENT_NAME,
        "logo": "images/logo.jpg",
        "generated_at": generated_at,
        "races": races,
        "leagues": {"marathon": marathon, "half_marathon": half_marathon, "unassigned": []},
        "league_pdfs": league_pdfs,
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
