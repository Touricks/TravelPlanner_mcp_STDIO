from __future__ import annotations

"""Import Notion CSV export into SQLite places + itinerary_items tables.

Reads the _all.csv (46 rows) and cross-references pois.yaml for source attribution.
"""

import csv
import sqlite3
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
TRIPDB_DIR = SEED_DIR.parent
CSV_PATH = SEED_DIR / "sources" / "itinerary_export.csv"
POIS_YAML_PATH = SEED_DIR / "sources" / "pois.yaml"
DB_PATH = TRIPDB_DIR / "travel.db"

TRIP_ID = "2026-04-san-francisco"
TRIP_START = date(2026, 4, 17)
TRIP_END = date(2026, 4, 25)

COFFEE_KEYWORDS = [
    "Coffee", "Blue Bottle", "Verve", "Scout Coffee",
    "Intelligentsia", "Sightglass", "Bakery & Coffee"
]


def parse_duration(text: str) -> int | None:
    """Parse duration text to minutes. '1.5h'→90, '30min'→30, '2h'→120."""
    if not text:
        return None
    text = text.strip().lower()
    if text.endswith('h'):
        return int(float(text[:-1]) * 60)
    if text.endswith('min'):
        return int(text[:-3])
    return None


def day_label_to_date(label: str) -> str:
    """Convert 'Day 2' to ISO date '2026-04-18'."""
    num = int(label.replace('Day ', ''))
    return (TRIP_START + timedelta(days=num - 1)).isoformat()


def parse_time_range(time_str: str) -> tuple[str | None, str | None]:
    """Parse '18:30-19:30' into ('18:30', '19:30')."""
    if not time_str or '-' not in time_str:
        return None, None
    parts = time_str.strip().split('-')
    return parts[0].strip(), parts[1].strip()


def detect_style(name: str, csv_style: str) -> str:
    """Detect 'coffee' style from name heuristic; otherwise use CSV value."""
    for kw in COFFEE_KEYWORDS:
        if kw.lower() in name.lower():
            return 'coffee'
    return csv_style


def compute_sort_order(day_num: int, time_start: str | None) -> float:
    """Compute sort_order for chronological ordering within days."""
    base = day_num * 1000.0
    if time_start:
        parts = time_start.split(':')
        base += int(parts[0]) * 60 + int(parts[1])
    return base


def load_yaml_sources() -> dict[str, str]:
    """Load pois.yaml to get source attribution for each POI by name."""
    sources = {}
    if not POIS_YAML_PATH.exists():
        return sources
    # Simple YAML parsing without external dependency
    current_name = None
    current_source = None
    for line in POIS_YAML_PATH.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith('name_en:'):
            current_name = stripped.split(':', 1)[1].strip().strip('"')
        elif stripped.startswith('source:'):
            current_source = stripped.split(':', 1)[1].strip().strip('"')
            if current_name and current_source:
                sources[current_name] = current_source
                current_name = None
                current_source = None
    return sources


def import_csv(conn: sqlite3.Connection):
    """Import CSV into places + itinerary_items."""
    cursor = conn.cursor()

    # Create trip
    cursor.execute("""
        INSERT OR IGNORE INTO trips (id, destination, start_date, end_date, version,
                                     notion_page_id)
        VALUES (?, ?, ?, ?, 2, '32a9db12-bca8-818a-9681-c61552a64842')
    """, (TRIP_ID, "San Francisco & California Coast",
          TRIP_START.isoformat(), TRIP_END.isoformat()))

    # Load source attribution from pois.yaml
    yaml_sources = load_yaml_sources()

    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        place_count = 0
        item_count = 0

        for row in reader:
            name_en = row['Name'].strip()
            name_cn = row.get('Chinese Name', '').strip()
            csv_style = row.get('Style', '').strip()
            style = detect_style(name_en, csv_style)
            address = row.get('Address', '').strip()
            city = row.get('City', '').strip()
            description = row.get('Description', '').strip()
            maps_url = row.get('userDefined:URL', '').strip()
            source = yaml_sources.get(name_en, 'agent')

            # Insert place
            cursor.execute("""
                INSERT INTO places (name_en, name_cn, style, address, city,
                                    maps_url, description, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name_en, name_cn, style, address, city,
                  maps_url, description, source))
            place_id = cursor.lastrowid
            place_count += 1

            # Parse itinerary fields
            day_label = row.get('Day', '').strip()
            iso_date = day_label_to_date(day_label) if day_label else None
            day_num = int(day_label.replace('Day ', '')) if day_label else 0
            time_str = row.get('Time', '').strip()
            time_start, time_end = parse_time_range(time_str)
            duration = parse_duration(row.get('Duration', '').strip())
            group_region = row.get('Group', '').strip()
            notes = row.get('Notes', '').strip()
            decision = row.get('Status', 'pending').strip()
            visited = 1 if row.get('Visited', 'No').strip().lower() == 'yes' else 0
            sort_order = compute_sort_order(day_num, time_start)

            # Insert itinerary item
            cursor.execute("""
                INSERT INTO itinerary_items (trip_id, place_id, date, time_start,
                    time_end, duration_minutes, group_region, notes, decision,
                    visited, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (TRIP_ID, place_id, iso_date, time_start, time_end,
                  duration, group_region, notes, decision, visited, sort_order))
            item_count += 1

    conn.commit()
    print(f"  places: {place_count} rows inserted")
    print(f"  itinerary_items: {item_count} rows inserted")


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    import_csv(conn)
    conn.close()
