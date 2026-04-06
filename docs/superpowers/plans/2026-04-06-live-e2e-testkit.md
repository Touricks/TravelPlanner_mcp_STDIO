# Live E2E Test Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a fully live E2E test that drives the complete MCP workflow (start_trip through complete_trip) against a real server with real codex/claude subprocesses, using the SF-to-LA coastal trip as the test scenario.

**Architecture:** The test spawns the real MCP server via stdio using `sys.executable` (portable venv resolution), calls tools sequentially through the MCP protocol with per-tool timeouts, and validates results with structural assertions (schema compliance, non-empty results) rather than exact content matching. A separate CI workflow runs this weekly/on-demand.

**Tech Stack:** pytest, anyio, mcp SDK (client/session/stdio), existing SFLA fixtures

---

### Task 1: Register pytest marker and create pyproject.toml

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml with marker registration**

```toml
[tool.pytest.ini_options]
markers = [
    "live_e2e: requires real codex/claude API access (slow, non-deterministic)",
]
```

- [ ] **Step 2: Verify marker is recognized**

Run: `.venv-mcp/bin/python -m pytest --markers | grep live_e2e`
Expected: `@pytest.mark.live_e2e: requires real codex/claude API access (slow, non-deterministic)`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: register live_e2e pytest marker"
```

---

### Task 2: Fix venv path in test_mcp_notifications_e2e.py

**Files:**
- Modify: `tests/test_mcp_notifications_e2e.py:28-37` (server_params fixture)

- [ ] **Step 1: Replace hardcoded venv path with sys.executable and add marker**

In `tests/test_mcp_notifications_e2e.py`, replace the `server_params` fixture and add the marker to the test class.

Replace lines 28-37:
```python
@pytest.fixture
def server_params():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return StdioServerParameters(
        command=str(PROJECT_ROOT / ".venv-mcp" / "bin" / "python3"),
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
```

With:
```python
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
```

Also add `import sys` at top (already imported on line 14) and add marker to the test class. Replace line 65:
```python
class TestNotificationDelivery:
```
With:
```python
@pytest.mark.live_e2e
class TestNotificationDelivery:
```

- [ ] **Step 2: Run the fixed test to verify it starts the server**

Run: `.venv-mcp/bin/python -m pytest tests/test_mcp_notifications_e2e.py::TestNotificationDelivery::test_list_trips_sends_no_crash -v -s`
Expected: PASS (connects to server, calls list_trips, no crash)

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_notifications_e2e.py
git commit -m "fix: use sys.executable for portable MCP server venv path"
```

---

### Task 3: Switch CI to marker-based exclusion

**Files:**
- Modify: `.github/workflows/ci.yml:29-30`

- [ ] **Step 1: Replace --ignore with marker exclusion**

Replace lines 29-30:
```yaml
          python -m pytest tests/ -v --tb=short \
            --ignore=tests/test_mcp_notifications_e2e.py
```

With:
```yaml
          python -m pytest tests/ -v --tb=short -m "not live_e2e"
```

- [ ] **Step 2: Verify fast tests still work with marker exclusion**

Run: `.venv-mcp/bin/python -m pytest tests/ -v --tb=short -m "not live_e2e" 2>&1 | tail -5`
Expected: All non-live tests pass (same count as before)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "chore: switch CI from --ignore to marker-based test exclusion"
```

---

### Task 4: Create the live E2E workflow test

**Files:**
- Create: `tests/test_live_workflow_e2e.py`

- [ ] **Step 1: Write the full test file**

```python
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

                    # --- 1. start_trip ---
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

                    # --- 2. update_profile ---
                    print("\n=== Step 2: update_profile ===")
                    for section, values in PROFILE_UPDATES.items():
                        r = await session.call_tool(
                            "update_profile",
                            arguments={"updates": {section: values}},
                            read_timeout_seconds=timedelta(seconds=30),
                        )
                        d = _parse_result(r)
                        print(f"  {section}: {d.get('status', 'unknown')}")

                    # --- 3. complete_profile_collection ---
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

                    # --- 4. discover_poi_names ---
                    print("\n=== Step 4: discover_poi_names ===")
                    r = await session.call_tool(
                        "discover_poi_names",
                        arguments={"session_id": session_id},
                        read_timeout_seconds=timedelta(seconds=60),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}, count={data.get('count')}")
                    assert data.get("count", 0) >= 4, (
                        f"Expected ≥4 POI names (4 must-visits), got {data.get('count')}"
                    )

                    # --- 5. search_pois (fully live) ---
                    print("\n=== Step 5: search_pois (LIVE — may take several minutes) ===")
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
                        f"Expected ≥3 candidates, got {data.get('candidates_count')}"
                    )

                    # --- 6. submit_artifact (scheduling fixture) ---
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

                    # --- 7. search_restaurants (live) ---
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

                    # --- 8. search_hotels (live) ---
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

                    # --- 9. run_review ---
                    print("\n=== Step 9: run_review ===")
                    r = await session.call_tool(
                        "run_review",
                        arguments={"session_id": session_id, "skip_codex": True},
                        read_timeout_seconds=timedelta(seconds=120),
                    )
                    data = _parse_result(r)
                    print(f"  Result: {data.get('status', 'unknown')}")

                    # --- 10. complete_trip ---
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
```

- [ ] **Step 2: Verify the test is collected with the marker**

Run: `.venv-mcp/bin/python -m pytest tests/test_live_workflow_e2e.py --collect-only`
Expected: `<Function test_full_workflow>` collected with `live_e2e` marker

- [ ] **Step 3: Verify fast CI still excludes it**

Run: `.venv-mcp/bin/python -m pytest tests/ --collect-only -m "not live_e2e" 2>&1 | grep test_live_workflow`
Expected: No output (test is excluded)

- [ ] **Step 4: Commit**

```bash
git add tests/test_live_workflow_e2e.py
git commit -m "feat: add live E2E workflow test for MCP server"
```

---

### Task 5: Create the live E2E CI workflow

**Files:**
- Create: `.github/workflows/ci-live-e2e.yml`

- [ ] **Step 1: Write the workflow file**

```yaml
name: Live E2E

on:
  workflow_dispatch:
  schedule:
    - cron: '0 6 * * 1'

jobs:
  live-e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m venv .venv-mcp
          source .venv-mcp/bin/activate
          pip install -r requirements-mcp-dev.txt

      - name: Run live E2E
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          source .venv-mcp/bin/activate
          python -m pytest tests/test_live_workflow_e2e.py -v -s \
            --timeout=1800 -m live_e2e
```

- [ ] **Step 2: Validate YAML syntax**

Run: `.venv-mcp/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci-live-e2e.yml')); print('Valid YAML')"`
Expected: `Valid YAML`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-live-e2e.yml
git commit -m "ci: add weekly live E2E workflow with manual trigger"
```

---

### Task 6: Run live test locally and verify

- [ ] **Step 1: Run the live E2E test**

Run: `.venv-mcp/bin/python -m pytest tests/test_live_workflow_e2e.py -v -s -m live_e2e`
Expected: Either PASS (full workflow completes) or XFAIL (transient search timeout — acceptable)

- [ ] **Step 2: Run the fixed notifications test**

Run: `.venv-mcp/bin/python -m pytest tests/test_mcp_notifications_e2e.py::TestNotificationDelivery::test_list_trips_sends_no_crash -v -s`
Expected: PASS

- [ ] **Step 3: Run fast test suite to confirm nothing broken**

Run: `.venv-mcp/bin/python -m pytest tests/ -v --tb=short -m "not live_e2e" 2>&1 | tail -5`
Expected: Same pass count as before (395+ passed)
