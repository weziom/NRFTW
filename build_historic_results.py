#!/usr/bin/env python3
"""
Build private, non-public archive files for historic 'No Rest For the
Wicked' seasons where the only available source is raceresult's
Marathon/Half Marathon event (and, for some years, a standalone 10K race) -
there's no Peel Hill result for these years, so there's no way to
determine the official series roster the way pull_results.py and
build_2025_results.py do.

Per the user's direction: for these years, the roster is simply "everyone
who ran the Marathon or Half Marathon that year" - cumulative time is
whatever races that runner also has a result in (10K where available).
Peel Hill / Killer Mile / Foxdale 5 / Trail Run have no source at all for
these years and are marked "unavailable", not "pending" (they didn't just
not-happen-yet, there's no way to find out about them).

These files are intentionally NOT wired into index.html's Year selector -
they're incomplete (missing several races' worth of data) and shouldn't be
presented as equivalent to the live 2026 site or the fuller 2025 archive.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from pull_results import (
    fetch_10k_race,
    fetch_marathon_half,
    match_by_full_name,
    seconds_to_hms,
)

BASE_DIR = Path(__file__).resolve().parent

RACE_LABELS = {
    "marathon_half": "Marathon / Half Marathon",
    "peel_hill": "Peel Hill",
    "ramsey_10k": "Ramsey 10K",
    "killer_mile": "Killer Mile",
    "foxdale_5": "Foxdale 5",
    "trail_run": "Trail",
}
RACE_ORDER = ["marathon_half", "peel_hill", "ramsey_10k", "killer_mile", "foxdale_5", "trail_run"]

# year -> (marathon/half event id, 10K event id or None)
YEARS = {
    "2024": ("274541", None),
    "2022": ("188406", "209333"),
    "2021": ("162820", "176096"),
}


def build_year(year, mh_event_id, ramsey_event_id):
    anomalies = []

    print(f"[{year}] Fetching Marathon/Half from raceresult event {mh_event_id}...")
    roster = [e for e in fetch_marathon_half(event_id=mh_event_id, use_cache=True) if e["contest"] in ("marathon", "half_marathon")]

    ramsey_matched = {}
    ramsey_source_entries = []
    if ramsey_event_id:
        print(f"[{year}] Fetching 10K from raceresult event {ramsey_event_id}...")
        ramsey_source_entries = fetch_10k_race(event_id=ramsey_event_id, use_cache=True)
        ramsey_matched, ramsey_anomalies = match_by_full_name(roster, ramsey_source_entries, "10K")
        # Unlike the live pipeline, most Marathon/Half runners were never
        # expected to also run the standalone 10K - "no_result" here just
        # means "didn't run the extra race", not a data problem. Keep only
        # genuine data-quality anomalies (duplicate/ambiguous names).
        anomalies.extend(a for a in ramsey_anomalies if a["type"] != "no_result")

    entrants = []
    for mh in roster:
        ramsey = ramsey_matched.get(mh["key"])
        seconds = {"marathon_half": mh["seconds"], "ramsey_10k": ramsey["seconds"] if ramsey else None}
        cumulative_seconds = sum(v for v in seconds.values() if v is not None) if any(seconds.values()) else None

        entrants.append({
            "name": mh["name"],
            "club": mh["club"],
            "gender": mh["gender"] or "Unknown",
            "age_group": mh["age_group"] or "Unknown",
            "league": mh["contest"],
            "races": {
                "marathon_half": {
                    "contest": mh["contest"],
                    "bib": mh["bib"],
                    "rank": mh["rank"],
                    "time": mh["time"],
                    "category": mh["category"],
                },
                "peel_hill": None,
                "ramsey_10k": ({
                    "position": ramsey["position"],
                    "time": ramsey["time"],
                    "category": ramsey["category"],
                } if ramsey else None),
                "killer_mile": None,
                "foxdale_5": None,
                "trail_run": None,
            },
            "races_completed": sum(1 for v in seconds.values() if v is not None),
            "cumulative_seconds": cumulative_seconds,
            "cumulative_time": seconds_to_hms(cumulative_seconds),
        })

    half_marathon = sorted(
        (e for e in entrants if e["league"] == "half_marathon"),
        key=lambda e: (e["cumulative_seconds"] is None, e["cumulative_seconds"]),
    )
    marathon = sorted(
        (e for e in entrants if e["league"] == "marathon"),
        key=lambda e: (e["cumulative_seconds"] is None, e["cumulative_seconds"]),
    )

    anomalies.insert(0, {
        "type": "incomplete_roster",
        "detail": (
            f"No Peel Hill source exists for {year}, so there's no official series roster - "
            "the roster here is simply everyone who ran the Marathon or Half Marathon that year. "
            "Peel Hill, Killer Mile, Foxdale 5 and Trail Run have no source at all for this year "
            "(marked 'unavailable') and don't count toward cumulative time. This file is NOT "
            "representative of the full series and is kept out of the public site."
        ),
    })

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    races = {key: {"label": RACE_LABELS[key], "status": "unavailable", "source": None, "finishers": 0} for key in RACE_ORDER}
    races["marathon_half"]["status"] = "complete"
    races["marathon_half"]["source"] = f"https://my.raceresult.com/{mh_event_id}/"
    races["marathon_half"]["finishers"] = len(roster)
    if ramsey_event_id:
        races["ramsey_10k"]["status"] = "complete"
        races["ramsey_10k"]["source"] = f"https://my.raceresult.com/{ramsey_event_id}/"
        races["ramsey_10k"]["finishers"] = len(ramsey_source_entries)

    output = {
        "event": f"No Rest For the Wicked {year} (INCOMPLETE ARCHIVE - not public)",
        "logo": "images/logo.jpg",
        "generated_at": generated_at,
        "races": races,
        "leagues": {"marathon": marathon, "half_marathon": half_marathon, "unassigned": []},
        "league_pdfs": {},
    }

    output_path = BASE_DIR / f"{year}.json"
    anomalies_path = BASE_DIR / "anomalies" / f"{year}.txt"

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    anomaly_lines = [f"No Rest For the Wicked {year} (incomplete archive) - anomalies as of {generated_at}", ""]
    for a in anomalies:
        anomaly_lines.append(f"[{a['type']}] {a['detail']}")
    anomalies_path.parent.mkdir(exist_ok=True)
    anomalies_path.write_text("\n".join(anomaly_lines) + "\n", encoding="utf-8")

    print(f"[{year}] Wrote {output_path}")
    print(f"[{year}] Wrote {anomalies_path}")
    print(f"[{year}]   Half Marathon: {len(half_marathon)}, Marathon: {len(marathon)}, Anomalies: {len(anomalies)}")


def main():
    for year, (mh_event_id, ramsey_event_id) in YEARS.items():
        build_year(year, mh_event_id, ramsey_event_id)


if __name__ == "__main__":
    main()
