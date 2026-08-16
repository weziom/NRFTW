#!/usr/bin/env python3
"""One-time build of the 2015-2019 archive files, transcribed from the
results/*_half_results*.jpg and *_marathon_results.jpg screenshots - full
season-tracking spreadsheets (already merged across all 6 races), not raw
single-race exports, so there's no roster-matching step here the way
pull_results.py needs - each row already *is* one entrant's full season.

Foxdale 6 / Heritage Trail are this era's actual names for what are now
Foxdale 5 / Trail - kept as period-accurate labels rather than normalized
to today's naming, at the user's direction.

Transcription was cross-checked two ways per row: the six race times must
sum to the sheet's own printed Total (catches most typos), and where OCR
text was legible enough to be useful, the individual fields were compared
against it too (catches same-row column transpositions/swaps that still
sum correctly, e.g. Peel Hill and Foxdale 6 times swapped for one runner
in 2017 - found this way). Values are otherwise transcribed exactly as
printed, including truncated club names and any results that look like
data-entry errors in the original sheet - see anomalies/<year>.txt for
each year's excluded/dubious rows rather than silently "fixing" them.

Club abbreviations (WAC, NAC, MFR, U/A, IOM Vets, "Western"/"Western
Athletics Club") are expanded to match this site's modern spelling
(Western AC, Northern AC, Manx Fell Runners, Unattached, IOMVAC) since
they're unambiguous. Genuinely truncated values (IOMV, "Widnes R",
"Runnymed" - cut off by the source spreadsheet's column width) are left
as printed rather than guessed at.
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
    "IOM Vets": "IOMVAC",
    "IOM VAC": "IOMVAC",
    "U/A": "Unattached",
    "Western": "Western AC",
    "Western Athletics Club": "Western AC",
}


def expand_club(raw):
    return CLUB_EXPANSIONS.get(raw, raw)


def _parse_category_2016_2017(category):
    """"M20" / "M Open" / "L35-39" -> (gender, age_group). L (Ladies) maps
    to F; 2016's gender letter is already M/F so this is a no-op for it."""
    if not category:
        return None, None
    gender = "F" if category[0] == "L" else category[0]
    age_group = category[1:].strip() or None
    return gender, age_group


def _parse_category_2019(category):
    """"M40-44" / "W40-44" / "Senior Men" / "Senior Wom[en]" -> (gender,
    age_group). Unlike 2018, the Senior/Junior word comes first and is
    followed by a full (or truncated) gender word, not a bare letter."""
    if not category:
        return None, None
    if category.startswith("Senior "):
        prefix, rest = category.split(" ", 1)
        gender = rest.strip()[0]
        age_group = prefix
    else:
        gender = category[0]
        age_group = category[1:].strip() or None
    if gender == "W":
        gender = "F"
    return gender, age_group


def _parse_category_2018(category):
    """"M35-39" / "Senior M" / "W45-49" / "Junior M" -> (gender, age_group).
    W (Women) maps to F; Senior/Junior appear as a word before the gender
    letter instead of a number after it."""
    if not category:
        return None, None
    if category.startswith(("Senior ", "Junior ")):
        age_group, letter = category.split(" ", 1)
        gender = letter.strip()
    else:
        gender = category[0]
        age_group = category[1:].strip() or None
    if gender == "W":
        gender = "F"
    return gender, age_group


CATEGORY_PARSERS = {
    "none": lambda c: (None, None),
    "2016_2017": _parse_category_2016_2017,
    "2018": _parse_category_2018,
    "2019": _parse_category_2019,
}


def build_entrant(row, league, category_style):
    has_category = category_style != "none"
    if has_category:
        name, category, club, *times = row
        gender, age_group = CATEGORY_PARSERS[category_style](category)
        club = expand_club(club)
    else:
        name, *times = row
        gender, age_group, club = None, None, ""

    mh_time, peel_time, ramsey_time, killer_time, foxdale_time, trail_time = times
    race_times = {
        "marathon_half": mh_time,
        "peel_hill": peel_time,
        "ramsey_10k": ramsey_time,
        "killer_mile": killer_time,
        "foxdale_5": foxdale_time,
        "trail_run": trail_time,
    }

    races = {}
    cumulative_seconds = 0
    for key, time_text in race_times.items():
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
        "races_completed": len(races),
        "cumulative_seconds": cumulative_seconds,
        "cumulative_time": seconds_to_hms(cumulative_seconds),
    }


def build_year(year, half_rows, marathon_rows, category_style):
    half_entrants = [build_entrant(r, "half_marathon", category_style) for r in half_rows]
    marathon_entrants = [build_entrant(r, "marathon", category_style) for r in marathon_rows]

    half_entrants.sort(key=lambda e: e["cumulative_seconds"])
    marathon_entrants.sort(key=lambda e: e["cumulative_seconds"])

    races_ordered = {
        "marathon_half": {"label": "Marathon / Half Marathon", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": len(half_entrants) + len(marathon_entrants)},
        "peel_hill": {"label": "Peel Hill", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": None},
        "ramsey_10k": {"label": "Ramsey 10K", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": None},
        "killer_mile": {"label": "Killer Mile", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": None},
        "foxdale_5": {"label": "Foxdale 6", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": None},
        "trail_run": {"label": "Heritage Trail", "status": "complete", "source": f"{year} archive spreadsheet", "finishers": None},
    }

    pdf_dir = BASE_DIR / "pdfs"
    pdf_dir.mkdir(exist_ok=True)
    league_pdfs = {}
    for league_key, entrants in (("half_marathon", half_entrants), ("marathon", marathon_entrants)):
        filename = f"{league_key}_{year}.pdf"
        write_league_pdf(league_key, entrants, races_ordered, event_name=f"No Rest For the Wicked {year}", filename=filename)
        league_pdfs[league_key] = f"pdfs/{filename}"

    return {
        "event": f"No Rest For the Wicked {year}",
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


def main():
    from historic_2015_2019_data import (
        HALF_2015, MARATHON_2015,
        HALF_2016, MARATHON_2016,
        HALF_2017, MARATHON_2017,
        HALF_2018, MARATHON_2018,
        HALF_2019, MARATHON_2019,
    )

    years = [
        ("2015", HALF_2015, MARATHON_2015, "2016_2017"),
        ("2016", HALF_2016, MARATHON_2016, "2016_2017"),
        ("2017", HALF_2017, MARATHON_2017, "2016_2017"),
        ("2018", HALF_2018, MARATHON_2018, "2018"),
        ("2019", HALF_2019, MARATHON_2019, "2019"),
    ]
    for year, half_rows, marathon_rows, style in years:
        data = build_year(year, half_rows, marathon_rows, style)
        with open(BASE_DIR / f"{year}.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {year}.json: {len(data['leagues']['half_marathon'])} half + {len(data['leagues']['marathon'])} marathon")


if __name__ == "__main__":
    main()
