#!/usr/bin/env python3
"""
Pull and parse results for the 'No Rest For the Wicked 2026' running series into
a single results.json used by the leaderboard webpage.

Data sources:
  - Marathon / Half Marathon: live API on my.raceresult.com (event 381348)
  - Peel Hill, Ramsey 10K, Killer Mile, Foxdale 5, Trail Run: any CSV file
    dropped into results/ whose filename contains that race's prefix (see
    RACE_FILE_DEFS below) is picked up automatically, e.g.:
        results/peelhill_2026.csv
        results/foxdale5_2026.csv
        results/ramsey10k-2026-final.csv
    CSV columns: position,first_name,last_name,time,category,club
    (position/category/club are optional; first_name,last_name,time required)
    If only scanned image/PDF result sheets are dropped in (no CSV) - there's
    no OCR tooling available in this environment - the race is reported as
    "needs_transcription" and flagged as an anomaly until someone transcribes
    them into a CSV with the columns above.

Series rule: a runner is only "in" the series if they have a Peel Hill
result - that's the series roster. Scoring runs from the Marathon / Half
Marathon onward, so cumulative time = sum of every race a roster runner has
a result in, matched by full name. There are two leagues, split by whether
the runner ran the Marathon or the Half Marathon.
"""

import csv
import difflib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
PDF_DIR = BASE_DIR / "pdfs"
OUTPUT_PATH = BASE_DIR / "results.json"
ANOMALIES_PATH = BASE_DIR / "anomalies.txt"

LEAGUE_LABELS = {"half_marathon": "Half Marathon", "marathon": "Marathon"}

MARATHON_EVENT_ID = "381348"
MARATHON_TAB = "results"
MARATHON_SOURCE_URL = f"https://my.raceresult.com/{MARATHON_EVENT_ID}/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".pdf"}

# raceresult's dynamic-format expression that colors women's rows pink - the
# most reliable gender signal available in the Marathon/Half Marathon feed.
GENDER_FIELD_EXPR = 'if([SEX]="f";"C(#E858A0)";"")'

# Order here is the display/column order used in results.json.
RACE_FILE_DEFS = [
    {"key": "peel_hill", "label": "Peel Hill", "prefix": "peelhill"},
    {"key": "ramsey_10k", "label": "Ramsey 10K", "prefix": "ramsey10k"},
    {"key": "killer_mile", "label": "Killer Mile", "prefix": "killermile"},
    {"key": "foxdale_5", "label": "Foxdale 5", "prefix": "foxdale5"},
    {"key": "trail_run", "label": "Trail Run", "prefix": "trailrun"},
]

# Known spelling/format variants of a runner's name as it appears in a race's
# results, mapped onto the spelling used for that runner on the series roster
# (Peel Hill), so they still match up without hand-editing the source CSV.
# Keys are matched case-insensitively against the name as read from the file.
NAME_ALIASES = {
    "jeffrey m moore": "Jeffrey Moore",
}


def resolve_alias(name):
    return NAME_ALIASES.get(name.strip().lower(), name)


def normalize_name(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z]", "", name.lower())
    return name


def parse_time_to_seconds(text):
    text = text.strip()
    m = re.match(r"^(\d+):(\d{2}):(\d{2})$", text)
    if m:
        h, mnt, s = map(int, m.groups())
        return h * 3600 + mnt * 60 + s
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", text)
    if m and any(m.groups()):
        h, mnt, s = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mnt * 60 + s
    return None


def seconds_to_hms(total_seconds):
    if total_seconds is None:
        return None
    total_seconds = int(round(total_seconds))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def split_age_group(category_text):
    """'Men 35-39 (3rd)' -> '35-39', 'Senior Women (1st)' -> 'Senior', etc."""
    base = re.sub(r"\s*\([^)]*\)\s*$", "", category_text).strip()
    m = re.match(r"^(Senior|Junior)\s+(Men|Women)$", base, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.match(r"^(Men|Women)\s+(.+)$", base, re.IGNORECASE)
    if m:
        return m.group(2)
    return base or None


def peel_hill_age_group(category_code):
    """Map a Peel Hill category code (SEN/JUN/V35../V80) onto the same age-group
    vocabulary used elsewhere (Senior/Junior/35-39/../70+), so it can be compared
    against other races' age groups when disambiguating duplicate names."""
    code = (category_code or "").strip().upper()
    if code == "SEN":
        return "Senior"
    if code == "JUN":
        return "Junior"
    m = re.match(r"^V(\d+)$", code)
    if m:
        n = int(m.group(1))
        return "70+" if n >= 70 else f"{n}-{n + 4}"
    return None


def candidates_matching_age(ph, candidates):
    """Candidates whose category/age group lines up with the roster runner's,
    either as an exact category match or via the Peel Hill code mapping above."""
    ph_category = (ph.get("category") or "").strip().upper()
    ph_age_group = peel_hill_age_group(ph_category)
    matches = []
    for c in candidates:
        c_category = (c.get("category") or "").strip().upper()
        c_age_group = (c.get("age_group") or "").strip()
        if ph_category and c_category and c_category == ph_category:
            matches.append(c)
        elif ph_age_group and c_age_group and c_age_group == ph_age_group:
            matches.append(c)
    return matches


def find_race_files(prefix):
    """Any file in results/ whose name contains `prefix` (case-insensitive)."""
    prefix_l = prefix.lower()
    csv_files, image_files = [], []
    for p in sorted(RESULTS_DIR.iterdir()):
        if not p.is_file() or prefix_l not in p.name.lower():
            continue
        if p.suffix.lower() == ".csv":
            csv_files.append(p)
        elif p.suffix.lower() in IMAGE_EXTS:
            image_files.append(p)
    return csv_files, image_files


def load_csv_entries(paths):
    entries = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = f"{row['first_name'].strip()} {row['last_name'].strip()}"
                position = (row.get("position") or "").strip()
                gender = (row.get("gender") or "").strip().upper()[:1] or None
                entries.append({
                    "position": int(position) if position else None,
                    "name": name,
                    "category": (row.get("category") or "").strip(),
                    "club": (row.get("club") or "").strip(),
                    "time": row["time"].strip(),
                    "seconds": parse_time_to_seconds(row["time"]),
                    "key": normalize_name(resolve_alias(name)),
                    "gender": gender,
                    "age_group": (row.get("category") or "").strip() or None,
                })
    return entries


def load_file_race(race_def):
    csv_files, image_files = find_race_files(race_def["prefix"])
    entries = load_csv_entries(csv_files)
    anomalies = []

    if entries:
        status = "complete"
    elif image_files:
        status = "needs_transcription"
        anomalies.append({
            "type": "unparsed_result_images",
            "detail": (
                f"{len(image_files)} image/PDF file(s) found for {race_def['label']} "
                f"({', '.join(p.name for p in image_files)}) but there is no OCR tooling "
                "available to parse them automatically. Transcribe them into a CSV named "
                f"like 'results/{race_def['prefix']}_2026.csv' with columns "
                "position,first_name,last_name,time,category,club and rerun this script."
            ),
        })
    else:
        status = "pending"

    meta = {
        "label": race_def["label"],
        "status": status,
        "source": ", ".join(p.name for p in csv_files) if csv_files else None,
        "finishers": len(entries),
    }
    return entries, meta, anomalies


def fetch_marathon_half():
    session = requests.Session()
    session.headers.update(HEADERS)

    config = session.get(
        f"https://my.raceresult.com/{MARATHON_EVENT_ID}/{MARATHON_TAB}/config",
        timeout=30,
    ).json()
    server = config["server"]
    key = config["key"]

    list_name = next(
        (lst["Name"] for lst in config["Tab"]["Config"]["Lists"]
         if lst["Name"].endswith("Result Overall")),
        None,
    )
    if not list_name:
        raise RuntimeError("Could not find the 'Result Overall' list in raceresult config")

    params = {
        "key": key,
        "listname": list_name,
        "page": MARATHON_TAB,
        "contest": "0",
        "r": "all",
        "l": "0",
        "fav": "",
        "openedGroups": "{}",
        "term": "",
    }
    payload = session.get(
        f"https://{server}/{MARATHON_EVENT_ID}/{MARATHON_TAB}/list",
        params=params,
        timeout=30,
    ).json()

    col = {field: i for i, field in enumerate(payload["DataFields"])}
    name_col = col["NamePlusBib"]
    club_col = col["ResolvedAffiliatedClubName"]
    cat_col = col["[AGEGROUP.NAME]&WithBrackets([Finish.AGEGROUP.th])"]
    result_col = col["WithStatus([RESULT])"]
    rank_col = col["WithStatus([OverallRank.Th])"]
    sex_col = col.get(GENDER_FIELD_EXPR)

    entries = []
    for group_key, rows in payload["data"].items():
        contest_label = group_key.split("_", 1)[1] if "_" in group_key else group_key
        if "Half" in contest_label:
            contest = "half_marathon"
        elif "Marathon" in contest_label:
            contest = "marathon"
        else:
            contest = "other"

        for r in rows:
            name_bib = r[name_col]
            m = re.match(r"^(.*)\s\((\d+)\)$", name_bib)
            name, bib = (m.group(1), m.group(2)) if m else (name_bib, None)
            time_text = r[result_col]
            category_text = r[cat_col].strip()
            entries.append({
                "contest": contest,
                "contest_label": contest_label,
                "bib": bib,
                "position": None,
                "name": name.strip(),
                "rank": r[rank_col],
                "club": r[club_col].strip(),
                "category": category_text,
                "time": time_text,
                "seconds": parse_time_to_seconds(time_text),
                "key": normalize_name(resolve_alias(name)),
                "gender": ("F" if (sex_col is not None and r[sex_col]) else "M"),
                "age_group": split_age_group(category_text),
            })
    return entries


def match_by_full_name(roster, entries, label):
    """Match `entries` (any race) onto the series roster by normalized full name.

    Returns (roster_key -> matched entry dict, anomalies). Duplicate names in
    `entries` are disambiguated using club name; anything left ambiguous, or
    any roster runner missing from `entries` entirely, is reported.
    """
    anomalies = []
    by_key = {}
    for e in entries:
        by_key.setdefault(e["key"], []).append(e)

    # Runners who never ran the original qualifying event (Peel Hill) aren't
    # part of the series - don't capture/report anything about them, even as
    # a side effect of name-matching. Only check for duplicates among names
    # that are actually on the series roster.
    roster_keys = {ph["key"] for ph in roster}
    for key, matches in by_key.items():
        if key in roster_keys and len(matches) > 1:
            anomalies.append({
                "type": "duplicate_name",
                "detail": (
                    f"{len(matches)} {label} entrants share the name '{matches[0]['name']}'. "
                    "Matched to the series roster by club name where possible."
                ),
            })

    matched = {}
    for ph in roster:
        candidates = by_key.get(ph["key"], [])
        if len(candidates) == 1:
            matched[ph["key"]] = candidates[0]
        elif len(candidates) > 1:
            club_matches = [
                c for c in candidates
                if c["club"] and ph["club"] and c["club"].lower() == ph["club"].lower()
            ]
            age_matches = candidates_matching_age(ph, candidates)
            both_matches = [c for c in club_matches if c in age_matches]
            if len(both_matches) == 1:
                matched[ph["key"]] = both_matches[0]
            elif len(club_matches) == 1:
                matched[ph["key"]] = club_matches[0]
            elif len(age_matches) == 1:
                matched[ph["key"]] = age_matches[0]
            else:
                anomalies.append({
                    "type": "ambiguous_match",
                    "detail": (
                        f"Series entrant '{ph['name']}' matches {len(candidates)} {label} "
                        "entrants by name and could not be disambiguated by club or age group. "
                        "Excluded from that race's cumulative total."
                    ),
                })
        elif entries:
            suggestion = ""
            close = difflib.get_close_matches(ph["key"], by_key.keys(), n=1, cutoff=0.82)
            if close:
                candidate = by_key[close[0]][0]
                suggestion = f" Possible spelling mismatch: found similarly named '{candidate['name']}' in {label} results."
            anomalies.append({
                "type": "no_result",
                "detail": f"Series entrant '{ph['name']}' has no matching {label} result.{suggestion}",
            })

    return matched, anomalies


def build_leaderboard(roster, marathon_half_entries, other_races):
    """other_races: dict of race_key -> list of entries (already loaded)."""
    anomalies = []

    marathon_match, marathon_anomalies = match_by_full_name(roster, marathon_half_entries, "Marathon/Half Marathon")
    anomalies.extend(marathon_anomalies)

    other_matches = {}
    for race_key, entries in other_races.items():
        matched, match_anomalies = match_by_full_name(roster, entries, race_key.replace("_", " ").title())
        other_matches[race_key] = matched
        anomalies.extend(match_anomalies)

    entrants = []
    for ph in roster:
        races = {
            "peel_hill": {"position": ph["position"], "time": ph["time"], "category": ph["category"]},
        }
        seconds_total = ph["seconds"]
        club = ph["club"]
        gender = None
        age_group = ph["category"] or None

        mh = marathon_match.get(ph["key"])
        if mh:
            races["marathon_half"] = {
                "contest": mh["contest"],
                "bib": mh["bib"],
                "rank": mh["rank"],
                "time": mh["time"],
                "category": mh["category"],
            }
            if mh["seconds"] is not None and seconds_total is not None:
                seconds_total += mh["seconds"]
            league = mh["contest"]
            if mh["club"]:
                club = mh["club"]
            gender = mh["gender"]
            age_group = mh["age_group"] or age_group
        else:
            races["marathon_half"] = None
            league = "unassigned"

        for race_key in other_races:
            match = other_matches[race_key].get(ph["key"])
            if match:
                races[race_key] = {
                    "position": match["position"],
                    "time": match["time"],
                    "category": match["category"],
                }
                if match["seconds"] is not None and seconds_total is not None:
                    seconds_total += match["seconds"]
                if gender is None and match.get("gender"):
                    gender = match["gender"]
                if match.get("age_group"):
                    age_group = match["age_group"]
            else:
                races[race_key] = None

        entrants.append({
            "name": ph["name"],
            "club": club,
            "gender": gender or "Unknown",
            "age_group": age_group or "Unknown",
            "league": league,
            "races": races,
            "races_completed": sum(1 for v in races.values() if v),
            "cumulative_seconds": seconds_total,
            "cumulative_time": seconds_to_hms(seconds_total),
        })

    entrants.sort(key=lambda e: (e["cumulative_seconds"] is None, e["cumulative_seconds"]))
    return entrants, anomalies


def race_cell_text(entry, race_key, races_meta):
    r = entry["races"].get(race_key)
    if r and r.get("time"):
        return r["time"]
    return "--" if races_meta[race_key]["status"] == "pending" else "-"


def write_league_pdf(league_key, entrants, races_ordered):
    """Render a printable leaderboard PDF for one league (Half Marathon or
    Marathon) into PDF_DIR, mirroring the columns shown on the webpage."""
    PDF_DIR.mkdir(exist_ok=True)
    league_label = LEAGUE_LABELS[league_key]
    race_order = list(races_ordered.keys())

    headers = ["#", "Name", "Cumulative", "Club"]
    for rk in race_order:
        label = races_ordered[rk]["label"]
        if rk == "marathon_half":
            label = league_label
        headers.append(label)

    data = [headers]
    for i, e in enumerate(entrants, start=1):
        row = [str(i), e["name"], e["cumulative_time"] or "-", e["club"] or "-"]
        row.extend(race_cell_text(e, rk, races_ordered) for rk in race_order)
        data.append(row)

    out_path = PDF_DIR / f"{league_key}.pdf"
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"No Rest For the Wicked 2026 - {league_label} League",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"No Rest For the Wicked 2026 &mdash; {league_label} League", styles["Title"]),
        Spacer(1, 8 * mm),
    ]

    if entrants:
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#b3122a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf9f7")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2ddd3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No runners in this league yet.", styles["Normal"]))

    doc.build(story)
    return f"pdfs/{league_key}.pdf"


def main():
    race_defs_by_key = {r["key"]: r for r in RACE_FILE_DEFS}

    roster, roster_meta, roster_anomalies = load_file_race(race_defs_by_key["peel_hill"])
    if not roster:
        raise RuntimeError(
            "No Peel Hill results found in results/ (filename must contain 'peelhill'). "
            "Peel Hill is the series roster - without it there's no leaderboard to build."
        )

    other_race_defs = [r for r in RACE_FILE_DEFS if r["key"] != "peel_hill"]
    other_races = {}
    races_meta = {"peel_hill": roster_meta}
    anomalies = list(roster_anomalies)

    for rdef in other_race_defs:
        entries, meta, file_anomalies = load_file_race(rdef)
        other_races[rdef["key"]] = entries
        races_meta[rdef["key"]] = meta
        anomalies.extend(file_anomalies)

    marathon_half = fetch_marathon_half()
    races_meta["marathon_half"] = {
        "label": "Marathon / Half Marathon",
        "status": "complete",
        "source": MARATHON_SOURCE_URL,
        "finishers": len(marathon_half),
    }

    entrants, match_anomalies = build_leaderboard(roster, marathon_half, other_races)
    anomalies.extend(match_anomalies)

    leagues = {"marathon": [], "half_marathon": [], "unassigned": []}
    for e in entrants:
        leagues.setdefault(e["league"], []).append(e)

    # Fixed race column order: peel_hill, marathon_half, then the rest as declared above.
    races_ordered = {"peel_hill": races_meta["peel_hill"], "marathon_half": races_meta["marathon_half"]}
    for rdef in other_race_defs:
        races_ordered[rdef["key"]] = races_meta[rdef["key"]]

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    league_pdfs = {
        league_key: write_league_pdf(league_key, leagues.get(league_key, []), races_ordered)
        for league_key in LEAGUE_LABELS
    }

    output = {
        "event": "No Rest For the Wicked 2026",
        "logo": "images/logo.jpg",
        "generated_at": generated_at,
        "races": races_ordered,
        "leagues": leagues,
        "league_pdfs": league_pdfs,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    anomaly_lines = [f"No Rest For the Wicked 2026 - anomalies as of {generated_at}", ""]
    for a in anomalies:
        anomaly_lines.append(f"[{a['type']}] {a['detail']}")
    if not anomalies:
        anomaly_lines.append("(none)")
    ANOMALIES_PATH.write_text("\n".join(anomaly_lines) + "\n", encoding="utf-8")

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Wrote {ANOMALIES_PATH}")
    print(f"  Series entrants (Peel Hill finishers): {len(entrants)}")
    print(f"  Marathon league: {len(leagues['marathon'])}, Half Marathon league: {len(leagues['half_marathon'])}, Unassigned: {len(leagues['unassigned'])}")
    print(f"  Anomalies flagged: {len(anomalies)}")
    for a in anomalies:
        print(f"    [{a['type']}] {a['detail']}")


if __name__ == "__main__":
    main()
