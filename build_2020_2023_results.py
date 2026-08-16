#!/usr/bin/env python3
"""One-time build of the 2020-2023 archive files, transcribed from the
club's own season-tracking spreadsheets (results/2020_*_result.jpeg,
2021_*_result.jpeg, 2022_*_result*.jpeg, 2023_half_marathon_incomplete.jpg).

Same conventions as build_2015_2019_results.py: each row already carries a
runner's full season, so no roster-matching step; transcription
cross-checked against each row's own printed Total; source anomalies (DNS/
DNF exclusions, missing club/category data, etc.) kept as printed rather
than corrected - see anomalies/<year>.txt.

2023 is genuinely incomplete in a different way from 2021/2022's old
raceresult-only archives: only the Half Marathon leg and Peel Hill have
any data at all (source filename says "incomplete") - Ramsey 10K, Killer
Mile, Foxdale and Trail are blank for every entrant, not just missing for
some, so it gets its own 2-race build path instead of the usual 6.

2021/2022 here supersede the thinner raceresult-only versions previously
built by build_historic_results.py (Peel Hill/Killer Mile/Foxdale/Trail
marked "unavailable" there) - this is the real, full 6-race data.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_results import parse_time_to_seconds, seconds_to_hms, write_league_pdf  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent

CLUB_EXPANSIONS = {
    "WAC": "Western AC",
    "NAC": "Northern AC",
    "MFR": "Manx Fell Runners",
    "MH": "Manx Harriers",
    "NA": "Unattached",
    "na": "Unattached",
    "un": "Unattached",
    "UN": "Unattached",
    "Unaffiliated": "Unattached",
    "Unattached": "Unattached",
    "IOM Vets": "IOMVAC",
    "IOM VAC": "IOMVAC",
    "U/A": "Unattached",
}


def expand_club(raw):
    return CLUB_EXPANSIONS.get(raw, raw)


def parse_category(category):
    """"M40-44" / "MSnr" / "FJnr" / "W45-49" -> (gender, age_group). All of
    2020/2022/2023's categories were transcribed letter-first (gender
    letter immediately followed by age band or Snr/Jnr, no space) - M/F
    used directly during transcription, W (as printed in the 2022/2023
    sheets) mapped to F here."""
    if not category:
        return None, None
    gender = "F" if category[0] in ("W", "L") else category[0]
    age_group = category[1:].strip() or None
    return gender, age_group


def build_entrant_6race(row, league):
    name, category, club, *times = row
    gender, age_group = parse_category(category)
    club = expand_club(club)

    mh_time, peel_time, ramsey_time, killer_time, foxdale_time, trail_time = times
    race_times = {
        "marathon_half": mh_time,
        "peel_hill": peel_time,
        "ramsey_10k": ramsey_time,
        "killer_mile": killer_time,
        "foxdale_5": foxdale_time,
        "trail_run": trail_time,
    }
    return _build_entrant(name, gender, age_group, club, league, race_times)


def build_entrant_no_category(row, league):
    name, *times = row
    mh_time, peel_time, ramsey_time, killer_time, foxdale_time, trail_time = times
    race_times = {
        "marathon_half": mh_time,
        "peel_hill": peel_time,
        "ramsey_10k": ramsey_time,
        "killer_mile": killer_time,
        "foxdale_5": foxdale_time,
        "trail_run": trail_time,
    }
    return _build_entrant(name, None, None, "", league, race_times)


def build_entrant_2race(row, league):
    """2023 only: name, category, club, half/marathon, peel_hill - the
    other 4 races have no source at all this year."""
    name, category, club, mh_time, peel_time = row
    gender, age_group = parse_category(category)
    club = expand_club(club)
    race_times = {
        "marathon_half": mh_time,
        "peel_hill": peel_time,
        "ramsey_10k": None,
        "killer_mile": None,
        "foxdale_5": None,
        "trail_run": None,
    }
    return _build_entrant(name, gender, age_group, club, league, race_times)


def _build_entrant(name, gender, age_group, club, league, race_times):
    races = {}
    cumulative_seconds = 0
    for key, time_text in race_times.items():
        if time_text is None:
            races[key] = None
            continue
        seconds = parse_time_to_seconds(time_text)
        cumulative_seconds += seconds
        races[key] = {"position": None, "time": time_text, "category": None}

    return {
        "name": name,
        "club": club,
        "gender": gender,
        "age_group": age_group,
        "league": league,
        "races": races,
        "races_completed": sum(1 for v in races.values() if v),
        "cumulative_seconds": cumulative_seconds,
        "cumulative_time": seconds_to_hms(cumulative_seconds),
    }


def build_year(year, half_rows, marathon_rows, builder, race_status, foxdale_label="Foxdale", trail_label="Trail",
                half_builder=None, marathon_builder=None):
    """`builder` is used for both leagues unless a league needs its own row
    shape (e.g. 2024's half sheet has a Club column but no Category one,
    while its marathon sheet has both) - pass half_builder/marathon_builder
    to override per league in that case."""
    half_entrants = [(half_builder or builder)(r, "half_marathon") for r in half_rows]
    marathon_entrants = [(marathon_builder or builder)(r, "marathon") for r in marathon_rows]

    half_entrants.sort(key=lambda e: e["cumulative_seconds"])
    marathon_entrants.sort(key=lambda e: e["cumulative_seconds"])

    races_ordered = {
        "marathon_half": {"label": "Marathon / Half Marathon", "status": race_status["marathon_half"], "source": f"{year} archive spreadsheet", "finishers": len(half_entrants) + len(marathon_entrants)},
        "peel_hill": {"label": "Peel Hill", "status": race_status["peel_hill"], "source": f"{year} archive spreadsheet", "finishers": None},
        "ramsey_10k": {"label": "Ramsey 10K", "status": race_status["ramsey_10k"], "source": f"{year} archive spreadsheet" if race_status["ramsey_10k"] == "complete" else None, "finishers": None},
        "killer_mile": {"label": "Killer Mile", "status": race_status["killer_mile"], "source": f"{year} archive spreadsheet" if race_status["killer_mile"] == "complete" else None, "finishers": None},
        "foxdale_5": {"label": foxdale_label, "status": race_status["foxdale_5"], "source": f"{year} archive spreadsheet" if race_status["foxdale_5"] == "complete" else None, "finishers": None},
        "trail_run": {"label": trail_label, "status": race_status["trail_run"], "source": f"{year} archive spreadsheet" if race_status["trail_run"] == "complete" else None, "finishers": None},
    }

    pdf_dir = BASE_DIR / "pdfs"
    pdf_dir.mkdir(exist_ok=True)
    league_pdfs = {}
    for league_key, entrants in (("half_marathon", half_entrants), ("marathon", marathon_entrants)):
        if not entrants:
            continue
        filename = f"{league_key}_{year}.pdf"
        write_league_pdf(league_key, entrants, races_ordered, event_name=f"No Rest For the Wicked {year}", filename=filename)
        league_pdfs[league_key] = f"pdfs/{filename}"

    event_suffix = "" if all(v == "complete" for v in race_status.values()) else " (partial results)"
    return {
        "event": f"No Rest For the Wicked {year}{event_suffix}",
        "logo": "images/logo.jpg",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "races": races_ordered,
        "leagues": {
            "half_marathon": half_entrants,
            "marathon": marathon_entrants,
            "unassigned": [],
        },
        "league_pdfs": league_pdfs,
    }


FULL = {k: "complete" for k in ("marathon_half", "peel_hill", "ramsey_10k", "killer_mile", "foxdale_5", "trail_run")}
TWO_RACE_ONLY = {
    "marathon_half": "complete", "peel_hill": "complete",
    "ramsey_10k": "unavailable", "killer_mile": "unavailable", "foxdale_5": "unavailable", "trail_run": "unavailable",
}


def main():
    from historic_2020_2023_data import (
        HALF_2020, MARATHON_2020,
        HALF_2021, MARATHON_2021,
        HALF_2022, MARATHON_2022,
        HALF_2023, MARATHON_2023,
    )

    years = [
        ("2020", HALF_2020, MARATHON_2020, build_entrant_6race, FULL, "Foxdale 6", "Heritage"),
        ("2021", HALF_2021, MARATHON_2021, build_entrant_no_category, FULL, "Foxdale", "Trail"),
        ("2022", HALF_2022, MARATHON_2022, build_entrant_6race, FULL, "Foxdale", "Trail"),
        ("2023", HALF_2023, MARATHON_2023, build_entrant_2race, TWO_RACE_ONLY, "Foxdale", "Trail"),
    ]
    for year, half_rows, marathon_rows, builder, race_status, foxdale_label, trail_label in years:
        data = build_year(year, half_rows, marathon_rows, builder, race_status, foxdale_label, trail_label)
        with open(BASE_DIR / f"{year}.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {year}.json: {len(data['leagues']['half_marathon'])} half + {len(data['leagues']['marathon'])} marathon")


if __name__ == "__main__":
    main()
