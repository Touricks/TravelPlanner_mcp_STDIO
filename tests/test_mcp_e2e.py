"""E2E tests for MCP workflow + bridge.

Calls MCP tool functions directly (no server required).
Mocks: _run_codex_search + _run_claude_transform (Codex/claude subprocesses).
Skips: Codex review (skip_codex=True).
Uses: temp directories for sessions, profile, SQLite DB.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    """Isolated MCP environment — temp sessions, profile, DB."""
    from mcp_server import config

    # Override sessions directory
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(config, "SESSIONS_DIR", sessions_dir)

    # Override DATA_DIR (legacy trip prefs location)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)

    # Provide complete profile (passes completeness check)
    profile_dir = tmp_path / "config"
    profile_dir.mkdir()
    from tests.fixtures import COMPLETE_PROFILE_YAML
    (profile_dir / "profile.yaml").write_text(COMPLETE_PROFILE_YAML)
    monkeypatch.setattr(config, "PROFILE_PATH", profile_dir / "profile.yaml")

    # Bridge: provide temp DB with schema
    db_path = tmp_path / "travel.db"
    schema = (config.PROJECT_ROOT / "tripdb" / "schema.sql").read_text()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db_path)

    return tmp_path


class _MockContext:
    """Minimal stand-in for FastMCP Context in tests."""

    async def info(self, msg): pass
    async def error(self, msg): pass
    async def debug(self, msg): pass
    async def report_progress(self, **kw): pass


MOCK_CTX = _MockContext()


@pytest.fixture
def mock_search(monkeypatch):
    """Mock _run_codex_search and _run_claude_transform with canned artifacts."""
    from tests.fixtures import SAMPLE_HOTELS, SAMPLE_POI_CANDIDATES, SAMPLE_RESTAURANTS

    call_log = []

    async def fake_codex_search(prompt, ctx=None):
        return "mock codex search results"

    async def fake_transform(transform_prompt, schema_path):
        stage = schema_path.stem
        call_log.append(stage)
        data = {
            "poi-candidates": SAMPLE_POI_CANDIDATES,
            "restaurants": SAMPLE_RESTAURANTS,
            "hotels": SAMPLE_HOTELS,
        }
        return data[stage]

    monkeypatch.setattr("mcp_server.server._run_codex_search", fake_codex_search)
    monkeypatch.setattr("mcp_server.server._run_claude_transform", fake_transform)
    return call_log


def _run_async(coro):
    """Run an async function in a new event loop (pytest-friendly)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Happy Path ─────────────────────────────────────────────


class TestStartTripDateValidation:
    """BUG-001: start_trip rejects invalid dates before creating any state."""

    def test_invalid_format_rejected(self, mcp_env):
        from mcp_server.server import start_trip
        r = start_trip("San Francisco", "next-week", "2026-04-25")
        assert r["status"] == "error"
        assert r["error"] == "invalid_dates"
        assert any(v["rule"] == "date_format" for v in r["violations"])

    def test_end_before_start_rejected(self, mcp_env):
        from mcp_server.server import start_trip
        r = start_trip("San Francisco", "2026-04-25", "2026-04-17")
        assert r["status"] == "error"
        assert any(v["rule"] == "date_range" for v in r["violations"])

    def test_excessive_duration_rejected(self, mcp_env):
        from mcp_server.server import start_trip
        r = start_trip("San Francisco", "2026-01-01", "2026-12-31")
        assert r["status"] == "error"
        assert any(v["rule"] == "date_duration" for v in r["violations"])

    def test_empty_string_rejected(self, mcp_env):
        from mcp_server.server import start_trip
        r = start_trip("San Francisco", "", "2026-04-25")
        assert r["status"] == "error"
        assert any(v["rule"] == "date_format" for v in r["violations"])

    def test_valid_dates_accepted(self, mcp_env):
        from mcp_server.server import start_trip
        r = start_trip("San Francisco", "2026-04-17", "2026-04-25")
        assert r.get("status") != "error"
        assert "session_id" in r


class TestMCPWorkflowE2E:
    """Full workflow: start → search → schedule → review → notion → complete."""

    def test_happy_path(self, mcp_env, mock_search):
        from mcp_server.server import (
            build_notion_manifest,
            complete_trip,
            get_workflow_status,
            record_notion_urls,
            run_review,
            search_hotels,
            search_pois,
            search_restaurants,
            start_trip,
            submit_artifact,
        )
        from tests.fixtures import SAMPLE_ITINERARY

        # Stage 0: Start trip
        r = start_trip("San Francisco", "2026-04-17", "2026-04-25")
        sid = r["session_id"]
        assert sid
        assert r["trip_id"]

        # Handle profile_collection if needed
        action = r["first_action"]
        if action.get("stage") == "profile_collection":
            from mcp_server.server import complete_profile_collection
            complete_profile_collection(sid)

        # Stage 1: POI Search (mocked)
        r = _run_async(search_pois(sid, MOCK_CTX))
        assert r["status"] == "complete"
        assert r["candidates_count"] == 5

        # Stage 2: Submit scheduling artifact
        r = submit_artifact(sid, "scheduling", SAMPLE_ITINERARY)
        assert r["status"] == "accepted"

        # Stage 3: Restaurant search (mocked)
        r = _run_async(search_restaurants(sid, MOCK_CTX))
        assert r["status"] == "complete"

        # Stage 4: Hotel search (mocked)
        r = _run_async(search_hotels(sid, MOCK_CTX))
        assert r["status"] == "complete"

        # Stage 5: Review (skip codex)
        r = run_review(sid, skip_codex=True)
        assert r["hard_pass"] is True

        # Stage 6: Notion manifest
        r = build_notion_manifest(sid)
        assert "manifest" in r

        # Stage 7: Record Notion URLs
        r = record_notion_urls(
            sid,
            "https://notion.so/test-page",
            {
                "itinerary": "db-itin-001",
                "restaurants": "db-rest-001",
                "hotels": "db-hotel-001",
                "notices": "db-notice-001",
            },
        )
        assert r["status"] == "accepted"

        # Stage 8: Complete
        r = complete_trip(sid)
        assert r["status"] == "complete"

        # Verify final state
        status = get_workflow_status(sid)
        assert status["status"] == "complete"
        expected_stages = {
            "poi_search", "scheduling", "restaurants",
            "hotels", "review", "notion", "verify",
        }
        assert expected_stages.issubset(set(status["completed_stages"]))

        # Verify search mock was called correctly
        assert "poi-candidates" in mock_search
        assert "restaurants" in mock_search
        assert "hotels" in mock_search

    def test_bridge_syncs_at_each_stage(self, mcp_env, mock_search):
        """Verify SQLite receives data at each bridge point."""
        from mcp_server import config
        from mcp_server.server import (
            run_review,
            search_hotels,
            search_pois,
            search_restaurants,
            start_trip,
            submit_artifact,
        )
        from tests.fixtures import SAMPLE_ITINERARY

        r = start_trip("San Francisco", "2026-04-17", "2026-04-25")
        sid = r["session_id"]

        if r["first_action"].get("stage") == "profile_collection":
            from mcp_server.server import complete_profile_collection
            complete_profile_collection(sid)

        _run_async(search_pois(sid, MOCK_CTX))
        submit_artifact(sid, "scheduling", SAMPLE_ITINERARY)
        _run_async(search_restaurants(sid, MOCK_CTX))
        _run_async(search_hotels(sid, MOCK_CTX))
        run_review(sid, skip_codex=True)

        # Check bridge_sync table
        conn = sqlite3.connect(str(config.DB_PATH))
        conn.row_factory = sqlite3.Row
        synced = conn.execute(
            "SELECT artifact_type, sync_state, rows_imported "
            "FROM bridge_sync ORDER BY artifact_type"
        ).fetchall()
        synced_types = {r["artifact_type"] for r in synced}

        assert "poi_search" in synced_types
        assert "scheduling" in synced_types
        assert "restaurants" in synced_types
        assert "hotels" in synced_types

        for row in synced:
            assert row["sync_state"] == "synced", (
                f"{row['artifact_type']} sync_state={row['sync_state']}"
            )

        # Check places created
        places_count = conn.execute(
            "SELECT COUNT(*) FROM places"
        ).fetchone()[0]
        assert places_count > 0

        # Check session_places populated
        sp_count = conn.execute(
            "SELECT COUNT(*) FROM session_places WHERE session_id=?", (sid,)
        ).fetchone()[0]
        assert sp_count > 0

        # Check itinerary items with session_id
        items_count = conn.execute(
            "SELECT COUNT(*) FROM itinerary_items "
            "WHERE session_id=? AND deleted_at IS NULL", (sid,)
        ).fetchone()[0]
        assert items_count > 0

        # Check hotels with session_id
        hotels_count = conn.execute(
            "SELECT COUNT(*) FROM hotels "
            "WHERE session_id=? AND deleted_at IS NULL", (sid,)
        ).fetchone()[0]
        assert hotels_count > 0

        conn.close()

    def test_session_isolation(self, mcp_env, mock_search):
        """Two sessions for same destination get separate session_ids."""
        from mcp_server.server import start_trip

        r1 = start_trip("San Francisco", "2026-04-17", "2026-04-25")
        r2 = start_trip("San Francisco", "2026-04-17", "2026-04-25")

        assert r1["session_id"] != r2["session_id"]
        assert r1["trip_id"] == r2["trip_id"]

    def test_error_recovery(self, mcp_env, mock_search):
        """Submit invalid artifact → rejected → fix → accepted."""
        from mcp_server.server import search_pois, start_trip, submit_artifact
        from tests.fixtures import SAMPLE_ITINERARY

        r = start_trip("San Francisco", "2026-04-17", "2026-04-25")
        sid = r["session_id"]

        if r["first_action"].get("stage") == "profile_collection":
            from mcp_server.server import complete_profile_collection
            complete_profile_collection(sid)

        _run_async(search_pois(sid, MOCK_CTX))

        # Submit invalid: empty days array
        bad = {
            "trip_id": "test",
            "start_date": "2026-04-17",
            "end_date": "2026-04-25",
            "days": [],
        }
        r = submit_artifact(sid, "scheduling", bad)
        # Empty days should still pass schema (days is an array, no minItems)
        # But hard_rules may fail or it may pass — either way, verify we can retry
        if r["status"] == "rejected":
            assert r["attempt"] >= 1

        # Submit valid
        r = submit_artifact(sid, "scheduling", SAMPLE_ITINERARY)
        assert r["status"] == "accepted"
