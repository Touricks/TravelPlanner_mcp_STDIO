"""Shared fixtures for the database test suite.

All tests use in-memory SQLite for speed. No production travel.db is touched.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# Add seed directory and parent to import path for modules under test
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
DB_PARENT = Path(__file__).resolve().parent.parent  # assets/database/
sys.path.insert(0, str(SEED_DIR))
sys.path.insert(0, str(DB_PARENT))


@pytest.fixture(scope="session")
def schema_sql() -> str:
    """Read schema.sql once per test session."""
    return SCHEMA_PATH.read_text(encoding="utf-8")


@pytest.fixture
def empty_db(schema_sql) -> sqlite3.Connection:
    """Fresh in-memory database with schema loaded."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql)
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture
def seeded_trip(empty_db):
    """Empty DB with one trip row inserted."""
    empty_db.execute(
        "INSERT INTO trips (id, destination, start_date, end_date) "
        "VALUES ('test-trip', 'Test Destination', '2026-04-17', '2026-04-25')"
    )
    empty_db.commit()
    yield empty_db, "test-trip"


@pytest.fixture
def sample_place(seeded_trip):
    """Seeded trip with one place and one itinerary item."""
    conn, trip_id = seeded_trip
    conn.execute(
        "INSERT INTO places (name_en, name_cn, style, address, city, description) "
        "VALUES ('Test Place', '测试地点', 'nature', '123 Test St', 'Test City', 'A test place')"
    )
    place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO itinerary_items (trip_id, place_id, date, time_start, time_end, "
        "duration_minutes, group_region, sort_order) "
        "VALUES (?, ?, '2026-04-17', '09:00', '10:00', 60, 'Test Region', 1009.0)",
        (trip_id, place_id),
    )
    item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    yield conn, trip_id, place_id, item_id


@pytest.fixture(scope="session")
def sample_md_content() -> str:
    """Hardcoded markdown content mimicking Notion export structure."""
    return """\
# Test Travel Planner

- [ ]  Book flight tickets (arrive SFO by 17:00 Apr 17)
- [ ]  Check Caltrans Highway 1 road conditions before Apr 18
- [ ]  Create packing list

### Sequoia National Park -- Vehicle & Road

| **Risk** | **Detail** | **Action Required** |
| --- | --- | --- |
| Tire chains in April | Required above 6000ft | Check rental car policy |
| Vehicle size restriction | Max 22ft on Moro Rock Rd | Confirm rental vehicle size |

### Highway 1 Big Sur -- Road Status

| **Risk** | **Detail** | **Action Required** |
| --- | --- | --- |
| Landslide closures | Reopened Jan 2026 | Check Caltrans before Apr 18 |

### Advance Tickets & Reservations

| **Attraction** | **Booking Required?** | **Cost** | **Book How Far Ahead** |
| --- | --- | --- | --- |
| Monterey Bay Aquarium | Yes -- timed entry tickets required | $59.95/adult | 2-3 weeks ahead |
| Griffith Observatory | No -- free admission, no tickets | Free (parking $10/hr) | No booking |
"""


@pytest.fixture
def db_file(tmp_path, schema_sql):
    """File-based SQLite DB for CLI integration tests.

    CliRunner invokes click commands that open their own connections,
    so we need a file path (not an in-memory connection).
    """
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO trips (id, destination, start_date, end_date) "
        "VALUES ('test-trip', 'Test Destination', '2026-04-17', '2026-04-25')"
    )
    conn.commit()
    conn.close()
    return db_path
