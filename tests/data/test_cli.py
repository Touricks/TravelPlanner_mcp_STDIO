"""Integration tests for Sprint 1 CLI commands (status, add-place, schedule)."""

import json
import sqlite3

import pytest
from click.testing import CliRunner

from cli.trip import cli
from cli.utils import compute_sort_order, format_maps_url


# ── Utility unit tests ──────────────────────────────────────


class TestUtilFunctions:
    def test_compute_sort_order_with_time(self):
        assert compute_sort_order(1, "18:30") == 2110.0

    def test_compute_sort_order_no_time(self):
        assert compute_sort_order(3, None) == 3000.0

    def test_format_maps_url_basic(self):
        url = format_maps_url("123 Main St, SF CA")
        assert url == "https://maps.google.com/?q=123+Main+St%2C+SF+CA"

    def test_format_maps_url_unicode(self):
        url = format_maps_url("东京都渋谷区")
        assert "maps.google.com" in url


# ── trip status ─────────────────────────────────────────────


class TestStatus:
    def test_shows_trip_name(self, db_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_file), "status"])
        assert result.exit_code == 0
        assert "Test Destination" in result.output

    def test_shows_table_names(self, db_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_file), "status"])
        assert "places" in result.output
        assert "itinerary_items" in result.output
        assert "hotels" in result.output

    def test_empty_db_zero_counts(self, db_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_file), "status"])
        assert result.exit_code == 0

    def test_verbose_no_crash(self, db_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_file), "status", "--verbose"])
        assert result.exit_code == 0

    def test_alerts_unscheduled(self, db_file):
        """An orphan place triggers the unscheduled alert."""
        conn = sqlite3.connect(str(db_file))
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Orphan', 'nature')")
        conn.commit()
        conn.close()
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_file), "status"])
        assert "unscheduled" in result.output


# ── trip add-place ──────────────────────────────────────────


class TestAddPlace:
    def test_basic_add(self, db_file):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_file), "add-place", "Test Cafe", "--style", "coffee"],
        )
        assert result.exit_code == 0
        assert "Added place" in result.output
        assert "Test Cafe" in result.output
        assert "coffee" in result.output

    def test_maps_url_from_address(self, db_file):
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_file), "add-place", "Golden Park",
                "--style", "nature", "--address", "123 Main St, SF CA",
            ],
        )
        conn = sqlite3.connect(str(db_file))
        url = conn.execute(
            "SELECT maps_url FROM places WHERE name_en='Golden Park'"
        ).fetchone()[0]
        conn.close()
        assert "maps.google.com" in url
        assert "123+Main+St" in url

    def test_no_maps_url_without_address(self, db_file):
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_file), "add-place", "No Addr", "--style", "nature"],
        )
        conn = sqlite3.connect(str(db_file))
        url = conn.execute(
            "SELECT maps_url FROM places WHERE name_en='No Addr'"
        ).fetchone()[0]
        conn.close()
        assert url is None

    def test_audit_log_entry(self, db_file):
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_file), "add-place", "Audited", "--style", "food"],
        )
        conn = sqlite3.connect(str(db_file))
        row = conn.execute(
            "SELECT action, target_type, new_value FROM audit_log "
            "WHERE action='add_place'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "add_place"
        assert row[1] == "place"
        data = json.loads(row[2])
        assert data["name_en"] == "Audited"
        assert data["style"] == "food"

    def test_style_required(self, db_file):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_file), "add-place", "No Style"]
        )
        assert result.exit_code != 0

    def test_invalid_style_rejected(self, db_file):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_file), "add-place", "Bad", "--style", "museum"],
        )
        assert result.exit_code != 0

    def test_default_source_is_user(self, db_file):
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_file), "add-place", "UserPlace", "--style", "culture"],
        )
        conn = sqlite3.connect(str(db_file))
        source = conn.execute(
            "SELECT source FROM places WHERE name_en='UserPlace'"
        ).fetchone()[0]
        conn.close()
        assert source == "user"

    def test_chinese_name(self, db_file):
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_file), "add-place", "Dim Sum Palace",
                "--style", "food", "--cn", "点心宫",
            ],
        )
        conn = sqlite3.connect(str(db_file))
        cn = conn.execute(
            "SELECT name_cn FROM places WHERE name_en='Dim Sum Palace'"
        ).fetchone()[0]
        conn.close()
        assert cn == "点心宫"


# ── trip schedule ───────────────────────────────────────────


class TestSchedule:
    @pytest.fixture
    def db_with_place(self, db_file):
        """db_file + one place, returns (db_path, place_id)."""
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO places (name_en, style, city) "
            "VALUES ('Test Place', 'nature', 'SF')"
        )
        place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return db_file, place_id

    def test_basic_schedule(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--db", str(db_path), "schedule", str(place_id),
                "--day", "1", "--time", "09:00", "--duration", "60",
            ],
        )
        assert result.exit_code == 0
        assert "Scheduled" in result.output
        assert "Test Place" in result.output
        assert "Day 1" in result.output

    def test_date_from_day(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "schedule", str(place_id), "--day", "3"],
        )
        conn = sqlite3.connect(str(db_path))
        date_val = conn.execute(
            "SELECT date FROM itinerary_items WHERE place_id=?", (place_id,)
        ).fetchone()[0]
        conn.close()
        assert date_val == "2026-04-19"  # Day 3 of trip starting Apr 17

    def test_sort_order(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_path), "schedule", str(place_id),
                "--day", "2", "--time", "14:30",
            ],
        )
        conn = sqlite3.connect(str(db_path))
        so = conn.execute(
            "SELECT sort_order FROM itinerary_items WHERE place_id=?", (place_id,)
        ).fetchone()[0]
        conn.close()
        assert so == 2870.0  # 2*1000 + 14*60 + 30

    def test_time_end_computed(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_path), "schedule", str(place_id),
                "--day", "1", "--time", "09:00", "--duration", "90",
            ],
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT time_start, time_end FROM itinerary_items WHERE place_id=?",
            (place_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "09:00"
        assert row[1] == "10:30"

    def test_day_out_of_range(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "schedule", str(place_id), "--day", "15"],
        )
        assert result.exit_code != 0
        assert "out of range" in result.output

    def test_nonexistent_place(self, db_with_place):
        db_path, _ = db_with_place
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "schedule", "9999", "--day", "1"],
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_audit_log(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_path), "schedule", str(place_id),
                "--day", "2", "--time", "10:00",
            ],
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT action, new_value FROM audit_log WHERE action='schedule_visit'"
        ).fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row[1])
        assert data["day_num"] == 2
        assert data["time_start"] == "10:00"

    def test_day_required(self, db_with_place):
        db_path, place_id = db_with_place
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "schedule", str(place_id)],
        )
        assert result.exit_code != 0


# ── Sprint 2: Mutation commands ─────────────────────────────


@pytest.fixture
def db_with_item(db_file):
    """db_file + one place + one itinerary item. Returns (path, place_id, item_id)."""
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO places (name_en, style, city) "
        "VALUES ('Test Place', 'nature', 'SF')"
    )
    place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO itinerary_items (trip_id, place_id, date, time_start, "
        "time_end, duration_minutes, sort_order) "
        "VALUES ('test-trip', ?, '2026-04-17', '09:00', '10:00', 60, 1540.0)",
        (place_id,),
    )
    item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return db_file, place_id, item_id


class TestConfirm:
    def test_pending_to_confirmed(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_path), "confirm", str(item_id)])
        assert result.exit_code == 0
        assert "Confirmed" in result.output
        conn = sqlite3.connect(str(db_path))
        decision = conn.execute(
            "SELECT decision FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert decision == "confirmed"

    def test_already_confirmed_noop(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        # Confirm once
        runner.invoke(cli, ["--db", str(db_path), "confirm", str(item_id)])
        # Confirm again
        result = runner.invoke(cli, ["--db", str(db_path), "confirm", str(item_id)])
        assert result.exit_code == 0
        assert "Already confirmed" in result.output

    def test_audit_log(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(cli, ["--db", str(db_path), "confirm", str(item_id)])
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT action FROM audit_log WHERE action='confirm'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_nonexistent_item(self, db_with_item):
        db_path, _, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_path), "confirm", "9999"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestDrop:
    def test_pending_to_rejected(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db_path), "drop", str(item_id)])
        assert result.exit_code == 0
        assert "Dropped" in result.output
        conn = sqlite3.connect(str(db_path))
        decision = conn.execute(
            "SELECT decision FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert decision == "rejected"

    def test_reason_appended_to_notes(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "drop", str(item_id), "--reason", "Too far"],
        )
        conn = sqlite3.connect(str(db_path))
        notes = conn.execute(
            "SELECT notes FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert "[Dropped] Too far" in notes

    def test_place_still_exists_after_drop(self, db_with_item):
        db_path, place_id, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(cli, ["--db", str(db_path), "drop", str(item_id)])
        conn = sqlite3.connect(str(db_path))
        place = conn.execute(
            "SELECT deleted_at FROM places WHERE id=?", (place_id,)
        ).fetchone()
        conn.close()
        assert place[0] is None  # not deleted

    def test_audit_log(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(cli, ["--db", str(db_path), "drop", str(item_id)])
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT action, new_value FROM audit_log WHERE action='drop'"
        ).fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row[1])
        assert data["decision"] == "rejected"


class TestUpdatePlace:
    def test_change_name(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "update-place", str(place_id), "--name", "New Name"],
        )
        assert result.exit_code == 0
        assert "Updated" in result.output
        conn = sqlite3.connect(str(db_path))
        name = conn.execute(
            "SELECT name_en FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        conn.close()
        assert name == "New Name"

    def test_change_address_recomputes_maps_url(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--db", str(db_path), "update-place", str(place_id),
                "--address", "456 Oak Ave, LA",
            ],
        )
        conn = sqlite3.connect(str(db_path))
        url = conn.execute(
            "SELECT maps_url FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        conn.close()
        assert "456+Oak+Ave" in url

    def test_invalid_style_rejected(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "update-place", str(place_id), "--style", "museum"],
        )
        assert result.exit_code != 0

    def test_no_options_error(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "update-place", str(place_id)]
        )
        assert result.exit_code != 0
        assert "No changes" in result.output

    def test_audit_log(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "update-place", str(place_id), "--city", "Oakland"],
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT action FROM audit_log WHERE action='update_place'"
        ).fetchone()
        conn.close()
        assert row is not None


class TestReschedule:
    def test_change_day(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "reschedule", str(item_id), "--day", "3"],
        )
        assert result.exit_code == 0
        assert "Rescheduled" in result.output
        conn = sqlite3.connect(str(db_path))
        date_val = conn.execute(
            "SELECT date FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert date_val == "2026-04-19"

    def test_change_time(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "reschedule", str(item_id), "--time", "14:00"],
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT time_start, sort_order FROM itinerary_items WHERE id=?",
            (item_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "14:00"
        assert row[1] == 1840.0  # Day 1 * 1000 + 14*60 + 0

    def test_change_duration_recomputes_time_end(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "reschedule", str(item_id), "--duration", "120"],
        )
        conn = sqlite3.connect(str(db_path))
        time_end = conn.execute(
            "SELECT time_end FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert time_end == "11:00"  # 09:00 + 120min

    def test_no_options_error(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "reschedule", str(item_id)]
        )
        assert result.exit_code != 0
        assert "at least one" in result.output

    def test_day_out_of_range(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "reschedule", str(item_id), "--day", "20"],
        )
        assert result.exit_code != 0
        assert "out of range" in result.output

    def test_audit_log(self, db_with_item):
        db_path, _, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "reschedule", str(item_id), "--day", "5"],
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT old_value, new_value FROM audit_log WHERE action='reschedule'"
        ).fetchone()
        conn.close()
        assert row is not None
        old = json.loads(row[0])
        new = json.loads(row[1])
        assert old["date"] == "2026-04-17"
        assert new["date"] == "2026-04-21"


class TestRemovePlace:
    def test_remove_no_active_visits(self, db_file):
        conn = sqlite3.connect(str(db_file))
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Orphan', 'nature')")
        conn.commit()
        place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_file), "remove-place", str(place_id)]
        )
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_active_visits_without_force(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "remove-place", str(place_id)]
        )
        assert result.exit_code != 0
        assert "active visit" in result.output

    def test_active_visits_with_force(self, db_with_item):
        db_path, place_id, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "remove-place", str(place_id), "--force"],
        )
        assert result.exit_code == 0
        assert "Removed" in result.output
        conn = sqlite3.connect(str(db_path))
        deleted = conn.execute(
            "SELECT deleted_at FROM places WHERE id=?", (place_id,)
        ).fetchone()[0]
        conn.close()
        assert deleted is not None

    def test_cascade_deletes_items(self, db_with_item):
        db_path, place_id, item_id = db_with_item
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "remove-place", str(place_id), "--force"],
        )
        conn = sqlite3.connect(str(db_path))
        item_deleted = conn.execute(
            "SELECT deleted_at FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert item_deleted is not None

    def test_audit_log(self, db_file):
        conn = sqlite3.connect(str(db_file))
        conn.execute("INSERT INTO places (name_en, style) VALUES ('Temp', 'food')")
        conn.commit()
        place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        runner = CliRunner()
        runner.invoke(
            cli, ["--db", str(db_file), "remove-place", str(place_id)]
        )
        conn = sqlite3.connect(str(db_file))
        row = conn.execute(
            "SELECT action FROM audit_log WHERE action='remove_place'"
        ).fetchone()
        conn.close()
        assert row is not None


# ── Sprint 3: Sync & Export ─────────────────────────────────


class TestExportYaml:
    def test_export_creates_file(self, db_with_item, tmp_path):
        db_path, _, _ = db_with_item
        out = tmp_path / "export.yaml"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "export-yaml", "--output", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "Test Place" in content

    def test_export_contains_trip_header(self, db_with_item, tmp_path):
        db_path, _, _ = db_with_item
        out = tmp_path / "export.yaml"
        runner = CliRunner()
        runner.invoke(
            cli, ["--db", str(db_path), "export-yaml", "--output", str(out)]
        )
        content = out.read_text()
        assert "trip:" in content
        assert "destination:" in content

    def test_export_duration_format(self, db_with_item, tmp_path):
        db_path, _, _ = db_with_item
        out = tmp_path / "export.yaml"
        runner = CliRunner()
        runner.invoke(
            cli, ["--db", str(db_path), "export-yaml", "--output", str(out)]
        )
        content = out.read_text()
        assert "duration: 1h" in content  # 60 min → 1h


class TestDurText:
    def test_whole_hours(self):
        from cli.utils import _dur_text
        assert _dur_text(60) == "1h"
        assert _dur_text(120) == "2h"

    def test_fractional_hours(self):
        from cli.utils import _dur_text
        assert _dur_text(90) == "1.5h"

    def test_minutes(self):
        from cli.utils import _dur_text
        assert _dur_text(30) == "30min"
        assert _dur_text(45) == "45min"

    def test_none_and_zero(self):
        from cli.utils import _dur_text
        assert _dur_text(None) == ""
        assert _dur_text(0) == ""


class TestPushNotion:
    def test_dry_run_shows_counts(self, db_with_item):
        db_path, _, _ = db_with_item
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "push-notion", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "pending" in result.output

    def test_no_pending_shows_all_synced(self, db_file):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_file), "push-notion", "--dry-run"]
        )
        assert result.exit_code == 0
        # Empty db has no pending items
        assert "synced" in result.output or "nothing" in result.output


class TestMarkSynced:
    def test_mark_itinerary_item(self, db_with_item):
        db_path, _, item_id = db_with_item
        conn = sqlite3.connect(str(db_path))
        uuid = conn.execute(
            "SELECT uuid FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_path), "mark-synced", uuid]
        )
        assert result.exit_code == 0
        assert "synced" in result.output
        conn = sqlite3.connect(str(db_path))
        status = conn.execute(
            "SELECT sync_status FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert status == "synced"

    def test_mark_with_notion_id(self, db_with_item):
        db_path, _, item_id = db_with_item
        conn = sqlite3.connect(str(db_path))
        uuid = conn.execute(
            "SELECT uuid FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        runner = CliRunner()
        runner.invoke(
            cli,
            ["--db", str(db_path), "mark-synced", uuid, "--notion-id", "abc-123"],
        )
        conn = sqlite3.connect(str(db_path))
        nid = conn.execute(
            "SELECT notion_page_id FROM itinerary_items WHERE id=?", (item_id,)
        ).fetchone()[0]
        conn.close()
        assert nid == "abc-123"

    def test_invalid_uuid(self, db_file):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(db_file), "mark-synced", "nonexistent-uuid"]
        )
        assert result.exit_code != 0
