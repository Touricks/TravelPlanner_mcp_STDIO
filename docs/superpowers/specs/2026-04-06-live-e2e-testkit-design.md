# Live E2E Test Kit for MCP Workflow

**Date:** 2026-04-06
**Status:** Draft

## Context

The project has two E2E testing patterns: mock-based tests (fast, deterministic, CI-friendly) and a real-server test (`test_mcp_notifications_e2e.py`) that spawns the MCP server via stdio. The real-server test is broken — it hardcodes `.venv-mcp/bin/python3` which doesn't exist in worktrees — and is excluded from CI.

The most vulnerable part of the system is `search_pois`, which now uses a per-POI pipeline (feat7) with real codex exec for web search and claude -p for structured transforms. Mock-based tests can't verify that this works against real LLM APIs. A fully live E2E test is needed.

## What Gets Built

1. **`tests/test_live_workflow_e2e.py`** — Full MCP workflow test against the real server with live codex/claude subprocesses
2. **Fix venv path** in `test_mcp_notifications_e2e.py` — replace hardcoded path with `sys.executable`
3. **`.github/workflows/ci-live-e2e.yml`** — Separate CI workflow for live tests (manual trigger + optional nightly)
4. **`conftest.py` marker** — Register `live_e2e` pytest marker for selective execution

## Trip Spec

Derived from `assets/template/CI_template.md`:

- **Destination:** SF to LA Coast
- **Dates:** 2026-04-19 to 2026-04-22
- **Route:** SF → Monterey/Big Sur → Santa Barbara
- **Must-visit:** Bixby Bridge, McWay Falls, Hearst Castle, Santa Barbara Mission
- **Workspace tag:** `sf-la-coastal-2026`

Profile is injected via `update_profile` after `start_trip` to skip interactive collection.

## Test Structure

```python
@pytest.mark.live_e2e
class TestLiveWorkflowE2E:
    def test_full_workflow(self, server_params):
        # 1. start_trip
        # 2. update_profile (inject CI_template profile)
        # 3. complete_profile_collection
        # 4. discover_poi_names → assert ≥4 names
        # 5. search_pois → assert schema-valid candidates, count ≥3
        # 6. submit_artifact("scheduling", SFLA_ITINERARY)
        # 7. search_restaurants → assert recommendations exist
        # 8. search_hotels → assert recommendations exist
        # 9. run_review → assert report returned
        # 10. complete_trip → assert status complete
```

## Server Fixture

```python
@pytest.fixture
def server_params():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return StdioServerParameters(
        command=sys.executable,  # <-- uses whatever Python runs the test
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
```

`sys.executable` resolves to the venv Python when tests are run via `.venv-mcp/bin/python -m pytest`. This works in worktrees, CI, and local dev.

## Profile Injection

After `start_trip`, call `update_profile` multiple times to build a complete profile, then call `complete_profile_collection` to advance past the profile stage:

```python
PROFILE_SECTIONS = [
    {"section": "identity", "data": {
        "name": "CI Test User",
        "languages": ["English", "Chinese"],
    }},
    {"section": "travel_interests", "data": {
        "styles": ["nature", "culture", "food"],
    }},
    {"section": "travel_style", "data": {
        "pace": "moderate",
        "budget_tier": "moderate",
    }},
    {"section": "travel_pace", "data": {
        "pois_per_day": [3, 4],
    }},
    {"section": "wishlist", "data": [
        {"name_en": "Bixby Bridge", "priority": "must_visit"},
        {"name_en": "McWay Falls", "priority": "must_visit"},
        {"name_en": "Hearst Castle", "priority": "must_visit"},
        {"name_en": "Santa Barbara Mission", "priority": "must_visit"},
    ]},
]
```

Each section is a separate `update_profile` call (additive merge). The profile must have `identity`, `travel_interests`, `travel_style`, and `travel_pace` for `complete_profile_collection` to succeed.

## Assertions

Non-deterministic LLM output means assertions check structure, not content:

| Step | Assertion |
|------|-----------|
| `start_trip` | `session_id` present, `status != "error"` |
| `discover_poi_names` | `count >= 4` (4 must-visits at minimum) |
| `search_pois` | `candidates_count >= 3`, no `validation_failed` status |
| `submit_artifact` | `status == "accepted"` |
| `search_restaurants` | `status == "complete"`, recommendations array non-empty |
| `search_hotels` | `status == "complete"`, recommendations array non-empty |
| `run_review` | Response returned (review may flag items, that's fine) |
| `complete_trip` | `status == "complete"` |

Soft assertion for `search_pois`: if it returns `search_failed` due to codex timeouts, the test logs the error and marks as `xfail` (expected failure) rather than hard-failing. This handles transient network/API issues.

## Timeouts

| Tool | Timeout |
|------|---------|
| `start_trip`, `complete_trip`, `update_profile` | 30s |
| `discover_poi_names` | 60s |
| `search_pois` | 600s (10 min, per-POI pipeline with retries) |
| `submit_artifact` | 30s |
| `search_restaurants` | 300s (5 min) |
| `search_hotels` | 300s (5 min) |
| `run_review` | 120s (2 min) |

## CI Integration

**New workflow:** `.github/workflows/ci-live-e2e.yml`

```yaml
name: Live E2E

on:
  workflow_dispatch:
  schedule:
    - cron: '0 6 * * 1'  # Weekly Monday 6am UTC

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

**Existing CI (`ci.yml`):** Add `--ignore=tests/test_live_workflow_e2e.py` alongside the existing notifications ignore. Or use marker-based exclusion: `-m "not live_e2e"`.

## Fix for Existing Test

`test_mcp_notifications_e2e.py` gets the same `sys.executable` fix in its `server_params` fixture. This unblocks it from running in worktrees. It should also get the `live_e2e` marker and be excluded from fast CI alongside the new test.

## Pytest Configuration

Add to `pyproject.toml` (or create it):

```toml
[tool.pytest.ini_options]
markers = [
    "live_e2e: requires real codex/claude API access (slow, non-deterministic)",
]
```

Update `ci.yml` to use marker exclusion:

```yaml
python -m pytest tests/ -v --tb=short -m "not live_e2e"
```

This replaces the `--ignore` flags with a cleaner marker-based approach.

## Files to Create/Modify

| File | Action |
|------|--------|
| `tests/test_live_workflow_e2e.py` | Create — full workflow test |
| `tests/test_mcp_notifications_e2e.py` | Modify — fix venv path, add marker |
| `.github/workflows/ci-live-e2e.yml` | Create — live E2E CI workflow |
| `.github/workflows/ci.yml` | Modify — switch to marker-based exclusion |
| `pyproject.toml` | Create or modify — register pytest marker |

## Verification

1. Run locally: `.venv-mcp/bin/python -m pytest tests/test_live_workflow_e2e.py -v -s`
2. Verify existing fast tests still pass: `.venv-mcp/bin/python -m pytest tests/ -v -m "not live_e2e"`
3. Verify the fixed notifications test works: `.venv-mcp/bin/python -m pytest tests/test_mcp_notifications_e2e.py -v -s`
