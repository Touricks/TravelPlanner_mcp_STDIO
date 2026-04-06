"""Live E2E: full MCP workflow with real codex/claude subprocesses.

Spawns the real MCP server via stdio, drives the complete trip planning
workflow using the SF-to-LA coastal trip spec from CI_template.md.

Run:  .venv-mcp/bin/python -m pytest tests/test_live_workflow_e2e.py -v -s -m live_e2e
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import anyio
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


SFLA_ITINERARY = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "sfla_itinerary.json").read_text()
)

PROFILE_UPDATES = {
    "identity": {"name": "CI Test User", "languages": ["English", "Chinese"]},
    "travel_interests": {"styles": ["nature", "culture", "food"]},
    "travel_style": {"pace": "moderate", "budget_tier": "moderate"},
    "travel_pace": {"pois_per_day": [3, 4]},
    "wishlist": [
        {"name_en": "Bixby Bridge", "priority": "must_visit"},
        {"name_en": "McWay Falls", "priority": "must_visit"},
        {"name_en": "Hearst Castle", "priority": "must_visit"},
        {"name_en": "Santa Barbara Mission", "priority": "must_visit"},
    ],
}


def _parse_result(result) -> dict:
    """Extract the JSON dict from an MCP CallToolResult."""
    for item in result.content:
        if hasattr(item, "text"):
            try:
                return json.loads(item.text)
            except (json.JSONDecodeError, AttributeError):
                continue
    return {}


@pytest.fixture
def server_params():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


@pytest.mark.live_e2e
class TestLiveWorkflowE2E:

    def test_full_workflow(self, server_params):
        """Drive the complete trip planning workflow with live search."""

        async def run():
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(
                    read, write,
                    read_timeout_seconds=timedelta(seconds=30),
                ) as session:
                    await session.initialize()

                    print("\n=== Step 1: start_trip ===")
                    r = await session.call_tool(
                        "start_trip",
                        arguments={
                            "destination": "SF to LA Coast",
                            "start_date": "2026-04-19",
                            "end_date": "2026-04-22",
                            "workspace_tag": "sf-la-coastal-2026",
                        },
                        read_timeout_seconds=timedelta(seconds=30),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")
                    assert "session_id" in data, f"No session_id in start_trip: {data}"
                    session_id = data["session_id"]

                    print("\n=== Step 2: update_profile ===")
                    for section, values in PROFILE_UPDATES.items():
                        r = await session.call_tool(
                            "update_profile",
                            arguments={"updates": {section: values}},
                            read_timeout_seconds=timedelta(seconds=30),
                        )
                        d = _parse_result(r)
                        print(f"  {section}: {d.get('status', 'unknown')}")

                    print("\n=== Step 3: complete_profile_collection ===")
                    r = await session.call_tool(
                        "complete_profile_collection",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=30),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")
                    assert data.get("status") == "accepted", (
                        f"Profile not accepted: {data}"
                    )

                    print("\n=== Step 4: discover_poi_names ===")
                    r = await session.call_tool(
                        "discover_poi_names",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=60),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}, count={data.get('count')}")
                    assert data.get("count", 0) >= 4, (
                        f"Expected >=4 POI names (4 must-visits), got {data.get('count')}"
                    )

                    print("\n=== Step 5: search_pois (LIVE) ===")
                    r = await session.call_tool(
                        "search_pois",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=600),
                    )
                    data = _parse_result(r)
                    status = data.get("status", "unknown")
                    print(f"  Result: {status}, candidates={data.get('candidates_count')}")
                    if status == "search_failed":
                        pytest.xfail(
                            f"search_pois returned search_failed (transient): {data.get('error')}"
                        )
                    assert status == "complete", f"search_pois failed: {data}"
                    assert data.get("candidates_count", 0) >= 3, (
                        f"Expected >=3 candidates, got {data.get('candidates_count')}"
                    )

                    print("\n=== Step 6: submit_artifact (scheduling) ===")
                    r = await session.call_tool(
                        "submit_artifact",
                        arguments={
                            "session_id": session_id,
                            "stage": "scheduling",
                            "data": SFLA_ITINERARY,
                        },
                        read_timeout_seconds=timedelta(seconds=30),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")
                    assert data.get("status") == "accepted", (
                        f"Scheduling not accepted: {data}"
                    )

                    print("\n=== Step 7: search_restaurants (LIVE) ===")
                    r = await session.call_tool(
                        "search_restaurants",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=300),
                    )
                    data = _parse_result(r)
                    status = data.get("status", "unknown")
                    print(f"  Result: {status}")
                    if status == "search_failed":
                        pytest.xfail(
                            f"search_restaurants failed (transient): {data.get('error')}"
                        )
                    assert status == "complete", f"search_restaurants failed: {data}"

                    print("\n=== Step 8: search_hotels (LIVE) ===")
                    r = await session.call_tool(
                        "search_hotels",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=300),
                    )
                    data = _parse_result(r)
                    status = data.get("status", "unknown")
                    print(f"  Result: {status}")
                    if status == "search_failed":
                        pytest.xfail(
                            f"search_hotels failed (transient): {data.get('error')}"
                        )
                    assert status == "complete", f"search_hotels failed: {data}"

                    print("\n=== Step 9: run_review ===")
                    r = await session.call_tool(
                        "run_review",
                        arguments={"session_id": session_id, "skip_codex": True},
                        read_timeout_seconds=timedelta(seconds=120),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")

                    print("\n=== Step 10: complete_trip ===")
                    r = await session.call_tool(
                        "complete_trip",
                        arguments={
                            "session_id": session_id,
                            "verification_notes": "Live E2E test run",
                        },
                        read_timeout_seconds=timedelta(seconds=30),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")
                    assert data.get("status") == "complete", (
                        f"complete_trip failed: {data}"
                    )

                    print("\n=== WORKFLOW COMPLETE ===")
                    return session_id

        session_id = anyio.run(run)
        assert session_id is not None
