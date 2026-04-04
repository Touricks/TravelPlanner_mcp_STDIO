"""Integration tests for Markdown import (risks, todos, reservations)."""

import pytest

import import_md
from import_md import import_todos, import_risks, import_reservations


@pytest.fixture(autouse=True)
def _patch_trip_id(seeded_trip, monkeypatch):
    """Ensure import_md uses the test trip ID, not the hardcoded production one."""
    _, trip_id = seeded_trip
    monkeypatch.setattr(import_md, "TRIP_ID", trip_id)


class TestImportTodos:
    def test_count(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_todos(conn, sample_md_content)
        count = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        assert count == 3

    def test_priority_assignment(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_todos(conn, sample_md_content)
        priorities = dict(conn.execute("SELECT task, priority FROM todos").fetchall())
        assert priorities["Book flight tickets (arrive SFO by 17:00 Apr 17)"] == "high"
        assert priorities["Create packing list"] == "low"
        assert (
            priorities["Check Caltrans Highway 1 road conditions before Apr 18"]
            == "normal"
        )

    def test_category_assignment(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_todos(conn, sample_md_content)
        categories = dict(conn.execute("SELECT task, category FROM todos").fetchall())
        assert (
            categories["Book flight tickets (arrive SFO by 17:00 Apr 17)"] == "booking"
        )
        # "packing" contains "pack" → matches gear keyword
        assert categories["Create packing list"] == "gear"


class TestImportRisks:
    def test_count(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_risks(conn, sample_md_content)
        count = conn.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
        # 2 from Sequoia + 1 from Highway 1 = 3
        assert count == 3

    def test_category_mapping(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_risks(conn, sample_md_content)
        cats = dict(conn.execute("SELECT risk, category FROM risks").fetchall())
        assert cats["Tire chains in April"] == "vehicle"
        assert cats["Vehicle size restriction"] == "vehicle"
        assert cats["Landslide closures"] == "road"


class TestImportReservations:
    def test_count(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_reservations(conn, sample_md_content)
        count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        assert count == 2

    def test_cost_parsing(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_reservations(conn, sample_md_content)
        costs = dict(
            conn.execute(
                "SELECT attraction, cost_per_person FROM reservations"
            ).fetchall()
        )
        assert costs["Monterey Bay Aquarium"] == 59.95
        assert costs["Griffith Observatory"] == 0.0

    def test_booking_required(self, seeded_trip, sample_md_content):
        conn, _ = seeded_trip
        import_reservations(conn, sample_md_content)
        reqs = dict(
            conn.execute(
                "SELECT attraction, booking_required FROM reservations"
            ).fetchall()
        )
        assert reqs["Monterey Bay Aquarium"] == 1
        assert reqs["Griffith Observatory"] == 0
