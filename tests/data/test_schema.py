"""Schema, trigger, view, and constraint tests.

All tests use in-memory SQLite via conftest fixtures.
"""

import sqlite3

import pytest


# ── Table / View / Trigger existence ────────────────────────


class TestSchemaCreation:
    def test_all_tables_exist(self, empty_db):
        tables = {
            r[0]
            for r in empty_db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        expected = {
            "trips", "places", "itinerary_items", "hotels",
            "risks", "reservations", "todos", "audit_log",
            "sessions", "session_places", "bridge_sync",
        }
        assert tables == expected

    def test_all_views_exist(self, empty_db):
        views = {
            r[0]
            for r in empty_db.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        }
        expected = {
            "v_full_itinerary", "v_foods", "v_attractions", "v_hotels",
            "day_summary", "open_risks", "incomplete_todos",
            "unscheduled_places", "v_pending_sync", "v_reservations",
        }
        assert views == expected

    def test_all_triggers_exist(self, empty_db):
        triggers = {
            r[0]
            for r in empty_db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        # 6 updated_at + 3 sync_dirty = 9
        assert len(triggers) == 9
        assert "places_sync_dirty" in triggers
        assert "itinerary_sync_dirty" in triggers
        assert "hotels_sync_dirty" in triggers


# ── UUID generation ─────────────────────────────────────────


class TestUUID:
    def test_auto_generated_on_insert(self, seeded_trip):
        conn, _ = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Test', 'nature')")
        uuid = conn.execute("SELECT uuid FROM places WHERE name_en='Test'").fetchone()[0]
        assert uuid is not None
        assert len(uuid) == 36
        assert uuid[14] == "4"  # UUID v4 marker

    def test_unique_across_rows(self, seeded_trip):
        conn, _ = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('A', 'nature')")
        conn.execute("INSERT INTO places (name_en, style) VALUES ('B', 'nature')")
        uuids = [r[0] for r in conn.execute("SELECT uuid FROM places").fetchall()]
        assert len(set(uuids)) == len(uuids)


# ── Foreign key enforcement ─────────────────────────────────


class TestForeignKeys:
    def test_itinerary_requires_valid_trip(self, empty_db):
        empty_db.execute("INSERT INTO places (name_en, style) VALUES ('X', 'nature')")
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO itinerary_items (trip_id, place_id, date) "
                "VALUES ('nonexistent', 1, '2026-04-17')"
            )

    def test_itinerary_requires_valid_place(self, seeded_trip):
        conn, trip_id = seeded_trip
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO itinerary_items (trip_id, place_id, date) "
                "VALUES (?, 9999, '2026-04-17')",
                (trip_id,),
            )

    def test_hotel_requires_valid_trip(self, empty_db):
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO hotels (trip_id, city, check_in, check_out) "
                "VALUES ('bad', 'SF', '2026-04-17', '2026-04-18')"
            )


# ── CHECK constraints ───────────────────────────────────────


class TestCheckConstraints:
    def test_invalid_style_rejected(self, seeded_trip):
        conn, _ = seeded_trip
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO places (name_en, style) VALUES ('X', 'invalid')")

    def test_invalid_sync_status_rejected(self, seeded_trip):
        conn, _ = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('X', 'nature')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE places SET sync_status='bogus' WHERE name_en='X'")

    def test_invalid_decision_rejected(self, sample_place):
        conn, _, _, item_id = sample_place
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE itinerary_items SET decision='maybe' WHERE id=?", (item_id,)
            )

    def test_invalid_risk_category_rejected(self, seeded_trip):
        conn, trip_id = seeded_trip
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO risks (trip_id, category, risk) VALUES (?, 'invalid', 'test')",
                (trip_id,),
            )


# ── updated_at trigger ──────────────────────────────────────


class TestUpdatedAtTrigger:
    def test_auto_updates_on_change(self, sample_place):
        conn, _, place_id, _ = sample_place
        original = conn.execute(
            "SELECT updated_at FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        conn.execute("UPDATE places SET name_en='Changed' WHERE id=?", (place_id,))
        new_ts = conn.execute(
            "SELECT updated_at FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert new_ts >= original

    def test_no_infinite_recursion(self, sample_place):
        """The WHEN guard prevents trigger from recursing."""
        conn, _, place_id, _ = sample_place
        conn.execute("UPDATE places SET description='new desc' WHERE id=?", (place_id,))
        count = conn.execute(
            "SELECT COUNT(*) FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert count == 1


# ── sync_status dirty trigger ───────────────────────────────


class TestSyncDirtyTrigger:
    def test_content_change_marks_modified(self, sample_place):
        conn, _, place_id, _ = sample_place
        conn.execute("UPDATE places SET sync_status='synced' WHERE id=?", (place_id,))
        conn.execute("UPDATE places SET name_en='New Name' WHERE id=?", (place_id,))
        status = conn.execute(
            "SELECT sync_status FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert status == "modified"

    def test_untracked_field_stays_synced(self, sample_place):
        conn, _, place_id, _ = sample_place
        conn.execute("UPDATE places SET sync_status='synced' WHERE id=?", (place_id,))
        conn.execute("UPDATE places SET lat=37.7749 WHERE id=?", (place_id,))
        status = conn.execute(
            "SELECT sync_status FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert status == "synced"

    def test_only_fires_when_synced(self, sample_place):
        """Dirty trigger only fires when OLD.sync_status='synced', not 'pending'."""
        conn, _, place_id, _ = sample_place
        conn.execute("UPDATE places SET name_en='Changed' WHERE id=?", (place_id,))
        status = conn.execute(
            "SELECT sync_status FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert status == "pending"

    def test_itinerary_date_change_marks_modified(self, sample_place):
        conn, _, _, item_id = sample_place
        conn.execute(
            "UPDATE itinerary_items SET sync_status='synced' WHERE id=?", (item_id,)
        )
        conn.execute(
            "UPDATE itinerary_items SET date='2026-04-20' WHERE id=?", (item_id,)
        )
        status = conn.execute(
            "SELECT sync_status FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        assert status == "modified"

    def test_hotel_city_change_marks_modified(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'SF', '2026-04-17', '2026-04-18')",
            (trip_id,),
        )
        hotel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE hotels SET sync_status='synced' WHERE id=?", (hotel_id,))
        conn.execute("UPDATE hotels SET city='Oakland' WHERE id=?", (hotel_id,))
        status = conn.execute(
            "SELECT sync_status FROM hotels WHERE id=?", (hotel_id,)
        ).fetchone()[0]
        assert status == "modified"

    def test_sync_lifecycle_full_cycle(self, sample_place):
        """Verify the full sync lifecycle: pending → synced → modified → synced.

        TODO: This is your contribution opportunity!
        Trace the complete sync state machine for a place record.
        Think about: which fields are "tracked" (trigger dirty) vs untracked (no effect)?
        The tracked fields for places are: name_en, name_cn, style, address, description.
        Untracked: lat, lng, maps_url, source, city.
        """
        conn, _, place_id, _ = sample_place

        # Step 1: Verify initial state is 'pending'
        status = conn.execute(
            "SELECT sync_status FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        assert status == "pending"

        # Step 2: Simulate a successful Notion push → 'synced'
        conn.execute("UPDATE places SET sync_status='synced' WHERE id=?", (place_id,))
        assert conn.execute("SELECT sync_status FROM places WHERE id=?", (place_id,)).fetchone()[0] == "synced"

        # Step 3: Change a TRACKED field (name_en) → trigger flips to 'modified'
        conn.execute("UPDATE places SET name_en='Renamed Place' WHERE id=?", (place_id,))
        assert conn.execute("SELECT sync_status FROM places WHERE id=?", (place_id,)).fetchone()[0] == "modified"

        # Step 4: Simulate re-push → back to 'synced'
        conn.execute("UPDATE places SET sync_status='synced' WHERE id=?", (place_id,))
        assert conn.execute("SELECT sync_status FROM places WHERE id=?", (place_id,)).fetchone()[0] == "synced"

        # Step 5: Change an UNTRACKED field (lat) → should stay 'synced'
        conn.execute("UPDATE places SET lat=37.7749 WHERE id=?", (place_id,))
        assert conn.execute("SELECT sync_status FROM places WHERE id=?", (place_id,)).fetchone()[0] == "synced"


# ── Generated column (hotels.nights) ────────────────────────


class TestHotelNights:
    def test_single_night(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'SF', '2026-04-17', '2026-04-18')",
            (trip_id,),
        )
        nights = conn.execute("SELECT nights FROM hotels WHERE city='SF'").fetchone()[0]
        assert nights == 1

    def test_multi_night(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'Three Rivers', '2026-04-22', '2026-04-24')",
            (trip_id,),
        )
        nights = conn.execute(
            "SELECT nights FROM hotels WHERE city='Three Rivers'"
        ).fetchone()[0]
        assert nights == 2


# ── View behavior ───────────────────────────────────────────


class TestViews:
    def test_full_itinerary_excludes_rejected(self, sample_place):
        conn, _, _, item_id = sample_place
        conn.execute(
            "UPDATE itinerary_items SET decision='rejected' WHERE id=?", (item_id,)
        )
        count = conn.execute("SELECT COUNT(*) FROM v_full_itinerary").fetchone()[0]
        assert count == 0

    def test_full_itinerary_excludes_soft_deleted(self, sample_place):
        conn, _, _, item_id = sample_place
        conn.execute(
            "UPDATE itinerary_items SET deleted_at=datetime('now') WHERE id=?",
            (item_id,),
        )
        count = conn.execute("SELECT COUNT(*) FROM v_full_itinerary").fetchone()[0]
        assert count == 0

    def test_full_itinerary_computes_day_num(self, sample_place):
        conn, *_ = sample_place
        row = conn.execute("SELECT day_num FROM v_full_itinerary").fetchone()
        assert row[0] == 1  # date='2026-04-17' = trip start = Day 1

    def test_type_mapping_food_to_food(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Cafe', 'coffee')")
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO itinerary_items (trip_id, place_id, date) "
            "VALUES (?, ?, '2026-04-17')",
            (trip_id, pid),
        )
        typ = conn.execute(
            "SELECT type FROM v_full_itinerary WHERE name_en='Cafe'"
        ).fetchone()[0]
        assert typ == "Food"

    def test_type_mapping_nature_to_attractions(self, sample_place):
        conn, *_ = sample_place
        typ = conn.execute("SELECT type FROM v_full_itinerary").fetchone()[0]
        assert typ == "Attractions"

    def test_v_foods_filters_correctly(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Cafe', 'coffee')")
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Park', 'nature')")
        for name in ("Cafe", "Park"):
            pid = conn.execute(
                "SELECT id FROM places WHERE name_en=?", (name,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO itinerary_items (trip_id, place_id, date) "
                "VALUES (?, ?, '2026-04-17')",
                (trip_id, pid),
            )
        count = conn.execute("SELECT COUNT(*) FROM v_foods").fetchone()[0]
        assert count == 1

    def test_unscheduled_places(self, seeded_trip):
        conn, _ = seeded_trip
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Orphan', 'nature')")
        count = conn.execute("SELECT COUNT(*) FROM unscheduled_places").fetchone()[0]
        assert count == 1

    def test_open_risks_filters(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO risks (trip_id, category, risk, status) "
            "VALUES (?, 'road', 'A', 'open')",
            (trip_id,),
        )
        conn.execute(
            "INSERT INTO risks (trip_id, category, risk, status) "
            "VALUES (?, 'road', 'B', 'resolved')",
            (trip_id,),
        )
        count = conn.execute("SELECT COUNT(*) FROM open_risks").fetchone()[0]
        assert count == 1

    def test_incomplete_todos_priority_order(self, seeded_trip):
        conn, trip_id = seeded_trip
        for priority in ("low", "critical", "normal", "high"):
            conn.execute(
                "INSERT INTO todos (trip_id, task, priority) VALUES (?, ?, ?)",
                (trip_id, f"Task {priority}", priority),
            )
        rows = conn.execute("SELECT task FROM incomplete_todos").fetchall()
        assert [r[0] for r in rows] == [
            "Task critical", "Task high", "Task normal", "Task low"
        ]

    def test_v_pending_sync_includes_pending(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'SF', '2026-04-17', '2026-04-18')",
            (trip_id,),
        )
        count = conn.execute("SELECT COUNT(*) FROM v_pending_sync").fetchone()[0]
        assert count == 1

    def test_v_pending_sync_excludes_synced(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'SF', '2026-04-17', '2026-04-18')",
            (trip_id,),
        )
        conn.execute("UPDATE hotels SET sync_status='synced'")
        count = conn.execute("SELECT COUNT(*) FROM v_pending_sync").fetchone()[0]
        assert count == 0

    def test_v_hotels_day_num(self, seeded_trip):
        conn, trip_id = seeded_trip
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'Three Rivers', '2026-04-22', '2026-04-24')",
            (trip_id,),
        )
        row = conn.execute("SELECT day_num_in, day_num_out FROM v_hotels").fetchone()
        assert row[0] == 6  # Apr 22 = Day 6
        assert row[1] == 8  # Apr 24 = Day 8
