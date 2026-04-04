"""Master import orchestrator: create travel.db and seed all tables.

Usage: python -m tripdb.seed.import_all
"""

import sqlite3
import sys
from pathlib import Path

TRIPDB_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = TRIPDB_DIR / "schema.sql"
DB_PATH = TRIPDB_DIR / "travel.db"

# Add seed directory to path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))
from import_csv import import_csv
from import_hotels import import_hotels
from import_md import import_md


def create_database() -> sqlite3.Connection:
    """Create fresh database from schema.sql."""
    # Remove existing DB for clean rebuild
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH.name}")

    conn = sqlite3.connect(DB_PATH)
    schema = SCHEMA_PATH.read_text(encoding='utf-8')
    conn.executescript(schema)
    print(f"Created {DB_PATH.name} from schema.sql")
    return conn


def validate(conn: sqlite3.Connection):
    """Run validation queries and print results."""
    print("\n=== Validation ===")

    # Row counts
    tables = ['trips', 'places', 'itinerary_items', 'hotels', 'risks', 'todos', 'reservations']
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count}")

    # Hotel nights
    total_nights = conn.execute("SELECT SUM(nights) FROM hotels").fetchone()[0]
    print(f"  total hotel nights: {total_nights}")

    # View counts
    print("\n=== Views ===")
    views = {
        'v_full_itinerary': None,
        'v_foods': None,
        'v_attractions': None,
        'v_hotels': None,
        'open_risks': None,
        'incomplete_todos': None,
        'v_pending_sync': None,
        'v_reservations': None,
    }
    for view in views:
        count = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        print(f"  {view}: {count}")

    # Style distribution
    print("\n=== Style Distribution ===")
    rows = conn.execute(
        "SELECT style, COUNT(*) FROM places GROUP BY style ORDER BY COUNT(*) DESC"
    ).fetchall()
    for style, count in rows:
        print(f"  {style}: {count}")

    # Day schedule smoke test
    print("\n=== Day 3 Schedule (smoke test) ===")
    rows = conn.execute("""
        SELECT name_en, time_start, style, city
        FROM v_full_itinerary WHERE day_num = 3
        ORDER BY time_start
    """).fetchall()
    for name, time, style, city in rows:
        print(f"  {time or '??:??'} {name} ({style}, {city})")


def main():
    print("=" * 60)
    print("Travel Planner — Database Import")
    print("=" * 60)

    # Step 1: Create DB
    print("\n[1/4] Creating database...")
    conn = create_database()
    conn.execute("PRAGMA foreign_keys=ON")

    # Step 2: Import CSV (trip + places + itinerary_items)
    print("\n[2/4] Importing CSV (places + itinerary items)...")
    import_csv(conn)

    # Step 3: Import hotels
    print("\n[3/4] Importing hotels...")
    import_hotels(conn)

    # Step 4: Import MD (risks + todos + reservations)
    print("\n[4/4] Importing markdown (risks + todos + reservations)...")
    import_md(conn)

    # Validate
    validate(conn)

    conn.close()
    print(f"\nDone. Database at: {DB_PATH}")


if __name__ == '__main__':
    main()
