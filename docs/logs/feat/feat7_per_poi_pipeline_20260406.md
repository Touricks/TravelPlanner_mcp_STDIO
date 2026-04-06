---
date: 2026-04-06
title: "feat7: Per-POI file isolation for search and transform pipeline"
task_source: progress-next-steps
files_changed: 8
---

# feat7: Per-POI file isolation for search and transform pipeline

## Objective

Refactor the parallel POI search from "merge all raw text into one string, run one claude transform" to per-POI file output with per-POI transforms. This eliminates the single-point-of-failure in the transform step, enables per-POI retry, persists intermediate results for crash recovery, and resolves BUG-006 shared-state concerns during concurrent search.

## Changes

### Per-POI pipeline architecture

Replaced the monolithic merge-then-transform pattern with a two-phase fan-out:

- **Phase 1 (search):** Parallel codex exec calls (semaphore=5) write raw output to individual files at `sessions/{sid}/poi-raw/{sanitized_name}.txt`. Each search retries once on `SearchError` with exponential backoff.
- **Majority gate:** If <50% of searches succeed, abort before spending transform budget.
- **Phase 2 (transform):** Parallel claude -p calls (semaphore=3) read from persisted raw files and write structured JSON to `sessions/{sid}/poi-transforms/{sanitized_name}.json`. Each transform retries once from the persisted file.
- **Merge:** Collect successful per-POI candidates into the standard `poi-candidates.json` artifact. Downstream validation, artifact storage, and bridge import are unchanged.

### New schema and config

- Created `assets/configs/contracts/poi-candidate-single.json` for per-POI structured output (single candidate object, extracted from `poi-candidates.json` items definition).
- Added config constants: `TRANSFORM_PARALLEL_LIMIT` (3), `TRANSFORM_PER_POI_TIMEOUT_SECONDS` (45), `CODEX_SEARCH_MAX_RETRIES` (1), `CODEX_SECONDS_PER_POI_SCALING` (30).
- Added `atomic_write_text()` utility alongside existing `atomic_write_json()`.
- Added optional `timeout` parameter to `_run_claude_transform`.
- Added `stdin=asyncio.subprocess.DEVNULL` to both subprocess spawn sites.

### BUG-005 resolution

Added resolution note to `docs/bugs/bug-005-codex-rescue-no-websearch.md`. The bug was correctly scoped to `codex:rescue` (Bash-only agent), not raw `codex exec` (which has WebSearch). Doc fixes were already applied in bugfix3+4. The bugfix log line 82 claiming `codex exec` lacks WebSearch is incorrect per ARCHITECTURE.md.

### Files Modified

| File | Change |
|------|--------|
| `mcp_server/server.py` | Two-phase fan-out pipeline: `_sanitize_poi_filename`, `_search_single_poi` (file output + retry), `_transform_single_poi`, `_merge_poi_transforms`, `_build_per_poi_transform_prompt`, refactored `_search_pois_parallel` and `search_pois` handler |
| `mcp_server/config.py` | New constants, `atomic_write_text` utility, `stdin=DEVNULL` |
| `assets/configs/contracts/poi-candidate-single.json` | New per-POI JSON Schema |
| `docs/bugs/bug-005-codex-rescue-no-websearch.md` | Resolution note |
| `tests/test_search_notifications.py` | Updated mocks for new return types, added 5 new tests (`TestSanitizePoiFilename`, `TestMergePoiTransforms`) |
| `tests/test_mcp_e2e.py` | Updated `mock_search` fixture for `poi-candidate-single` schema and new config constants |
| `tests/test_sfla_e2e.py` | Same mock updates |
| `tests/test_miami_e2e.py` | Same mock updates |

## Decisions

- **Separate semaphores for search and transform:** Claude -p processes are heavier than codex exec, so transform concurrency (3) is lower than search concurrency (5). These are independently tunable via environment variables.
- **Per-POI retry inside the semaphore:** Retry happens within the semaphore hold, so a retrying task doesn't release its slot and re-queue. This prevents thundering herd on retry.
- **Fixture scheduling for E2E tests:** The scheduling artifact is agent-generated, not a server tool, so all E2E tests use `SFLA_ITINERARY` fixture. This is consistent across all three test suites.

## Issues and Follow-ups

- `test_mcp_notifications_e2e.py` still fails in worktrees due to hardcoded `.venv-mcp/bin/python3` path. Fix planned as part of feat8 (live E2E test kit).
- Crash recovery (resuming from `poi-raw/` files) is architecturally enabled but not yet implemented — raw files persist, but `search_pois` doesn't check for them before re-searching.
- The per-POI timeout formula (`max(60, len(poi_list) * 30)`) grows linearly with list size. This may need a cap for very large POI lists.
