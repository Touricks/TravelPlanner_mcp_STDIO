"""Integration test: connect to the real MCP server via stdio and verify
that search tool notifications (ctx.info heartbeat + ctx.report_progress)
actually reach the client.

Uses a short CODEX_SEARCH_TIMEOUT_SECONDS so the test completes quickly —
codex will timeout, but we can verify notifications arrived before that.

Run:  .venv-mcp/bin/python -m pytest tests/test_mcp_notifications_e2e.py -v -s
"""
from __future__ import annotations

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import anyio
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.fixture
def server_params():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["CODEX_SEARCH_TIMEOUT_SECONDS"] = "10"
    return StdioServerParameters(
        command=str(PROJECT_ROOT / ".venv-mcp" / "bin" / "python3"),
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


class NotificationCollector:
    def __init__(self):
        self.log_messages: list[dict] = []
        self.progress_events: list[dict] = []

    async def on_log(self, params):
        entry = {
            "level": params.level,
            "data": params.data,
            "ts": time.monotonic(),
        }
        self.log_messages.append(entry)
        print(f"  [LOG {params.level}] {params.data}")

    async def on_progress(self, progress, total, message):
        entry = {
            "progress": progress,
            "total": total,
            "message": message,
            "ts": time.monotonic(),
        }
        self.progress_events.append(entry)
        print(f"  [PROGRESS {progress}/{total}] {message}")


class TestNotificationDelivery:
    def test_list_trips_sends_no_crash(self, server_params):
        """Baseline: connect, call a fast tool, verify no crash."""

        async def run():
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "list_trips",
                        arguments={},
                        read_timeout_seconds=timedelta(seconds=10),
                    )
                    return result

        result = anyio.run(run)
        assert not result.isError

    def test_search_pois_heartbeat_and_progress(self, server_params):
        """Call search_pois — codex will fail/timeout, but we should receive
        heartbeat (ctx.info) and progress (ctx.report_progress) notifications
        before the error comes back."""

        collector = NotificationCollector()

        async def run():
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(
                    read, write,
                    logging_callback=collector.on_log,
                    read_timeout_seconds=timedelta(seconds=120),
                ) as session:
                    await session.initialize()

                    trip = await session.call_tool(
                        "start_trip",
                        arguments={
                            "destination": "Test City",
                            "start_date": "2026-06-01",
                            "end_date": "2026-06-03",
                        },
                        read_timeout_seconds=timedelta(seconds=15),
                    )
                    print(f"start_trip result: {trip.content}")

                    session_id = None
                    for item in trip.content:
                        if hasattr(item, "text"):
                            import json
                            try:
                                data = json.loads(item.text)
                                session_id = data.get("session_id")
                            except (json.JSONDecodeError, AttributeError):
                                pass

                    if not session_id:
                        pytest.skip("Could not extract session_id from start_trip")

                    print(f"\nCalling search_pois(session_id={session_id!r})...")
                    print("Expecting: heartbeat ctx.info every 30s + progress events")
                    print("-" * 60)

                    result = await session.call_tool(
                        "search_pois",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=120),
                        progress_callback=collector.on_progress,
                    )

                    print("-" * 60)
                    print(f"Final result: {result.content}")
                    return result

        anyio.run(run)

        print(f"\n=== Notification Summary ===")
        print(f"Log messages received:    {len(collector.log_messages)}")
        print(f"Progress events received: {len(collector.progress_events)}")

        for msg in collector.log_messages:
            print(f"  LOG: [{msg['level']}] {msg['data']}")
        for evt in collector.progress_events:
            print(f"  PROGRESS: {evt['progress']}/{evt['total']} - {evt['message']}")

        assert len(collector.log_messages) >= 1, (
            "Expected at least 1 log notification (ctx.info heartbeat or startup message)"
        )
        assert len(collector.progress_events) >= 1, (
            "Expected at least 1 progress notification (initial report_progress(0,4))"
        )
