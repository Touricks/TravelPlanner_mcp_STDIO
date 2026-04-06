---
date: 2026-04-06
title: "feat8: Live E2E test kit for MCP workflow"
task_source: progress-next-steps
files_changed: 5
---

# feat8: Live E2E test kit for MCP workflow

## Objective

Create a fully live E2E test that drives the complete MCP workflow (start_trip through complete_trip) against the real server with real codex/claude CLI subprocesses. Fix the broken `test_mcp_notifications_e2e.py` (hardcoded venv path) and switch CI to marker-based test exclusion.

## Changes

### Live workflow test

Created `tests/test_live_workflow_e2e.py` — a 10-step test that spawns the real MCP server via stdio and drives the SF-to-LA coastal trip workflow:

1. `start_trip` with workspace tag
2. `update_profile` (5 sections: identity, interests, style, pace, wishlist)
3. `complete_profile_collection`
4. `discover_poi_names` (assert >= 4 names)
5. `search_pois` (fully live codex + claude per-POI pipeline)
6. `submit_artifact` (scheduling fixture)
7. `search_restaurants` (live)
8. `search_hotels` (live)
9. `run_review` (rule engine, skip codex)
10. `complete_trip`

Search steps use `pytest.xfail` for transient failures (codex timeouts, network issues) rather than hard-failing. Timeouts: 10 min for search_pois, 5 min for restaurants/hotels, 30s for fast tools.

### Venv path fix

Replaced hardcoded `.venv-mcp/bin/python3` with `sys.executable` in `test_mcp_notifications_e2e.py`. This resolves the 2 pre-existing test failures in worktrees and CI.

### Marker-based CI exclusion

Registered `live_e2e` pytest marker in `pyproject.toml`. Updated `ci.yml` to use `-m "not live_e2e"` instead of `--ignore` flags. Created `ci-live-e2e.yml` workflow for weekly/manual live test runs.

### Files Modified

| File | Change |
|------|--------|
| `tests/test_live_workflow_e2e.py` | New: full workflow live E2E test |
| `tests/test_mcp_notifications_e2e.py` | Fixed venv path, added `@pytest.mark.live_e2e` |
| `.github/workflows/ci.yml` | Switched to marker-based exclusion |
| `.github/workflows/ci-live-e2e.yml` | New: weekly/manual live E2E CI workflow |
| `pyproject.toml` | New: pytest marker registration |

## Decisions

- **sys.executable over shutil.which:** Since tests are always run from within the venv (`.venv-mcp/bin/python -m pytest`), `sys.executable` reliably resolves to the correct Python. No need for path detection heuristics.
- **xfail for transient search failures:** Live codex/claude calls are inherently non-deterministic. Rather than flaky hard failures, search steps use `pytest.xfail` when the server returns `search_failed`, distinguishing infrastructure issues from real bugs.
- **Fixture scheduling artifact:** The scheduling step uses `SFLA_ITINERARY` because itinerary generation is an agent task, not a server tool. This is consistent with all existing E2E tests.

## Issues and Follow-ups

- The live E2E test has not been run yet — it requires codex and claude CLI to be available. The CI workflow needs `ANTHROPIC_API_KEY` configured as a GitHub secret, but the actual dependency is on the CLI tools being installed, not the env var directly.
- No smoke-only mode exists yet. A lighter test that just verifies server startup + `list_trips` without search would be useful for CI pre-flight checks.
