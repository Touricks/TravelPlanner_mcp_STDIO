"""Tests for tripdb.bridge — MCP artifact → SQLite bridge."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path for tripdb imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tripdb.bridge import (
    candidate_id,
    ensure_trip,
    import_hotels,
    import_itinerary,
    import_pois,
    import_restaurants,
    import_review_risks,
    register_session,
)


# ── Sample Artifacts ───────────────────────────────────────


def _poi_artifact(candidates=None):
    if candidates is None:
        candidates = [
            {
                "name_en": "Golden Gate Bridge",
                "name_cn": "金门大桥",
                "style": "landmark",
                "address": "Golden Gate Bridge, San Francisco, CA",
                "city": "San Francisco",
                "duration_minutes": 60,
                "description": "Iconic bridge",
            },
            {
                "name_en": "Fisherman's Wharf",
                "style": "landmark",
                "address": "Pier 39, San Francisco, CA",
                "city": "San Francisco",
                "duration_minutes": 90,
                "description": "Waterfront area",
            },
            {
                "name_en": "Chinatown",
                "name_cn": "唐人街",
                "style": "culture",
                "address": "Grant Ave, San Francisco, CA",
                "city": "San Francisco",
                "duration_minutes": 120,
                "description": "Historic neighborhood",
            },
        ]
    return {"destination": "San Francisco", "candidates": candidates}


def _itinerary_artifact(items_with_candidates=None):
    """Build itinerary artifact. Uses candidate_ids for place resolution."""
    if items_with_candidates is None:
        items_with_candidates = [
            {
                "day_num": 1,
                "items": [
                    {
                        "candidate_id": candidate_id(
                            "Golden Gate Bridge",
                            "Golden Gate Bridge, San Francisco, CA",
                        ),
                        "name_en": "Golden Gate Bridge",
                        "style": "landmark",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "duration_minutes": 60,
                    },
                    {
                        "candidate_id": candidate_id(
                            "Fisherman's Wharf",
                            "Pier 39, San Francisco, CA",
                        ),
                        "name_en": "Fisherman's Wharf",
                        "style": "landmark",
                        "start_time": "11:00",
                        "end_time": "12:30",
                        "duration_minutes": 90,
                    },
                ],
            },
        ]
    days = []
    for d in items_with_candidates:
        days.append({
            "day_num": d["day_num"],
            "date": f"2026-04-{16 + d['day_num']:02d}",
            "region": "San Francisco",
            "items": d["items"],
        })
    return {
        "trip_id": "test-trip",
        "start_date": "2026-04-17",
        "end_date": "2026-04-25",
        "days": days,
    }


# ── TestEnsureTrip ─────────────────────────────────────────


class TestEnsureTrip:
    def test_creates_trip(self, empty_db):
        ensure_trip(empty_db, "t1", "Paris", "2026-05-01", "2026-05-10")
        row = empty_db.execute("SELECT * FROM trips WHERE id='t1'").fetchone()
        assert row is not None

    def test_idempotent(self, empty_db):
        ensure_trip(empty_db, "t1", "Paris", "2026-05-01", "2026-05-10")
        ensure_trip(empty_db, "t1", "Paris", "2026-05-01", "2026-05-10")
        count = empty_db.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        assert count == 1


class TestRegisterSession:
    def test_creates_session(self, session_trip):
        conn, trip_id, sid = session_trip
        # Session already created by fixture
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        assert row is not None

    def test_idempotent(self, session_trip):
        conn, trip_id, sid = session_trip
        register_session(conn, sid, trip_id)
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 1

    def test_fk_constraint(self, empty_db):
        """Session must reference valid trip."""
        import sqlite3
        import pytest
        empty_db.execute(
            "INSERT INTO trips (id, destination, start_date, end_date) "
            "VALUES ('t1', 'X', '2026-01-01', '2026-01-02')"
        )
        empty_db.commit()
        register_session(empty_db, "s1", "t1")  # OK

        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO sessions (id, trip_id) VALUES ('s2', 'nonexistent')"
            )


# ── TestImportPois ─────────────────────────────────────────


class TestImportPois:
    def test_basic_import(self, session_trip):
        conn, trip_id, sid = session_trip
        result = import_pois(conn, sid, trip_id, _poi_artifact())
        assert result["status"] == "synced"
        assert result["rows_imported"] == 3
        assert len(result["candidate_map"]) == 3

        places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        assert places == 3

    def test_candidate_id_deterministic(self):
        a = candidate_id("Golden Gate Bridge", "123 Main St")
        b = candidate_id("Golden Gate Bridge", "123 Main St")
        assert a == b

    def test_dedup_same_name_address(self, session_trip):
        conn, trip_id, sid = session_trip
        art = _poi_artifact()
        import_pois(conn, sid, trip_id, art)
        # Create session2, then import same artifact — should reuse places
        conn.execute(
            "INSERT INTO sessions (id, trip_id) VALUES ('session2', ?)", (trip_id,)
        )
        conn.commit()
        result = import_pois(conn, "session2", trip_id, art)
        assert result["status"] == "synced"
        places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        assert places == 3  # No duplicates

    def test_session_places_populated(self, session_trip):
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())
        sp = conn.execute(
            "SELECT COUNT(*) FROM session_places WHERE session_id=?", (sid,)
        ).fetchone()[0]
        assert sp == 3

    def test_bridge_sync_recorded(self, session_trip):
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())
        row = conn.execute(
            "SELECT sync_state, rows_imported FROM bridge_sync "
            "WHERE session_id=? AND artifact_type='poi_search'",
            (sid,),
        ).fetchone()
        assert row[0] == "synced"
        assert row[1] == 3

    def test_idempotent_same_hash(self, session_trip):
        conn, trip_id, sid = session_trip
        art = _poi_artifact()
        import_pois(conn, sid, trip_id, art)
        result = import_pois(conn, sid, trip_id, art)
        assert result["status"] == "skipped"

    def test_changed_artifact_reimport(self, session_trip):
        conn, trip_id, sid = session_trip
        art1 = _poi_artifact()
        import_pois(conn, sid, trip_id, art1)
        # Change artifact
        art2 = _poi_artifact()
        art2["candidates"].append({
            "name_en": "New Place",
            "style": "nature",
            "address": "456 New St",
            "duration_minutes": 45,
            "description": "Added later",
        })
        result = import_pois(conn, sid, trip_id, art2)
        assert result["status"] == "synced"
        assert result["rows_imported"] == 4

    def test_audit_log(self, session_trip):
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())
        row = conn.execute(
            "SELECT action, actor FROM audit_log "
            "WHERE action='batch_import_pois'"
        ).fetchone()
        assert row is not None
        assert row[1] == "mcp_bridge"

    def test_maps_url_computed(self, session_trip):
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())
        row = conn.execute(
            "SELECT maps_url FROM places WHERE name_en='Golden Gate Bridge'"
        ).fetchone()
        assert row[0] is not None
        assert "maps.google.com" in row[0]


# ── TestImportItinerary ────────────────────────────────────


class TestImportItinerary:
    def test_basic_import(self, session_trip):
        conn, trip_id, sid = session_trip
        poi_result = import_pois(conn, sid, trip_id, _poi_artifact())
        cmap = poi_result["candidate_map"]

        result = import_itinerary(conn, sid, trip_id, _itinerary_artifact(), cmap)
        assert result["status"] == "synced"
        assert result["rows_imported"] == 2

    def test_candidate_id_resolution(self, session_trip):
        conn, trip_id, sid = session_trip
        poi_result = import_pois(conn, sid, trip_id, _poi_artifact())
        cmap = poi_result["candidate_map"]

        import_itinerary(conn, sid, trip_id, _itinerary_artifact(), cmap)
        # Check that itinerary items have valid place_ids
        rows = conn.execute(
            "SELECT ii.place_id, p.name_en FROM itinerary_items ii "
            "JOIN places p ON ii.place_id = p.id "
            "WHERE ii.session_id=? AND ii.deleted_at IS NULL",
            (sid,),
        ).fetchall()
        names = {r[1] for r in rows}
        assert "Golden Gate Bridge" in names
        assert "Fisherman's Wharf" in names

    def test_session_id_stored(self, session_trip):
        conn, trip_id, sid = session_trip
        poi_result = import_pois(conn, sid, trip_id, _poi_artifact())
        import_itinerary(
            conn, sid, trip_id, _itinerary_artifact(), poi_result["candidate_map"]
        )
        rows = conn.execute(
            "SELECT session_id FROM itinerary_items WHERE deleted_at IS NULL"
        ).fetchall()
        assert all(r[0] == sid for r in rows)

    def test_reimport_soft_deletes_old(self, session_trip):
        conn, trip_id, sid = session_trip
        poi_result = import_pois(conn, sid, trip_id, _poi_artifact())
        cmap = poi_result["candidate_map"]

        import_itinerary(conn, sid, trip_id, _itinerary_artifact(), cmap)
        first_count = conn.execute(
            "SELECT COUNT(*) FROM itinerary_items WHERE session_id=? AND deleted_at IS NULL",
            (sid,),
        ).fetchone()[0]
        assert first_count == 2

        # Re-import with different hash triggers re-sync
        art2 = _itinerary_artifact()
        art2["days"][0]["items"].append({
            "candidate_id": candidate_id("Chinatown", "Grant Ave, San Francisco, CA"),
            "name_en": "Chinatown",
            "style": "culture",
            "start_time": "14:00",
            "end_time": "16:00",
            "duration_minutes": 120,
        })
        import_itinerary(conn, sid, trip_id, art2, cmap)
        active = conn.execute(
            "SELECT COUNT(*) FROM itinerary_items WHERE session_id=? AND deleted_at IS NULL",
            (sid,),
        ).fetchone()[0]
        assert active == 3  # new import

    def test_sort_order_computed(self, session_trip):
        conn, trip_id, sid = session_trip
        poi_result = import_pois(conn, sid, trip_id, _poi_artifact())
        import_itinerary(
            conn, sid, trip_id, _itinerary_artifact(), poi_result["candidate_map"]
        )
        rows = conn.execute(
            "SELECT sort_order, time_start FROM itinerary_items "
            "WHERE session_id=? AND deleted_at IS NULL ORDER BY sort_order",
            (sid,),
        ).fetchall()
        # Day 1 09:00 -> 1*1000 + 9*60 + 0 = 1540
        assert rows[0][0] == 1540.0
        # Day 1 11:00 -> 1*1000 + 11*60 + 0 = 1660
        assert rows[1][0] == 1660.0

    def test_fallback_name_matching(self, session_trip):
        """When no candidate_id, falls back to name_en matching."""
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())

        art = {
            "trip_id": "test-trip",
            "start_date": "2026-04-17",
            "end_date": "2026-04-25",
            "days": [{
                "day_num": 1,
                "date": "2026-04-17",
                "region": "SF",
                "items": [{
                    "name_en": "Golden Gate Bridge",  # no candidate_id
                    "style": "landmark",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "duration_minutes": 60,
                }],
            }],
        }
        result = import_itinerary(conn, sid, trip_id, art)
        assert result["status"] == "synced"
        assert result["rows_imported"] == 1


# ── TestImportRestaurants ──────────────────────────────────


class TestImportRestaurants:
    def test_creates_food_places(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "recommendations": [
                {
                    "day_num": 1,
                    "meal_type": "lunch",
                    "name_en": "Test Restaurant",
                    "cuisine": "Italian",
                    "address": "100 Main St",
                    "near_poi": "Golden Gate Bridge",
                },
            ],
        }
        result = import_restaurants(conn, sid, trip_id, art, "2026-04-17")
        assert result["status"] == "synced"
        assert result["rows_imported"] == 1

        place = conn.execute(
            "SELECT style FROM places WHERE name_en='Test Restaurant'"
        ).fetchone()
        assert place[0] == "food"

    def test_creates_itinerary_items_with_meal_times(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "recommendations": [
                {
                    "day_num": 1, "meal_type": "lunch",
                    "name_en": "Lunch Spot", "cuisine": "Thai",
                    "address": "1 Lunch St", "near_poi": "X",
                },
                {
                    "day_num": 1, "meal_type": "dinner",
                    "name_en": "Dinner Spot", "cuisine": "Japanese",
                    "address": "2 Dinner St", "near_poi": "Y",
                },
            ],
        }
        import_restaurants(conn, sid, trip_id, art, "2026-04-17")
        rows = conn.execute(
            "SELECT time_start FROM itinerary_items "
            "WHERE session_id=? AND deleted_at IS NULL ORDER BY time_start",
            (sid,),
        ).fetchall()
        assert rows[0][0] == "12:00"  # lunch
        assert rows[1][0] == "18:30"  # dinner


# ── TestImportHotels ───────────────────────────────────────


class TestImportHotels:
    def test_basic_import(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "recommendations": [
                {
                    "name": "Hotel A",
                    "address": "1 Hotel St",
                    "city": "San Francisco",
                    "check_in": "2026-04-17",
                    "check_out": "2026-04-19",
                },
            ],
        }
        result = import_hotels(conn, sid, trip_id, art)
        assert result["status"] == "synced"
        assert result["rows_imported"] == 1

        row = conn.execute(
            "SELECT hotel_name, nights FROM hotels WHERE session_id=?", (sid,)
        ).fetchone()
        assert row[0] == "Hotel A"
        assert row[1] == 2  # computed GENERATED column

    def test_session_id_stored(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "recommendations": [{
                "name": "H1", "address": "1 St", "city": "SF",
                "check_in": "2026-04-17", "check_out": "2026-04-18",
            }],
        }
        import_hotels(conn, sid, trip_id, art)
        row = conn.execute(
            "SELECT session_id FROM hotels WHERE deleted_at IS NULL"
        ).fetchone()
        assert row[0] == sid

    def test_reimport_soft_deletes(self, session_trip):
        conn, trip_id, sid = session_trip
        art1 = {
            "trip_id": trip_id,
            "recommendations": [{
                "name": "Old Hotel", "address": "1 St", "city": "SF",
                "check_in": "2026-04-17", "check_out": "2026-04-18",
            }],
        }
        import_hotels(conn, sid, trip_id, art1)

        art2 = {
            "trip_id": trip_id,
            "recommendations": [{
                "name": "New Hotel", "address": "2 St", "city": "SF",
                "check_in": "2026-04-17", "check_out": "2026-04-19",
            }],
        }
        import_hotels(conn, sid, trip_id, art2)

        active = conn.execute(
            "SELECT hotel_name FROM hotels WHERE session_id=? AND deleted_at IS NULL",
            (sid,),
        ).fetchall()
        assert len(active) == 1
        assert active[0][0] == "New Hotel"


# ── TestImportReviewRisks ──────────────────────────────────


class TestImportReviewRisks:
    def test_reject_creates_risk(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "summary": {"total_items": 2, "accepted": 1, "flagged": 0, "rejected": 1},
            "items": [
                {"ref": "item1", "source": "hard_rule", "verdict": "reject",
                 "rule_id": "time_overlap", "reason": "Items overlap"},
                {"ref": "item2", "source": "soft_rule", "verdict": "accept",
                 "reason": "OK"},
            ],
        }
        result = import_review_risks(conn, sid, trip_id, art)
        assert result["status"] == "synced"
        assert result["rows_imported"] == 1

        risks = conn.execute(
            "SELECT category, source FROM risks WHERE session_id=?", (sid,)
        ).fetchall()
        assert len(risks) == 1
        assert risks[0][0] == "logistics"
        assert risks[0][1] == "review"

    def test_accept_skipped(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "summary": {"total_items": 1, "accepted": 1, "flagged": 0, "rejected": 0},
            "items": [
                {"ref": "item1", "source": "hard_rule", "verdict": "accept",
                 "reason": "OK"},
            ],
        }
        result = import_review_risks(conn, sid, trip_id, art)
        assert result["rows_imported"] == 0

    def test_flag_creates_risk(self, session_trip):
        conn, trip_id, sid = session_trip
        art = {
            "trip_id": trip_id,
            "summary": {"total_items": 1, "accepted": 0, "flagged": 1, "rejected": 0},
            "items": [
                {"ref": "i1", "source": "codex", "verdict": "flag",
                 "reason": "Proximity concern"},
            ],
        }
        result = import_review_risks(conn, sid, trip_id, art)
        assert result["rows_imported"] == 1


# ── TestSessionIsolation ───────────────────────────────────


class TestSessionIsolation:
    def test_two_sessions_no_collision(self, empty_db):
        conn = empty_db
        conn.execute(
            "INSERT INTO trips (id, destination, start_date, end_date) "
            "VALUES ('t1', 'SF', '2026-04-17', '2026-04-25')"
        )
        conn.execute("INSERT INTO sessions (id, trip_id) VALUES ('s1', 't1')")
        conn.execute("INSERT INTO sessions (id, trip_id) VALUES ('s2', 't1')")
        conn.commit()

        art = _poi_artifact()
        r1 = import_pois(conn, "s1", "t1", art)
        r2 = import_pois(conn, "s2", "t1", art)

        assert r1["status"] == "synced"
        assert r2["status"] == "synced"

        # Both sessions see 3 session_places each
        sp1 = conn.execute(
            "SELECT COUNT(*) FROM session_places WHERE session_id='s1'"
        ).fetchone()[0]
        sp2 = conn.execute(
            "SELECT COUNT(*) FROM session_places WHERE session_id='s2'"
        ).fetchone()[0]
        assert sp1 == 3
        assert sp2 == 3

        # But only 3 actual places (dedup)
        places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        assert places == 3

    def test_null_session_excluded(self, session_trip):
        """Legacy items with NULL session_id excluded from session queries."""
        conn, trip_id, sid = session_trip
        # Insert legacy place + item (no session_id)
        conn.execute(
            "INSERT INTO places (name_en, style, address) "
            "VALUES ('Legacy Place', 'landmark', '1 Old St')"
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO itinerary_items (trip_id, place_id, date) "
            "VALUES (?, ?, '2026-04-17')",
            (trip_id, pid),
        )
        conn.commit()

        # Import session data
        import_pois(conn, sid, trip_id, _poi_artifact())

        # Session query excludes legacy
        from tripdb.queries import session_places
        sp = session_places(conn, sid)
        names = {p["name_en"] for p in sp}
        assert "Legacy Place" not in names
        assert "Golden Gate Bridge" in names


# ── TestBridgeSync ─────────────────────────────────────────


class TestBridgeSync:
    def test_sync_state_on_success(self, session_trip):
        conn, trip_id, sid = session_trip
        import_pois(conn, sid, trip_id, _poi_artifact())
        row = conn.execute(
            "SELECT sync_state FROM bridge_sync "
            "WHERE session_id=? AND artifact_type='poi_search'",
            (sid,),
        ).fetchone()
        assert row[0] == "synced"

    def test_idempotent_skip(self, session_trip):
        conn, trip_id, sid = session_trip
        art = _poi_artifact()
        import_pois(conn, sid, trip_id, art)
        result = import_pois(conn, sid, trip_id, art)
        assert result["status"] == "skipped"


# ── Workspace Session Persistence ──────────────────────────────


class TestRegisterSessionWorkspace:
    """Tests for workspace_id / workspace_tag in register_session."""

    def test_register_session_with_workspace(self, session_trip):
        conn, trip_id, sid = session_trip
        register_session(conn, "ws_session_1", trip_id, workspace_id="ws123", workspace_tag="test-trip")
        row = conn.execute(
            "SELECT workspace_id, workspace_tag FROM sessions WHERE id='ws_session_1'"
        ).fetchone()
        assert row[0] == "ws123"
        assert row[1] == "test-trip"

    def test_register_session_without_workspace(self, session_trip):
        conn, trip_id, sid = session_trip
        register_session(conn, "no_ws_session", trip_id)
        row = conn.execute(
            "SELECT workspace_id, workspace_tag FROM sessions WHERE id='no_ws_session'"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None


class TestUpdateSessionStatus:
    """Tests for update_session_status bridge function."""

    def test_updates_to_complete(self, session_trip):
        from tripdb.bridge import update_session_status
        conn, trip_id, sid = session_trip
        update_session_status(conn, sid, "complete")
        row = conn.execute(
            "SELECT status, completed_at FROM sessions WHERE id=?", (sid,)
        ).fetchone()
        assert row[0] == "complete"
        assert row[1] is not None  # completed_at set

    def test_updates_to_cancelled(self, session_trip):
        from tripdb.bridge import update_session_status
        conn, trip_id, sid = session_trip
        update_session_status(conn, sid, "cancelled")
        row = conn.execute("SELECT status FROM sessions WHERE id=?", (sid,)).fetchone()
        assert row[0] == "cancelled"

    def test_ignores_invalid_status(self, session_trip):
        from tripdb.bridge import update_session_status
        conn, trip_id, sid = session_trip
        update_session_status(conn, sid, "blocked")  # not a DB-valid status
        row = conn.execute("SELECT status FROM sessions WHERE id=?", (sid,)).fetchone()
        assert row[0] == "active"  # unchanged


class TestFindActiveSessionByWorkspace:
    """Tests for workspace-based session queries."""

    def test_finds_active_session(self, session_trip):
        from tripdb.queries import find_active_session_by_workspace
        conn, trip_id, sid = session_trip
        register_session(conn, "ws_find_1", trip_id, workspace_id="find_ws_123")
        result = find_active_session_by_workspace(conn, "find_ws_123")
        assert result is not None
        assert result["id"] == "ws_find_1"

    def test_returns_none_for_unknown(self, session_trip):
        from tripdb.queries import find_active_session_by_workspace
        conn, trip_id, sid = session_trip
        result = find_active_session_by_workspace(conn, "nonexistent")
        assert result is None

    def test_skips_completed_session(self, session_trip):
        from tripdb.bridge import update_session_status
        from tripdb.queries import find_active_session_by_workspace
        conn, trip_id, sid = session_trip
        register_session(conn, "ws_done_1", trip_id, workspace_id="done_ws")
        update_session_status(conn, "ws_done_1", "complete")
        result = find_active_session_by_workspace(conn, "done_ws")
        assert result is None
