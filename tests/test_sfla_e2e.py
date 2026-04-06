"""E2E test for SF-to-LA coastal road trip (3 nights, 4 days).

Exercises the full MCP workflow pipeline by calling actual tool functions
with search subprocess mocked to return SF-LA fixture data.

Tests: start_trip -> search -> scheduling -> review -> notion -> complete,
including bridge sync to SQLite and session query verification.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.config import GUARDRAILS_PATH, STAGES


class _MockContext:
    """Minimal stand-in for FastMCP Context in tests."""

    async def info(self, msg): pass
    async def error(self, msg): pass
    async def debug(self, msg): pass
    async def report_progress(self, **kw): pass


MOCK_CTX = _MockContext()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    """Isolated MCP environment — temp sessions, profile, trip data, DB."""
    import mcp_server.config as cfg
    import mcp_server.workflow as _wf

    monkeypatch.setattr(cfg, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(_wf, "SESSIONS_DIR", tmp_path / "sessions")

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path / "data")

    profile_dir = tmp_path / "config"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text(
        "identity:\n"
        "  name: Test User\n"
        "  languages: [en, zh]\n"
        "travel_interests:\n"
        "  styles: [nature, culture, food]\n"
        "travel_style:\n"
        "  budget: moderate\n"
        "  accommodation: hotel\n"
        "travel_pace:\n"
        "  pois_per_day: [2, 5]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "PROFILE_PATH", profile_dir / "profile.yaml")

    db_path = tmp_path / "travel.db"
    conn = sqlite3.connect(str(db_path))
    schema = (cfg.PROJECT_ROOT / "tripdb" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.close()
    monkeypatch.setattr(cfg, "DB_PATH", db_path)

    return tmp_path


@pytest.fixture
def mock_search(monkeypatch):
    """Mock codex exec + claude -p transform with SF-LA fixture data."""
    from mcp_server import config
    from tests.fixtures import SFLA_HOTELS, SFLA_POI_CANDIDATES, SFLA_RESTAURANTS

    poi_transform_idx = 0

    monkeypatch.setattr(config, "CODEX_SEARCH_MAX_RETRIES", 0)
    monkeypatch.setattr(config, "CODEX_SECONDS_PER_POI_SCALING", 1)
    monkeypatch.setattr(config, "TRANSFORM_PARALLEL_LIMIT", 3)
    monkeypatch.setattr(config, "TRANSFORM_PER_POI_TIMEOUT_SECONDS", 5)

    async def fake_codex_search(prompt, ctx=None, **kwargs):
        return "mock codex search results"

    async def fake_transform(transform_prompt, schema_path, timeout=None):
        nonlocal poi_transform_idx
        stage = schema_path.stem
        if stage == "poi-candidate-single":
            candidates = SFLA_POI_CANDIDATES["candidates"]
            candidate = candidates[poi_transform_idx % len(candidates)]
            poi_transform_idx += 1
            return candidate
        return {
            "poi-names": {
                "destination": "SF to LA Coast",
                "poi_names": [
                    {"name_en": c["name_en"], "priority": c.get("priority", "agent_suggested")}
                    for c in SFLA_POI_CANDIDATES["candidates"]
                ],
            },
            "poi-candidates": SFLA_POI_CANDIDATES,
            "restaurants": SFLA_RESTAURANTS,
            "hotels": SFLA_HOTELS,
        }[stage]

    monkeypatch.setattr("mcp_server.server._run_codex_search", fake_codex_search)
    monkeypatch.setattr("mcp_server.server._run_claude_transform", fake_transform)


def _run_full_workflow(mcp_env):
    """Run the complete MCP workflow, returning session_id."""
    from mcp_server.server import (
        build_notion_manifest,
        complete_trip,
        record_notion_urls,
        run_review,
        search_hotels,
        search_pois,
        search_restaurants,
        start_trip,
        submit_artifact,
    )
    from tests.fixtures import SFLA_ITINERARY

    r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                   workspace_tag="sf-la-coastal-2026")
    sid = r["session_id"]

    asyncio.run(search_pois(sid, MOCK_CTX))
    submit_artifact(sid, "scheduling", SFLA_ITINERARY)
    asyncio.run(search_restaurants(sid, MOCK_CTX))
    asyncio.run(search_hotels(sid, MOCK_CTX))
    run_review(sid, skip_codex=True)
    build_notion_manifest(sid)
    record_notion_urls(
        sid,
        "https://notion.so/fake-sfla",
        {"itinerary": "db1", "restaurants": "db2", "hotels": "db3", "notices": "db4"},
    )
    complete_trip(sid)
    return sid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSflaE2E:
    """Full pipeline E2E for a 4-day SF-to-LA coastal road trip."""

    def test_happy_path_workflow(self, mcp_env, mock_search):
        """Full workflow from start_trip to complete_trip."""
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
        from tests.fixtures import SFLA_ITINERARY

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        sid = r["session_id"]
        assert r["first_action"]["stage"] == "poi_search"

        r = asyncio.run(search_pois(sid, MOCK_CTX))
        assert r["status"] == "complete"
        assert r["candidates_count"] == 12

        r = submit_artifact(sid, "scheduling", SFLA_ITINERARY)
        assert r["status"] == "accepted", f"Scheduling rejected: {r}"

        r = asyncio.run(search_restaurants(sid, MOCK_CTX))
        assert r["status"] == "complete"
        assert r["recommendations_count"] == 8

        r = asyncio.run(search_hotels(sid, MOCK_CTX))
        assert r["status"] == "complete"
        assert r["recommendations_count"] == 3

        r = run_review(sid, skip_codex=True)
        assert r["hard_pass"] is True
        assert r["review_report"]["summary"]["rejected"] == 0

        r = build_notion_manifest(sid)
        manifest = r["manifest"]
        assert set(manifest["databases"].keys()) == {
            "itinerary",
            "restaurants",
            "hotels",
            "notices",
        }
        assert len(manifest["databases"]["itinerary"]["entries"]) == 12
        assert len(manifest["databases"]["restaurants"]["entries"]) == 8
        assert len(manifest["databases"]["hotels"]["entries"]) == 3

        r = record_notion_urls(
            sid,
            "https://notion.so/fake-sfla",
            {
                "itinerary": "db1",
                "restaurants": "db2",
                "hotels": "db3",
                "notices": "db4",
            },
        )
        assert r["status"] == "accepted"

        r = complete_trip(sid)
        assert r["status"] == "complete"

        status = get_workflow_status(sid)
        assert status["status"] == "complete"
        assert set(status["completed_stages"]) == set(STAGES)

    def test_bridge_syncs_all_artifacts(self, mcp_env, mock_search):
        """Verify SQLite receives data at each bridge point."""
        import mcp_server.config as cfg

        sid = _run_full_workflow(mcp_env)

        conn = sqlite3.connect(str(cfg.DB_PATH))
        conn.row_factory = sqlite3.Row

        synced = conn.execute(
            "SELECT artifact_type, sync_state FROM bridge_sync"
        ).fetchall()
        synced_types = {r["artifact_type"] for r in synced}
        assert synced_types >= {
            "poi_search",
            "scheduling",
            "restaurants",
            "hotels",
            "review",
        }
        assert all(r["sync_state"] == "synced" for r in synced)

        places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        assert places >= 20

        items = conn.execute(
            "SELECT COUNT(*) FROM itinerary_items "
            "WHERE session_id IS NOT NULL AND deleted_at IS NULL"
        ).fetchone()[0]
        assert items >= 20

        hotels = conn.execute(
            "SELECT COUNT(*) FROM hotels "
            "WHERE deleted_at IS NULL AND session_id IS NOT NULL"
        ).fetchone()[0]
        assert hotels == 3

        risks = conn.execute(
            "SELECT COUNT(*) FROM risks WHERE deleted_at IS NULL"
        ).fetchone()[0]
        assert risks >= 1

        conn.close()

    def test_error_recovery_flow(self, mcp_env, mock_search):
        """Submit invalid scheduling, then valid — accepted."""
        from mcp_server.server import (
            search_pois,
            start_trip,
            submit_artifact,
        )
        from tests.fixtures import SFLA_ITINERARY

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        sid = r["session_id"]

        asyncio.run(search_pois(sid, MOCK_CTX))

        bad = {
            "trip_id": "x",
            "start_date": "2026-04-19",
            "end_date": "2026-04-22",
            "days": [
                {
                    "date": "2026-04-19",
                    "day_num": 1,
                    "items": [{"name_en": "Bad Item"}],
                }
            ],
        }
        r = submit_artifact(sid, "scheduling", bad)
        assert r["status"] == "rejected"
        assert r["attempt"] == 1

        r = submit_artifact(sid, "scheduling", SFLA_ITINERARY)
        assert r["status"] == "accepted"

    def test_session_isolation(self, mcp_env, mock_search):
        """Two trips get different session_ids."""
        from mcp_server.server import start_trip

        r1 = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        r2 = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        assert r1["session_id"] != r2["session_id"]

    def test_hard_rules_pass_sfla_itinerary(self):
        """Standalone: fixture itinerary passes all hard rules."""
        from rules.hard_rules import check_hard_rules
        from tests.fixtures import SFLA_ITINERARY

        guardrails = yaml.safe_load(GUARDRAILS_PATH.read_text(encoding="utf-8"))
        violations = check_hard_rules(SFLA_ITINERARY, guardrails)
        assert violations == [], f"Hard rule violations: {violations}"

    def test_soft_rules_meal_coverage_warnings(self):
        """Itinerary has no food items -> meal_coverage warns on all 4 days."""
        from rules.soft_rules import check_soft_rules
        from tests.fixtures import SFLA_ITINERARY

        guardrails = yaml.safe_load(GUARDRAILS_PATH.read_text(encoding="utf-8"))
        warnings = check_soft_rules(SFLA_ITINERARY, guardrails)
        meal_warnings = [w for w in warnings if w["rule"] == "meal_coverage"]
        assert len(meal_warnings) == 4


# ── Workspace Session Persistence ──────────────────────────────


class TestSflaWorkspaceSession:
    """E2E tests for workspace-scoped session persistence."""

    def test_start_trip_with_workspace_tag(self, mcp_env, mock_search):
        from mcp_server.server import start_trip
        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                       workspace_tag="sf-la-coastal-2026")
        assert "workspace_id" in r
        assert len(r["workspace_id"]) == 12
        assert r["workspace_tag"] == "sf-la-coastal-2026"

    def test_start_trip_without_workspace_tag(self, mcp_env, mock_search):
        from mcp_server.server import start_trip
        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        assert "workspace_id" in r
        assert len(r["workspace_id"]) == 12
        assert r["workspace_tag"] is None

    def test_resume_trip_by_workspace_id(self, mcp_env, mock_search):
        from mcp_server.server import start_trip, resume_trip
        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                       workspace_tag="resume-test")
        ws_id = r["workspace_id"]

        r2 = resume_trip(ws_id)
        assert r2["status"] == "resumed"
        assert r2["session_id"] == r["session_id"]
        assert r2["workspace_id"] == ws_id

    def test_resume_trip_not_found(self, mcp_env, mock_search):
        from mcp_server.server import resume_trip
        r = resume_trip("nonexistent_ws")
        assert r["status"] == "not_found"

    def test_resume_trip_completed_session(self, mcp_env, mock_search):
        """Completed sessions should not be resumable."""
        from mcp_server.server import start_trip, resume_trip
        from mcp_server.workflow import WorkflowState
        from tripdb.bridge import update_session_status
        import mcp_server.config as cfg

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        ws_id = r["workspace_id"]
        sid = r["session_id"]

        state = WorkflowState.load(sid)
        state.status = "complete"
        state.save()
        conn = sqlite3.connect(str(cfg.DB_PATH))
        update_session_status(conn, sid, "complete")
        conn.close()

        r2 = resume_trip(ws_id)
        assert r2["status"] == "not_found"

    def test_resume_trip_blocked_session(self, mcp_env, mock_search):
        """Blocked sessions should be resumable (blocked is sub-state of active)."""
        from mcp_server.server import start_trip, resume_trip
        from mcp_server.workflow import WorkflowState

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        ws_id = r["workspace_id"]

        state = WorkflowState.load(r["session_id"])
        state.block("test block reason")

        r2 = resume_trip(ws_id)
        assert r2["status"] == "resumed"
        assert r2["workflow_status"] == "blocked"

    def test_resume_trip_stale_db_row(self, mcp_env, mock_search):
        """DB says active but JSON says complete -> not_found (stale DB)."""
        from mcp_server.server import start_trip, resume_trip
        from mcp_server.workflow import WorkflowState

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        ws_id = r["workspace_id"]

        state = WorkflowState.load(r["session_id"])
        state.status = "complete"
        state.save()

        r2 = resume_trip(ws_id)
        assert r2["status"] == "not_found"

    def test_resume_trip_missing_json(self, mcp_env, mock_search):
        """DB row exists but workflow-state.json is missing -> orphaned."""
        from mcp_server.server import start_trip, resume_trip
        import mcp_server.config as cfg

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        ws_id = r["workspace_id"]
        sid = r["session_id"]

        state_file = cfg.session_dir(sid) / "workflow-state.json"
        state_file.unlink()

        r2 = resume_trip(ws_id)
        assert r2["status"] == "orphaned"

    def test_resume_latest_single_active(self, mcp_env, mock_search):
        from mcp_server.server import start_trip, resume_latest
        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")

        r2 = resume_latest()
        assert r2["status"] == "resumed"
        assert r2["session_id"] == r["session_id"]

    def test_resume_latest_multiple_active(self, mcp_env, mock_search):
        from mcp_server.server import start_trip, resume_latest
        start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        start_trip("NYC", "2026-06-01", "2026-06-05")

        r = resume_latest()
        assert r["status"] == "multiple_active"
        assert len(r["sessions"]) == 2
        for s in r["sessions"]:
            assert "workspace_id" in s

    def test_list_trips_workspace_filter(self, mcp_env, mock_search):
        from mcp_server.server import start_trip, list_trips
        r1 = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                        workspace_tag="sfla")
        start_trip("NYC", "2026-06-01", "2026-06-05", workspace_tag="nyc")
        ws_id = r1["workspace_id"]

        r = list_trips(workspace_id=ws_id)
        assert len(r["sessions"]) == 1
        assert r["sessions"][0]["workspace_id"] == ws_id

    def test_cancel_syncs_status_to_db(self, mcp_env, mock_search):
        import mcp_server.config as cfg
        from mcp_server.server import start_trip, cancel_trip

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22")
        sid = r["session_id"]
        cancel_trip(sid, "testing")

        conn = sqlite3.connect(str(cfg.DB_PATH))
        row = conn.execute("SELECT status FROM sessions WHERE id=?", (sid,)).fetchone()
        conn.close()
        assert row[0] == "cancelled"

    def test_workspace_id_persisted_in_workflow_state(self, mcp_env, mock_search):
        from mcp_server.server import start_trip
        from mcp_server.workflow import WorkflowState

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                       workspace_tag="persist-test")
        state = WorkflowState.load(r["session_id"])
        assert state.workspace_id == r["workspace_id"]
        assert state.workspace_tag == "persist-test"

    def test_workspace_id_persisted_in_sqlite(self, mcp_env, mock_search):
        import mcp_server.config as cfg
        from mcp_server.server import start_trip

        r = start_trip("SF to LA Coast", "2026-04-19", "2026-04-22",
                       workspace_tag="db-test")
        conn = sqlite3.connect(str(cfg.DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT workspace_id, workspace_tag FROM sessions WHERE id=?",
            (r["session_id"],),
        ).fetchone()
        conn.close()
        assert row["workspace_id"] == r["workspace_id"]
        assert row["workspace_tag"] == "db-test"
