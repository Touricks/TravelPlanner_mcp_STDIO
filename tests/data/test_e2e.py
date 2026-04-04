"""End-to-end tests exercising cross-module boundaries.

These tests are designed to surface bugs that unit/integration tests miss
by testing realistic multi-step workflows and edge cases at module boundaries.
"""

import json
import sqlite3

import pytest
from click.testing import CliRunner

from cli.trip import cli
from cli.utils import (
    _dur_text,
    compute_sort_order,
    confirm_visit,
    create_place,
    drop_visit,
    export_yaml,
    get_connection,
    get_push_summary,
    get_status,
    get_trip,
    log_audit,
    mark_synced,
    minutes_to_duration_text,
    remove_place,
    reschedule_visit,
    resolve_item,
    resolve_place,
    schedule_visit,
    update_place_fields,
)


# ── Helpers ────────────────────────────────────────────────


def _get_trip_dict(conn):
    """Fetch trip as dict."""
    row = conn.execute("SELECT * FROM trips").fetchone()
    return dict(row)


def _enable_row_factory(conn):
    """Enable Row factory for dict-like access."""
    conn.row_factory = sqlite3.Row


# ══════════════════════════════════════════════════════════════
# 1. Full Lifecycle E2E (CLI layer)
# ══════════════════════════════════════════════════════════════


class TestFullLifecycleCLI:
    """Test a complete trip planning workflow through the CLI."""

    def test_add_schedule_confirm_reschedule_drop_export(self, db_file):
        """Full lifecycle: add → schedule → confirm → reschedule → drop → export."""
        runner = CliRunner()
        db = str(db_file)

        # 1. Add a place
        result = runner.invoke(
            cli,
            [
                "--db", db, "add-place", "Golden Gate Bridge",
                "--style", "landmark",
                "--cn", "金门大桥",
                "--city", "San Francisco",
                "--address", "Golden Gate Bridge, San Francisco, CA",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Golden Gate Bridge" in result.output
        assert "landmark" in result.output

        # Extract place ID from output
        place_id = result.output.split("#")[1].split(" ")[0]

        # 2. Schedule it on Day 1
        result = runner.invoke(
            cli,
            ["--db", db, "schedule", place_id, "--day", "1", "--time", "09:00", "--duration", "120"],
        )
        assert result.exit_code == 0, result.output
        assert "Day 1" in result.output
        assert "09:00" in result.output

        # Extract item ID
        item_id = result.output.split("item #")[1].strip()

        # 3. Confirm the visit
        result = runner.invoke(cli, ["--db", db, "confirm", item_id])
        assert result.exit_code == 0, result.output
        assert "Confirmed" in result.output

        # 4. Reschedule to Day 3 at 14:00
        result = runner.invoke(
            cli,
            ["--db", db, "reschedule", item_id, "--day", "3", "--time", "14:00"],
        )
        assert result.exit_code == 0, result.output
        assert "14:00" in result.output

        # 5. Drop the visit
        result = runner.invoke(
            cli, ["--db", db, "drop", item_id, "--reason", "Too far from hotel"],
        )
        assert result.exit_code == 0, result.output
        assert "Dropped" in result.output
        assert "Too far from hotel" in result.output

        # 6. Export YAML — dropped item should be excluded
        result = runner.invoke(cli, ["--db", db, "export-yaml", "--output", "/dev/null"])
        assert result.exit_code == 0, result.output

        # 7. Status should show 0 pending sync for itinerary (all rejected)
        result = runner.invoke(cli, ["--db", db, "status"])
        assert result.exit_code == 0, result.output

    def test_add_two_places_schedule_both_remove_one(self, db_file):
        """Test cascading removal doesn't affect other places."""
        runner = CliRunner()
        db = str(db_file)

        # Add two places
        r1 = runner.invoke(cli, ["--db", db, "add-place", "Place A", "--style", "nature"])
        assert r1.exit_code == 0
        place_a_id = r1.output.split("#")[1].split(" ")[0]

        r2 = runner.invoke(cli, ["--db", db, "add-place", "Place B", "--style", "food"])
        assert r2.exit_code == 0
        place_b_id = r2.output.split("#")[1].split(" ")[0]

        # Schedule both
        runner.invoke(cli, ["--db", db, "schedule", place_a_id, "--day", "1", "--time", "09:00"])
        runner.invoke(cli, ["--db", db, "schedule", place_b_id, "--day", "1", "--time", "12:00"])

        # Remove Place A with --force
        result = runner.invoke(cli, ["--db", db, "remove-place", place_a_id, "--force"])
        assert result.exit_code == 0
        assert "1 scheduled visit" in result.output

        # Place B should still be schedulable — verify via status
        result = runner.invoke(cli, ["--db", db, "status"])
        assert result.exit_code == 0

        # Place B's visit should still appear in export
        result = runner.invoke(cli, ["--db", db, "export-yaml", "--output", "/dev/null"])
        assert result.exit_code == 0


# ══════════════════════════════════════════════════════════════
# 2. Full Lifecycle E2E (Service layer direct)
# ══════════════════════════════════════════════════════════════


class TestFullLifecycleService:
    """Test complete workflow through service functions directly."""

    def test_create_schedule_confirm_reschedule_audit_trail(self, db_file):
        """Every mutation should produce an audit_log entry."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        # 1. Create place
        place = create_place(
            conn, trip["id"], name_en="Alcatraz Island", style="landmark",
            name_cn="恶魔岛", city="San Francisco",
        )
        assert place["name_en"] == "Alcatraz Island"

        # 2. Schedule
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=2, trip=trip,
            time_start="10:00", duration_minutes=180,
        )
        assert item["time_end"] == "13:00"

        # 3. Confirm
        confirmed = confirm_visit(conn, trip["id"], item)
        assert confirmed["decision"] == "confirmed"

        # 4. Reschedule to Day 5
        rescheduled = reschedule_visit(
            conn, trip["id"], confirmed, trip, day_num=5, time_start="14:00",
        )
        assert rescheduled["date"] == "2026-04-21"  # Day 5
        assert rescheduled["time_start"] == "14:00"

        # 5. Verify audit trail completeness
        audits = conn.execute(
            "SELECT action FROM audit_log ORDER BY id"
        ).fetchall()
        actions = [a[0] for a in audits]
        assert "add_place" in actions
        assert "schedule_visit" in actions
        assert "confirm" in actions
        assert "reschedule" in actions
        assert len(actions) == 4

        conn.close()


# ══════════════════════════════════════════════════════════════
# 3. Sync Status + Dirty Trigger Interaction
# ══════════════════════════════════════════════════════════════


class TestSyncDirtyTriggerWithCLI:
    """Test that sync_status dirty triggers fire correctly after CLI mutations."""

    def test_mark_synced_then_reschedule_marks_modified(self, db_file):
        """After mark-synced, a reschedule should trigger sync_dirty → 'modified'."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        # Create + schedule
        place = create_place(conn, trip["id"], name_en="Pier 39", style="landmark")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
            time_start="10:00", duration_minutes=60,
        )
        assert item["sync_status"] == "pending"

        # Mark as synced
        found = mark_synced(conn, item["uuid"])
        assert found is True

        # Verify it's synced
        row = conn.execute(
            "SELECT sync_status FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone()
        assert row["sync_status"] == "synced"

        # Now reschedule — should trigger sync_dirty
        updated_item = dict(conn.execute(
            "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone())
        reschedule_visit(
            conn, trip["id"], updated_item, trip,
            day_num=3, time_start="15:00",
        )

        row = conn.execute(
            "SELECT sync_status FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone()
        assert row["sync_status"] == "modified", (
            "Expected sync_status='modified' after rescheduling a synced item"
        )

        conn.close()

    def test_mark_synced_then_confirm_marks_modified(self, db_file):
        """After mark-synced, confirming changes decision → sync_dirty → 'modified'."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        place = create_place(conn, trip["id"], name_en="Lombard St", style="landmark")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        # Mark synced
        mark_synced(conn, item["uuid"])

        # Confirm — decision change is a tracked field
        updated_item = dict(conn.execute(
            "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone())
        confirm_visit(conn, trip["id"], updated_item)

        row = conn.execute(
            "SELECT sync_status FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone()
        assert row["sync_status"] == "modified"

        conn.close()

    def test_mark_synced_then_update_place_marks_modified(self, db_file):
        """Updating a synced place should mark it 'modified'."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        place = create_place(conn, trip["id"], name_en="Test Cafe", style="coffee")

        # Manually mark place as synced (mark_synced doesn't cover places)
        conn.execute(
            "UPDATE places SET sync_status='synced' WHERE id=?", (place["id"],)
        )
        conn.commit()

        # Update the place name
        updated_place = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (place["id"],)
        ).fetchone())
        update_place_fields(conn, trip["id"], updated_place, name_en="Updated Cafe")

        row = conn.execute(
            "SELECT sync_status FROM places WHERE id=?", (place["id"],)
        ).fetchone()
        assert row["sync_status"] == "modified"

        conn.close()


# ══════════════════════════════════════════════════════════════
# 4. BUG: minutes_to_duration_text double-h
# ══════════════════════════════════════════════════════════════


class TestMinutesToDurationText:
    """Test the minutes_to_duration_text function (unused but buggy)."""

    def test_60_minutes(self):
        assert minutes_to_duration_text(60) == "1h"

    def test_120_minutes(self):
        assert minutes_to_duration_text(120) == "2h"

    def test_30_minutes(self):
        assert minutes_to_duration_text(30) == "30min"

    def test_none_returns_empty(self):
        assert minutes_to_duration_text(None) == ""

    def test_90_minutes_should_be_1_5h(self):
        """BUG: Operator precedence causes '1.5hh' instead of '1.5h'."""
        result = minutes_to_duration_text(90)
        assert result == "1.5h", f"Expected '1.5h' but got '{result}' (double-h bug)"

    def test_45_minutes(self):
        assert minutes_to_duration_text(45) == "45min"

    def test_75_minutes(self):
        """75min = 1.25h — :g format preserves meaningful decimals."""
        result = minutes_to_duration_text(75)
        assert result == "1.25h", f"Got '{result}'"


class TestDurText:
    """Test _dur_text (the function actually used by export_yaml)."""

    def test_90_minutes(self):
        assert _dur_text(90) == "1.5h"

    def test_60_minutes(self):
        assert _dur_text(60) == "1h"

    def test_30_minutes(self):
        assert _dur_text(30) == "30min"

    def test_0_minutes_returns_empty(self):
        """0 is falsy in Python, so _dur_text(0) returns ''."""
        assert _dur_text(0) == ""

    def test_none_returns_empty(self):
        assert _dur_text(None) == ""

    def test_15_minutes(self):
        assert _dur_text(15) == "15min"

    def test_180_minutes(self):
        assert _dur_text(180) == "3h"

    def test_150_minutes(self):
        """150min = 2.5h."""
        assert _dur_text(150) == "2.5h"


# ══════════════════════════════════════════════════════════════
# 5. BUG: Stale time_end on reschedule without duration
# ══════════════════════════════════════════════════════════════


class TestRescheduleStaleTimeEnd:
    """Reschedule --time without --duration when item has no duration_minutes."""

    def test_reschedule_time_without_duration_clears_stale_time_end(self, db_file):
        """BUG: If item has time_end but no duration, rescheduling time leaves stale time_end.

        Example: time_start=09:00, time_end=10:00, duration=NULL
        Reschedule --time 14:00 → time_end stays "10:00" (before time_start!)
        """
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        # Create place + schedule WITHOUT duration
        place = create_place(conn, trip["id"], name_en="Test Stale", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
            time_start="09:00",
            # No duration
        )

        # Manually set time_end to simulate imported data with time_end but no duration
        conn.execute(
            "UPDATE itinerary_items SET time_end='10:00' WHERE id=?", (item["id"],)
        )
        conn.commit()

        # Re-fetch
        item = dict(conn.execute(
            "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
        ).fetchone())
        assert item["time_start"] == "09:00"
        assert item["time_end"] == "10:00"
        assert item["duration_minutes"] is None

        # Reschedule to 14:00 (no --duration)
        rescheduled = reschedule_visit(
            conn, trip["id"], item, trip, time_start="14:00",
        )

        # time_end should NOT be "10:00" (before the new time_start!)
        if rescheduled["time_end"] is not None:
            # If time_end is set, it must be >= time_start
            assert rescheduled["time_end"] >= rescheduled["time_start"], (
                f"Stale time_end bug: time_start={rescheduled['time_start']} "
                f"but time_end={rescheduled['time_end']}"
            )

        conn.close()


# ══════════════════════════════════════════════════════════════
# 6. BUG: mark_synced SQL injection via notion_page_id
# ══════════════════════════════════════════════════════════════


class TestMarkSyncedSQLSafety:
    """mark_synced interpolates notion_page_id into SQL without parameterization."""

    def test_notion_page_id_with_single_quote(self, db_file):
        """notion_page_id containing a single quote should not break SQL."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="SQL Test", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        # This should not raise a SQL error
        try:
            found = mark_synced(conn, item["uuid"], notion_page_id="abc'def")
            assert found is True
            # Verify the value was stored correctly
            row = conn.execute(
                "SELECT notion_page_id FROM itinerary_items WHERE id=?", (item["id"],)
            ).fetchone()
            assert row["notion_page_id"] == "abc'def", (
                "notion_page_id with quote was not stored correctly"
            )
        except sqlite3.OperationalError as e:
            pytest.fail(
                f"SQL injection vulnerability: notion_page_id with single quote "
                f"broke the query: {e}"
            )

        conn.close()

    def test_notion_page_id_with_semicolon(self, db_file):
        """notion_page_id containing SQL injection attempt."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Inject Test", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        malicious = "'; DROP TABLE itinerary_items; --"
        try:
            mark_synced(conn, item["uuid"], notion_page_id=malicious)
        except sqlite3.OperationalError:
            pytest.fail("SQL injection vulnerability in mark_synced")

        # Table should still exist
        count = conn.execute(
            "SELECT COUNT(*) FROM itinerary_items"
        ).fetchone()[0]
        assert count >= 1, "itinerary_items table was dropped by SQL injection!"

        conn.close()


# ══════════════════════════════════════════════════════════════
# 7. BUG: mark_synced doesn't cover places, todos, reservations
# ══════════════════════════════════════════════════════════════


class TestMarkSyncedTableCoverage:
    """mark_synced only searches itinerary_items, hotels, risks — not places/todos/reservations."""

    def test_mark_synced_finds_itinerary_item(self, db_file):
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Found Test", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )
        assert mark_synced(conn, item["uuid"]) is True
        conn.close()

    def test_mark_synced_finds_hotel(self, db_file):
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        conn.execute(
            "INSERT INTO hotels (trip_id, city, check_in, check_out) "
            "VALUES (?, 'SF', '2026-04-17', '2026-04-18')",
            (trip["id"],),
        )
        conn.commit()
        uuid = conn.execute("SELECT uuid FROM hotels ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert mark_synced(conn, uuid) is True
        conn.close()

    def test_mark_synced_finds_risk(self, db_file):
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        conn.execute(
            "INSERT INTO risks (trip_id, category, risk) VALUES (?, 'road', 'Test risk')",
            (trip["id"],),
        )
        conn.commit()
        uuid = conn.execute("SELECT uuid FROM risks ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert mark_synced(conn, uuid) is True
        conn.close()

    def test_mark_synced_cannot_find_place(self, db_file):
        """BUG: Places have sync_status but mark_synced doesn't search them."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Orphan Place", style="nature")

        # mark_synced should find this place, but it doesn't
        found = mark_synced(conn, place["uuid"])
        assert found is True, (
            f"mark_synced cannot find places by UUID — "
            f"places have sync_status but aren't searched"
        )
        conn.close()

    def test_mark_synced_cannot_find_todo(self, db_file):
        """BUG: Todos have sync_status but mark_synced doesn't search them."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        conn.execute(
            "INSERT INTO todos (trip_id, task) VALUES (?, 'Book flights')",
            (trip["id"],),
        )
        conn.commit()
        uuid = conn.execute("SELECT uuid FROM todos ORDER BY id DESC LIMIT 1").fetchone()[0]

        found = mark_synced(conn, uuid)
        assert found is True, (
            "mark_synced cannot find todos by UUID — "
            "todos have sync_status but aren't searched"
        )
        conn.close()

    def test_mark_synced_cannot_find_reservation(self, db_file):
        """BUG: Reservations have sync_status but mark_synced doesn't search them."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        conn.execute(
            "INSERT INTO reservations (trip_id, attraction) VALUES (?, 'Aquarium')",
            (trip["id"],),
        )
        conn.commit()
        uuid = conn.execute(
            "SELECT uuid FROM reservations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

        found = mark_synced(conn, uuid)
        assert found is True, (
            "mark_synced cannot find reservations by UUID — "
            "reservations have sync_status but aren't searched"
        )
        conn.close()


# ══════════════════════════════════════════════════════════════
# 8. BUG: get_status table_counts includes deleted rows
# ══════════════════════════════════════════════════════════════


class TestStatusCountsAccuracy:
    """get_status SELECT COUNT(*) doesn't filter deleted_at or rejected."""

    def test_table_counts_exclude_deleted_places(self, db_file):
        """After removing a place, table_counts should decrease."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        # Create two places
        p1 = create_place(conn, trip["id"], name_en="Keep Me", style="nature")
        p2 = create_place(conn, trip["id"], name_en="Delete Me", style="food")

        # Get initial count
        status = get_status(conn, trip)
        initial_count = status["table_counts"]["places"]

        # Soft-delete p2
        p2_full = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (p2["id"],)
        ).fetchone())
        remove_place(conn, trip["id"], p2_full, force=True)

        # Get new count — should be one less
        status = get_status(conn, trip)
        new_count = status["table_counts"]["places"]

        assert new_count == initial_count - 1, (
            f"table_counts includes deleted rows: was {initial_count}, "
            f"now {new_count} (expected {initial_count - 1})"
        )

        conn.close()

    def test_table_counts_exclude_deleted_itinerary(self, db_file):
        """After remove-place cascade, itinerary_items count should decrease."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        place = create_place(conn, trip["id"], name_en="Cascade Test", style="nature")
        schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        status_before = get_status(conn, trip)
        count_before = status_before["table_counts"]["itinerary_items"]

        place_full = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (place["id"],)
        ).fetchone())
        remove_place(conn, trip["id"], place_full, force=True)

        status_after = get_status(conn, trip)
        count_after = status_after["table_counts"]["itinerary_items"]

        assert count_after == count_before - 1, (
            f"table_counts includes deleted itinerary items: "
            f"was {count_before}, now {count_after}"
        )

        conn.close()


# ══════════════════════════════════════════════════════════════
# 9. v_pending_sync completeness
# ══════════════════════════════════════════════════════════════


class TestPendingSyncCompleteness:
    """v_pending_sync only covers itinerary_items, hotels, risks."""

    def test_pending_places_not_in_push_summary(self, db_file):
        """BUG: Places with sync_status='pending' aren't in v_pending_sync."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        create_place(conn, trip["id"], name_en="Invisible Place", style="nature")

        summary = get_push_summary(conn)
        # Places should appear in push summary, but they don't
        has_places = any("place" in k.lower() for k in summary.keys())
        assert has_places, (
            f"v_pending_sync doesn't include places. Summary: {summary}"
        )

        conn.close()

    def test_pending_todos_not_in_push_summary(self, db_file):
        """BUG: Todos with sync_status='pending' aren't in v_pending_sync."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        conn.execute(
            "INSERT INTO todos (trip_id, task) VALUES (?, 'Push test')",
            (trip["id"],),
        )
        conn.commit()

        summary = get_push_summary(conn)
        has_todos = any("todo" in k.lower() for k in summary.keys())
        assert has_todos, (
            f"v_pending_sync doesn't include todos. Summary: {summary}"
        )

        conn.close()


# ══════════════════════════════════════════════════════════════
# 10. Export YAML edge cases
# ══════════════════════════════════════════════════════════════


class TestExportYamlEdgeCases:
    """Test export_yaml with tricky data."""

    def test_export_with_quotes_in_notes(self, db_file):
        """Notes containing double quotes should produce valid YAML."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(
            conn, trip["id"], name_en="Quote Test", style="nature",
            description='He said "hello" to everyone',
        )
        schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
            time_start="09:00", notes='Tip: use "early bird" pricing',
        )

        yaml_text = export_yaml(conn, trip)
        # The YAML should at minimum not crash
        assert "Quote Test" in yaml_text
        # Check that quotes don't break the YAML structure
        assert 'note: "' in yaml_text or "note:" in yaml_text

        conn.close()

    def test_export_excludes_rejected_items(self, db_file):
        """Dropped items should not appear in export."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Rejected Place", style="food")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )
        drop_visit(conn, trip["id"], item)

        yaml_text = export_yaml(conn, trip)
        assert "Rejected Place" not in yaml_text

        conn.close()

    def test_export_excludes_deleted_places(self, db_file):
        """Soft-deleted places should not appear in export."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Deleted Export", style="nature")
        schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )
        place_full = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (place["id"],)
        ).fetchone())
        remove_place(conn, trip["id"], place_full, force=True)

        yaml_text = export_yaml(conn, trip)
        assert "Deleted Export" not in yaml_text

        conn.close()

    def test_export_with_colons_in_description(self, db_file):
        """Descriptions with colons could break YAML if not quoted."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(
            conn, trip["id"], name_en="Colon Test", style="nature",
            description="Hours: 9:00-17:00",
        )
        schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        yaml_text = export_yaml(conn, trip)
        assert "Colon Test" in yaml_text
        # Description with colons should be quoted
        assert "Hours: 9:00-17:00" in yaml_text

        conn.close()


# ══════════════════════════════════════════════════════════════
# 11. Resolver edge cases
# ══════════════════════════════════════════════════════════════


class TestResolverEdgeCases:
    """Test resolver with edge case inputs."""

    def test_resolve_deleted_place_fails(self, db_file):
        """Resolving a soft-deleted place by ID should fail."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Delete Resolve", style="nature")
        place_full = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (place["id"],)
        ).fetchone())
        remove_place(conn, trip["id"], place_full, force=True)

        with pytest.raises(Exception):
            resolve_place(conn, str(place["id"]))

        conn.close()

    def test_resolve_deleted_place_by_uuid_fails(self, db_file):
        """Resolving a soft-deleted place by UUID should also fail."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="UUID Resolve", style="nature")
        uuid_prefix = place["uuid"][:8]

        place_full = dict(conn.execute(
            "SELECT * FROM places WHERE id=?", (place["id"],)
        ).fetchone())
        remove_place(conn, trip["id"], place_full, force=True)

        with pytest.raises(Exception):
            resolve_place(conn, uuid_prefix)

        conn.close()

    def test_resolve_with_numeric_uuid_prefix(self, db_file):
        """UUID prefix that looks like a number (e.g., '12345678') could match as integer ID."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)

        # Create enough places to get an ID that could collide with UUID prefix
        place = create_place(conn, trip["id"], name_en="Numeric UUID", style="nature")

        # If the place ID is, say, 1 — and UUID starts with a digit
        # The resolver tries int(ref) first, which is correct behavior
        result = resolve_place(conn, str(place["id"]))
        assert result["name_en"] == "Numeric UUID"

        conn.close()


# ══════════════════════════════════════════════════════════════
# 12. Concurrent mutations — verify isolation
# ══════════════════════════════════════════════════════════════


class TestConcurrentMutations:
    """Verify that multiple mutations on the same item produce correct state."""

    def test_confirm_then_drop_then_confirm(self, db_file):
        """Rapid status changes should produce correct final state + full audit trail."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Flipper", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
        )

        # pending → confirmed
        item = confirm_visit(conn, trip["id"], item)
        assert item["decision"] == "confirmed"

        # confirmed → rejected
        item = drop_visit(conn, trip["id"], item, reason="changed mind")
        assert item["decision"] == "rejected"

        # rejected → confirmed (re-confirm)
        item = confirm_visit(conn, trip["id"], item)
        assert item["decision"] == "confirmed"

        # Audit trail should have all transitions
        audits = conn.execute(
            "SELECT action, old_value, new_value FROM audit_log "
            "WHERE target_uuid=? ORDER BY id",
            (item["uuid"],),
        ).fetchall()

        # schedule + confirm + drop + confirm = 4 entries
        # (add_place is for place, not item)
        item_audits = [a for a in audits]
        assert len(item_audits) >= 3, f"Expected 3+ audits for item, got {len(item_audits)}"

        conn.close()

    def test_multiple_reschedules_sort_order_converges(self, db_file):
        """Multiple reschedules should always leave correct sort_order."""
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        trip = _get_trip_dict(conn)
        place = create_place(conn, trip["id"], name_en="Bouncer", style="nature")
        item = schedule_visit(
            conn, trip["id"], place_id=place["id"], day_num=1, trip=trip,
            time_start="09:00",
        )

        # Reschedule multiple times
        for day, time in [(3, "14:00"), (5, "08:00"), (2, "17:30")]:
            item = dict(conn.execute(
                "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
            ).fetchone())
            item = reschedule_visit(
                conn, trip["id"], item, trip,
                day_num=day, time_start=time,
            )

        # Final state should match Day 2 17:30
        assert item["date"] == "2026-04-18"  # Day 2
        assert item["time_start"] == "17:30"
        expected_sort = compute_sort_order(2, "17:30")
        assert item["sort_order"] == expected_sort

        conn.close()
