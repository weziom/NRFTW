#!/usr/bin/env python3
"""One-time build of the 2024 archive file, transcribed from the club's own
season-tracking spreadsheets (results/2024_half_results.jpg,
results/2024_marathon_result.jpg) - full 6-race season, replacing the
raceresult-API-only "(partial results)" 2024.json previously built by
build_historic_results.py (Marathon/Half Marathon race only, everything
else "unavailable").

Same conventions as build_2020_2023_results.py: each row already carries a
runner's full season, so no roster-matching step; transcription
cross-checked against each row's own printed Total; source anomalies kept
as printed - see anomalies/2024.txt.

The half sheet has no Category column (unlike the marathon sheet), so it
gets its own builder distinct from build_2020_2023_results.py's
build_entrant_no_category (which also has no club - 2021's sheet had
neither).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_2020_2023_results import (  # noqa: E402
    FULL, _build_entrant, build_entrant_6race, build_year, expand_club,
)

BASE_DIR = Path(__file__).resolve().parent


def build_entrant_half(row, league):
    name, club, *times = row
    mh_time, peel_time, ramsey_time, killer_time, foxdale_time, trail_time = times
    race_times = {
        "marathon_half": mh_time,
        "peel_hill": peel_time,
        "ramsey_10k": ramsey_time,
        "killer_mile": killer_time,
        "foxdale_5": foxdale_time,
        "trail_run": trail_time,
    }
    return _build_entrant(name, None, None, expand_club(club), league, race_times)


def main():
    from historic_2024_data import HALF_2024, MARATHON_2024

    data = build_year(
        "2024", HALF_2024, MARATHON_2024,
        builder=None, race_status=FULL, foxdale_label="Foxdale 5", trail_label="Trail",
        half_builder=build_entrant_half, marathon_builder=build_entrant_6race,
    )
    with open(BASE_DIR / "2024.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote 2024.json: {len(data['leagues']['half_marathon'])} half + {len(data['leagues']['marathon'])} marathon")


if __name__ == "__main__":
    main()
