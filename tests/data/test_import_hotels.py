"""Integration tests for hotel import."""

import import_hotels
from import_hotels import import_hotels as run_import


class TestImportHotels:
    def test_count(self, seeded_trip, monkeypatch):
        conn, trip_id = seeded_trip
        monkeypatch.setattr(import_hotels, "TRIP_ID", trip_id)
        run_import(conn)
        count = conn.execute("SELECT COUNT(*) FROM hotels").fetchone()[0]
        assert count == 7

    def test_total_nights(self, seeded_trip, monkeypatch):
        conn, trip_id = seeded_trip
        monkeypatch.setattr(import_hotels, "TRIP_ID", trip_id)
        run_import(conn)
        total = conn.execute("SELECT SUM(nights) FROM hotels").fetchone()[0]
        assert total == 8

    def test_three_rivers_two_nights(self, seeded_trip, monkeypatch):
        conn, trip_id = seeded_trip
        monkeypatch.setattr(import_hotels, "TRIP_ID", trip_id)
        run_import(conn)
        nights = conn.execute(
            "SELECT nights FROM hotels WHERE city='Three Rivers'"
        ).fetchone()[0]
        assert nights == 2

    def test_no_gaps_in_coverage(self, seeded_trip, monkeypatch):
        """Each check_out equals the next check_in — no missing nights."""
        conn, trip_id = seeded_trip
        monkeypatch.setattr(import_hotels, "TRIP_ID", trip_id)
        run_import(conn)
        rows = conn.execute(
            "SELECT check_in, check_out FROM hotels ORDER BY check_in"
        ).fetchall()
        for i in range(len(rows) - 1):
            assert rows[i][1] == rows[i + 1][0], (
                f"Gap: {rows[i][1]} != {rows[i + 1][0]}"
            )
