#!/usr/bin/env python3
"""
Render leaderboard images for posting to Facebook, one or more per league
(long leagues are split into multiple images so text stays legible in a
Facebook feed). Reads results.json (produced by pull_results.py) and writes
PNGs into facebook/.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "results.json"
LOGO_PATH = BASE_DIR / "images" / "logo.jpg"
OUT_DIR = BASE_DIR / "facebook"

LEAGUE_LABELS = {"half_marathon": "Half Marathon", "marathon": "Marathon"}
COLUMN_LABELS = {"half_marathon": "Half", "marathon": "Marathon"}

MAX_ROWS_PER_IMAGE = 25

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

RED = (179, 18, 42)
WHITE = (255, 255, 255)
TEXT = (40, 36, 32)
GRID = (226, 221, 211)
STRIPE = (250, 249, 247)
CREAM = (255, 255, 255)

WIDTH = 1600
MARGIN = 40
HEADER_H = 170
ROW_H = 52
COL_HEADER_H = 60
FOOTER_H = 20


def font(path, size):
    return ImageFont.truetype(str(path), size)


def race_cell_text(entry, race_key, races_meta):
    r = entry["races"].get(race_key)
    if r and r.get("time"):
        return r["time"]
    return "00:00:00" if races_meta[race_key]["status"] == "pending" else "-"


def split_name(full_name):
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def text_w(draw, text, f):
    return draw.textlength(text, font=f)


def fit_header_font(draw, text, max_width, start_size=20, min_size=13):
    """Shrink the bold header font until `text` fits within max_width (minus
    padding) - some race labels ('Half Marathon') are wider than the column
    a 6-column race grid leaves available at the default size."""
    size = start_size
    while size > min_size:
        f = font(FONT_BOLD, size)
        if text_w(draw, text, f) <= max_width - 16:
            return f
        size -= 1
    return font(FONT_BOLD, min_size)


def draw_table(entrants, start_rank, races_ordered, league_key, league_label, part_label, event_name):
    race_order = list(races_ordered.keys())

    headers = ["Pos", "First Name", "Last Name"]
    for rk in race_order:
        label = races_ordered[rk]["label"]
        if rk == "marathon_half":
            label = COLUMN_LABELS[league_key]
        headers.append(label)
    headers.append("TOTAL")

    n_rows = len(entrants)
    height = HEADER_H + COL_HEADER_H + n_rows * ROW_H + FOOTER_H + MARGIN
    img = Image.new("RGB", (WIDTH, height), CREAM)
    draw = ImageDraw.Draw(img)

    f_title = font(FONT_BOLD, 42)
    f_subtitle = font(FONT_BOLD, 30)
    f_part = font(FONT_REGULAR, 22)
    f_header = font(FONT_BOLD, 20)
    f_cell = font(FONT_REGULAR, 20)
    f_cell_bold = font(FONT_BOLD, 20)

    # Header banner
    draw.rectangle([0, 0, WIDTH, HEADER_H], fill=WHITE)
    try:
        logo = Image.open(LOGO_PATH).convert("RGB")
        logo_h = HEADER_H - 40
        logo_w = int(logo.width * (logo_h / logo.height))
        logo = logo.resize((logo_w, logo_h))
        img.paste(logo, (MARGIN, 20))
        text_x = MARGIN + logo_w + 30
    except Exception:
        text_x = MARGIN

    draw.text((text_x, 30), event_name, font=f_title, fill=RED)
    draw.text((text_x, 82), f"{league_label} League", font=f_subtitle, fill=TEXT)
    draw.text((text_x, 124), part_label, font=f_part, fill=(140, 134, 126))

    # Column widths
    table_left = MARGIN
    table_right = WIDTH - MARGIN
    table_w = table_right - table_left

    fixed_cols = {"Pos": 65, "First Name": 180, "Last Name": 200, "TOTAL": 140}
    n_race_cols = len(headers) - 4
    remaining = table_w - sum(fixed_cols.values())
    race_col_w = remaining // n_race_cols if n_race_cols else 0

    col_widths = []
    for h in headers:
        if h in fixed_cols:
            col_widths.append(fixed_cols[h])
        else:
            col_widths.append(race_col_w)
    # Absorb rounding remainder into TOTAL column
    col_widths[-1] += table_w - sum(col_widths)

    col_x = [table_left]
    for w in col_widths:
        col_x.append(col_x[-1] + w)

    # Column headers
    y = HEADER_H
    draw.rectangle([table_left, y, table_right, y + COL_HEADER_H], fill=RED)
    for i, h in enumerate(headers):
        hf = f_header if h in ("Pos", "First Name", "Last Name", "TOTAL") else fit_header_font(draw, h, col_widths[i])
        cx = col_x[i] + col_widths[i] / 2
        tw = text_w(draw, h, hf)
        align = "left" if headers[i] in ("First Name", "Last Name") else "center"
        if align == "left":
            tx = col_x[i] + 14
        else:
            tx = cx - tw / 2
        th = hf.size
        draw.text((tx, y + (COL_HEADER_H - th) / 2 - 2), h, font=hf, fill=WHITE)

    # Rows
    y = HEADER_H + COL_HEADER_H
    for idx, e in enumerate(entrants):
        rank = start_rank + idx
        row_bg = STRIPE if idx % 2 else CREAM
        draw.rectangle([table_left, y, table_right, y + ROW_H], fill=row_bg)

        first, last = split_name(e["name"])
        values = [str(rank), first, last]
        values.extend(race_cell_text(e, rk, races_ordered) for rk in race_order)
        values.append(e["cumulative_time"] or "-")

        for i, v in enumerate(values):
            h = headers[i]
            fnt = f_cell_bold if h in ("Pos", "TOTAL") else f_cell
            align = "left" if h in ("First Name", "Last Name") else "center"
            ty = y + (ROW_H - 24) / 2
            if align == "left":
                tx = col_x[i] + 14
            else:
                tw = text_w(draw, v, fnt)
                tx = col_x[i] + col_widths[i] / 2 - tw / 2
            draw.text((tx, ty), v, font=fnt, fill=TEXT)

        y += ROW_H

    # Grid lines
    total_bottom = y
    for x in col_x:
        draw.line([x, HEADER_H, x, total_bottom], fill=GRID, width=1)
    draw.line([table_left, total_bottom, table_right, total_bottom], fill=GRID, width=1)

    return img


def main():
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    races_ordered = data["races"]
    event_name = data["event"]

    OUT_DIR.mkdir(exist_ok=True)
    for f in OUT_DIR.glob("*.png"):
        f.unlink()

    for league_key, league_label in LEAGUE_LABELS.items():
        entrants = data["leagues"].get(league_key, [])
        if not entrants:
            continue

        chunks = [
            entrants[i:i + MAX_ROWS_PER_IMAGE]
            for i in range(0, len(entrants), MAX_ROWS_PER_IMAGE)
        ]
        total_parts = len(chunks)

        for part_idx, chunk in enumerate(chunks, start=1):
            start_rank = (part_idx - 1) * MAX_ROWS_PER_IMAGE + 1
            part_label = (
                f"Part {part_idx} of {total_parts} — Positions {start_rank}-{start_rank + len(chunk) - 1}"
                if total_parts > 1 else f"Full Standings ({len(entrants)} runners)"
            )
            img = draw_table(chunk, start_rank, races_ordered, league_key, league_label, part_label, event_name)

            suffix = f"_part{part_idx}" if total_parts > 1 else ""
            out_path = OUT_DIR / f"{league_key}{suffix}.png"
            img.save(out_path)
            print(f"Wrote {out_path} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
