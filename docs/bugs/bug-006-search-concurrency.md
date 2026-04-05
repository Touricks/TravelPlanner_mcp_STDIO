# BUG-006: Search Concurrency Race + Phase Separation Design

## Current Race

`workflow.py:140` — `complete_stage()` does `load() → mutate → save()`. File writes are atomic (tmp+rename via `atomic_write_json`), but the load-modify-save cycle has no lock. Concurrent search tool calls (or retry overlapping with original) both load the same state, both mutate, and the second `save()` overwrites the first writer's mutations.

Affected call sites: `search_pois` (server.py:638), `search_restaurants` (server.py:688), `search_hotels` (server.py:738) — each calls `state.complete_stage()` after saving its artifact.

## Proposed Fix: Phase Separation

Eliminate the race by splitting search into parallel discovery + sequential merge, rather than adding locks.

### Phase 1: Parallel Discovery (no shared state)

Each `codex exec` invocation writes raw output to a unique file:

```
sessions/{session_id}/search-raw/{stage}-{timestamp}.txt
```

Register each file as an MCP resource (`search://session/{id}/raw/{stage}/{timestamp}`) for observability.

### Phase 2: Sequential Transform + Merge

After all discovery completes:

1. `claude -p --bare` reads each raw file, produces schema-validated JSON
2. `artifact_store.save_artifact()` writes final artifacts
3. `complete_stage()` calls run sequentially — single writer, no race

### Search Tool Clarification

- `codex exec` and `/call-codex` both have WebSearch available by default — search works
- `codex:rescue` is Bash-only (agent definition restricts tools) — cannot do search

### Reproduction Test

```python
async def test_concurrent_complete_stage():
    """Two concurrent complete_stage calls — assert both mutations persist."""
    state = WorkflowState.load(sid)
    # Simulate concurrent load
    state_copy = WorkflowState.load(sid)
    state.complete_stage("poi_search")
    state_copy.complete_stage("restaurants")
    # Reload and verify — currently the second write wins, first is lost
    final = WorkflowState.load(sid)
    assert "poi_search" in final.completed_stages
    assert "restaurants" in final.completed_stages  # FAILS today
```

### Crash Recovery

Orphaned raw files (no corresponding artifact) cleaned on `resume_trip()`. Incomplete transforms retried from persisted raw output.
