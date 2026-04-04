"""Seed the hotels table from route-analysis.md accommodation recommendations.

7 stays across 8 nights (Three Rivers is a 2-night stay).
"""

import sqlite3
from pathlib import Path

TRIPDB_DIR = Path(__file__).resolve().parents[1]
DB_PATH = TRIPDB_DIR / "travel.db"
TRIP_ID = "2026-04-san-francisco"

HOTELS = [
    {
        "city": "San Francisco",
        "check_in": "2026-04-17",
        "check_out": "2026-04-18",
        "notes": "Arrival night. Near SFO or downtown SF.",
    },
    {
        "city": "Carmel-by-the-Sea",
        "check_in": "2026-04-18",
        "check_out": "2026-04-19",
        "notes": "Highway 1 Day 1 end. Monterey is an alternative.",
    },
    {
        "city": "Cambria",
        "check_in": "2026-04-19",
        "check_out": "2026-04-20",
        "notes": "Quieter and cheaper than Big Sur. Per route-analysis recommendation.",
    },
    {
        "city": "Santa Barbara",
        "check_in": "2026-04-20",
        "check_out": "2026-04-21",
        "notes": "v2 revision: stop here instead of rushing to LA. Extra 2.5h to enjoy.",
    },
    {
        "city": "Los Angeles",
        "check_in": "2026-04-21",
        "check_out": "2026-04-22",
        "notes": "LA day/evening. Near downtown or Santa Monica.",
    },
    {
        "city": "Three Rivers",
        "check_in": "2026-04-22",
        "check_out": "2026-04-24",
        "notes": "2 nights. Preferred over Wuksachi Lodge (saves 30-45min on Apr 24 return to SF).",
    },
    {
        "city": "San Francisco",
        "check_in": "2026-04-24",
        "check_out": "2026-04-25",
        "notes": "Final night. Depart 10pm Apr 25 from SFO.",
    },
]


def import_hotels(conn: sqlite3.Connection):
    """Insert 7 hotel rows."""
    cursor = conn.cursor()
    count = 0
    for h in HOTELS:
        cursor.execute("""
            INSERT INTO hotels (trip_id, city, check_in, check_out, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (TRIP_ID, h["city"], h["check_in"], h["check_out"], h["notes"]))
        count += 1
    conn.commit()
    print(f"  hotels: {count} rows inserted")

    # Verify nights sum
    total_nights = cursor.execute("SELECT SUM(nights) FROM hotels").fetchone()[0]
    print(f"  total nights: {total_nights}")


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    import_hotels(conn)
    conn.close()
