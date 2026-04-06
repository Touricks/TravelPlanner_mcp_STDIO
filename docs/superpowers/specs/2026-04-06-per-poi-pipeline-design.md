# Per-POI Search and Transform Pipeline

**Date:** 2026-04-06
**Feature:** feat5 continuation — per-POI file isolation
**Status:** Draft

## Context

The parallel POI search (feat5) reduced wall-clock time from ~10 minutes to ~2.5 minutes by fan-out searching via `codex exec` with semaphore-controlled concurrency. However, the pipeline still merges all raw search output into a single string and runs a single `claude -p` transform, creating:

- **Single point of failure:** One bad POI in the merged text can corrupt the entire transform output.
- **No retry granularity:** A failed search requires restarting all POIs, not just the failed ones.
- **BUG-006 exposure:** Concurrent search tools can race on `complete_stage()` because shared state is mutated during parallel work.
- **No crash recovery:** Raw search results exist only in memory; process death loses all work.

This design replaces the "merge-then-transform" pattern with per-POI file persistence and per-POI transforms, while keeping the final artifact format unchanged for downstream compatibility.

## Architecture

### Data Flow

```
poi_list
  |
  v
Phase 1: Parallel Search (codex exec, sem=5)
  |  Each POI writes: sessions/{sid}/poi-raw/{name}.txt
  |  Retry: 1 attempt with exponential backoff
  |
  v
Majority Gate (>= 50% success required)
  |
  v
Phase 2: Parallel Transform (claude -p, sem=3)
  |  Each POI writes: sessions/{sid}/poi-transforms/{name}.json
  |  Schema: poi-candidate-single.json (one candidate object)
  |
  v
Merge: Collect per-POI transforms into poi-candidates.json
  |  Same schema as today: {"destination", "candidates": [...]}
  |
  v
Validate + Save Artifact + Bridge Import (unchanged)
```

### Session Directory Structure

```
sessions/{session_id}/
  poi-raw/                       # NEW: per-POI raw codex output
    bixby-bridge-a1b2c3.txt
    mcway-falls-d4e5f6.txt
  poi-transforms/                # NEW: per-POI structured JSON
    bixby-bridge-a1b2c3.json
    mcway-falls-d4e5f6.json
  poi-candidates.json            # EXISTING: merged final artifact
  poi-names.json                 # EXISTING: unchanged
  poi-search-progress.json       # EXISTING: extended with "transforming" phase
  workflow-state.json            # EXISTING: unchanged
```

Filenames use `_sanitize_poi_filename`: lowercase slug (max 80 chars) + 6-char SHA256 suffix for uniqueness.

## New Schema Contract

**File:** `assets/configs/contracts/poi-candidate-single.json`

Extracted from the `items` definition in `poi-candidates.json`. Used by `claude -p --json-schema` during per-POI transform.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "candidate_id": { "type": "string" },
    "name_en": { "type": "string" },
    "name_cn": { "type": "string" },
    "style": {
      "type": "string",
      "enum": ["nature", "tech", "culture", "food", "landmark", "coffee"]
    },
    "address": { "type": "string" },
    "city": { "type": "string" },
    "hours": { "type": "string" },
    "lat": { "type": "number" },
    "lng": { "type": "number" },
    "duration_minutes": { "type": "integer" },
    "description": { "type": "string" },
    "source": { "type": "string" },
    "priority": {
      "type": "string",
      "enum": ["must_visit", "nice_to_have", "flexible", "agent_suggested"]
    },
    "notes": { "type": "string" }
  },
  "required": ["name_en", "style", "address", "duration_minutes", "description"]
}
```

## Function Changes

### New Functions (server.py)

**`_sanitize_poi_filename(poi_name: str) -> str`**
Slugifies POI name for safe filesystem use. Lowercase, replace non-alphanumeric with hyphens, truncate to 80 chars, append 6-char SHA256 suffix.

**`_build_per_poi_transform_prompt(poi_name: str, raw_text: str, destination: str, priority: str) -> str`**
Focused transform prompt for a single POI. Instructs Claude to produce one candidate object, includes the POI's priority from the discovery phase, and carries the "do NOT invent values" constraint.

**`_transform_single_poi(poi_name, raw_path, destination, priority, semaphore, session_id) -> dict`**
Reads raw text from the persisted file, runs `_run_claude_transform` with `poi-candidate-single.json` schema, writes structured JSON to `poi-transforms/`. Returns `{"name_en", "status", "candidate", "transform_path"}` on success or `{"name_en", "status", "error"}` on failure. Includes 1 retry with backoff. Uses `TRANSFORM_PER_POI_TIMEOUT_SECONDS` — requires adding an optional `timeout` parameter to `_run_claude_transform` (currently hardcoded to `config.TRANSFORM_TIMEOUT_SECONDS`).

**`_merge_poi_transforms(destination: str, transform_results: list[dict]) -> dict`**
Collects successful per-POI candidate objects into the standard `{"destination", "search_date", "candidates": [...]}` artifact format. Downstream validation, artifact storage, and bridge import are unchanged.

### Modified Functions (server.py)

**`_search_single_poi`** — gains `session_id` parameter. After successful codex search, writes raw output to `poi-raw/{sanitized_name}.txt` via `atomic_write_text`. Returns `raw_path` instead of `raw_text`. Adds 1 retry with exponential backoff (1s, 2s) for `SearchError`.

**`_search_pois_parallel`** — two-phase orchestration:
- Phase 1: parallel codex search (existing semaphore, writes files)
- Majority gate: abort if < 50% searches succeeded
- Phase 2: parallel claude transform (new semaphore for claude processes)
- Phase 3: merge per-POI transforms into artifact
- Returns `tuple[dict, list[dict]]` (merged artifact, failures) instead of `tuple[str, list[dict]]` (raw text, failures)

**`search_pois` tool handler** — removes the standalone `_build_poi_transform_prompt` + `_run_claude_transform` sequence. Receives the merged artifact dict directly from `_search_pois_parallel`. Progress phases simplified to: load names, parallel search+transform (incremental), validate, bridge import, complete.

### New Utility (config.py)

**`atomic_write_text(path: Path, text: str) -> None`**
Sibling to existing `atomic_write_json`. Writes plain text atomically via tmpfile + rename. Creates parent directories.

### Dead Code to Remove

- `_build_poi_transform_prompt` (line 438) — replaced by `_build_per_poi_transform_prompt`
- The `merged_raw` string join at line 556 — eliminated
- The standalone transform call in `search_pois` (around line 927) — now internal to pipeline

## Configuration

New constants in `config.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `TRANSFORM_PARALLEL_LIMIT` | 3 | Max concurrent `claude -p` processes (heavier than codex) |
| `TRANSFORM_PER_POI_TIMEOUT_SECONDS` | 45 | Timeout per individual POI transform |
| `CODEX_SEARCH_MAX_RETRIES` | 1 | Retry attempts per POI search on `SearchError` |

Existing constants unchanged: `CODEX_PARALLEL_LIMIT` (5), `CODEX_PER_POI_TIMEOUT_SECONDS` (60), `CODEX_SECONDS_PER_POI_SCALING` (30).

## Progress Tracking

The `_update_poi_progress` function gains a `"transforming"` phase value. The progress file shape is unchanged — the `phase` field cycles through `"searching"` -> `"transforming"` -> `"complete"`. Per-POI status entries reflect both search and transform outcomes.

## Error Handling

- **Search retry:** `_search_single_poi` retries once on `SearchError` with exponential backoff (1s, 2s). Non-`SearchError` exceptions fail immediately.
- **Transform retry:** `_transform_single_poi` retries once on any exception with the same backoff. The raw file is already persisted, so retry reads from disk.
- **Majority gate:** After search phase, if < 50% of POIs succeeded, raises `SearchError` and aborts before transform phase. No transform budget wasted on doomed batches.
- **Transform failures:** Per-POI transform failures are collected alongside search failures. The merge step includes only successful transforms. If the merged candidate list is too small, downstream validation catches it.
- **Crash recovery (future):** The `poi-raw/` directory persists completed searches. A future enhancement could skip re-searching POIs that already have raw files on disk.

## Unchanged Components

- `_run_codex_search` — subprocess wrapper, no changes
- `_run_claude_transform` — subprocess wrapper, gains optional `timeout` parameter (defaults to existing `TRANSFORM_TIMEOUT_SECONDS` for backward compat)
- `import_pois` bridge — receives same artifact schema, dedup logic unchanged
- `bridge_sync` idempotency — hashes the final merged artifact, works as before
- `validation.validate_schema` — validates the merged artifact, unchanged
- `artifact_store.save_artifact` — saves `poi-candidates.json`, unchanged

## BUG-006 Impact

The per-POI refactor eliminates concurrent writes to shared state during the parallel work. All file writes go to isolated per-POI paths. The single `state.complete_stage("poi_search")` call happens after merge, validation, and bridge import — sequentially, with no concurrency. The remaining BUG-006 concern (race between POI/restaurant/hotel search tools calling `complete_stage` concurrently) is a separate issue not addressed here.

## Test Updates

- `test_search_notifications.py`: Update mock for `_search_pois_parallel` return type from `tuple[str, list]` to `tuple[dict, list]`. Update `_search_single_poi` mocks to expect `session_id` param and return `raw_path`.
- New tests: `_transform_single_poi` (success, failure, retry), `_merge_poi_transforms` (empty, partial, full), `_sanitize_poi_filename` (edge cases: unicode, long names, collisions).
- E2E tests (`test_mcp_e2e.py`, `test_sfla_e2e.py`): Update mocks for new pipeline shape.

## Implementation Order

1. Schema + config (additive, no behavior change)
2. New functions (additive, no callers yet)
3. Modify `_search_single_poi` (file output + retry)
4. Refactor `_search_pois_parallel` (two-phase orchestration)
5. Update `search_pois` tool handler
6. Remove dead code
7. Update tests

## Verification

1. Run `python3 -c "from mcp_server import server"` to verify import
2. Run `.venv-mcp/bin/python -m pytest tests/test_search_notifications.py -v` for unit tests
3. Run `.venv-mcp/bin/python -m pytest tests/test_mcp_e2e.py -v` for E2E tests
4. Manual test: call `search_pois` via MCP and verify `poi-raw/` and `poi-transforms/` directories are created with per-POI files
5. Verify `poi-candidates.json` has the same schema shape as before
