# BUG-003: search_pois Blocks 10 Minutes With Zero Progress Feedback

## Symptom

After profile collection completes, the agent calls `search_pois(session_id)`. The tool spawns a `claude -p` subprocess that runs WebSearch queries for 30-50 POI candidates. This takes up to **10 minutes** (`SEARCH_TIMEOUT_SECONDS = 600`). During the entire execution, the MCP client receives **zero progress notifications** — the UI appears frozen.

The user sees a spinner with no indication of what's happening, whether progress is being made, or how long to wait. This applies equally to `search_restaurants` and `search_hotels`.

## Classification

**UX bug — missing progress notifications.** The search itself works correctly; the problem is silent execution.

## Root Cause

### 1. `_run_claude_search` uses blocking `proc.communicate()` with no intermediate output (`server.py:271-305`)

```python
async def _run_claude_search(prompt: str, schema_path: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        claude_cli, "-p", prompt,
        "--output-format", "json",
        "--json-schema", schema,
        "--allowedTools", "WebSearch",
        "--max-turns", "10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Blocks here for entire duration — no intermediate feedback
    stdout_bytes, stderr_bytes = await asyncio.wait_for(
        proc.communicate(), timeout=config.SEARCH_TIMEOUT_SECONDS
    )
```

`proc.communicate()` buffers all output until the subprocess exits. No intermediate data is available to report progress from.

### 2. Search tools don't use FastMCP `Context` (`server.py:497`)

```python
@mcp.tool(description="Search for POIs via WebSearch (server-side).")
async def search_pois(session_id: str) -> dict[str, Any]:
```

FastMCP provides two built-in mechanisms for progress feedback:

**a) `Context` logging** — `ctx.info()`, `ctx.warning()`, etc. send real-time messages to the MCP client:

```python
@mcp.tool
async def search_pois(session_id: str, ctx: Context) -> dict[str, Any]:
    await ctx.info("Starting POI search for Miami...")
    # ... work ...
    await ctx.info("Search complete, validating 42 candidates...")
```

**b) `Context.report_progress()`** — sends structured progress notifications:

```python
await ctx.report_progress(progress=0, total=4, message="Starting WebSearch...")
```

Neither is used anywhere in the server. Zero `Context` imports exist in `server.py`.

### 3. `claude -p` subprocess stdout is not streamed (`server.py:282-283`)

Both stdout and stderr are piped to `asyncio.subprocess.PIPE`, which buffers everything. Even if we wanted to read partial output, `claude -p --output-format json` produces a single JSON blob at the end — there's no line-by-line streaming to parse.

### 4. Timeout is 10 minutes with no early warning (`config.py:73`)

```python
SEARCH_TIMEOUT_SECONDS = 600
```

If the subprocess is slow but progressing, the user has no way to know. If it's stuck, they wait the full 10 minutes before getting a timeout error.

## Impact

- **User abandonment**: 10 minutes of no feedback feels like a hang. The screenshot shows the user interrupted the tool.
- **All 3 search stages affected**: `search_pois`, `search_restaurants`, `search_hotels` all use the same `_run_claude_search` path.
- **No way to distinguish "working" from "stuck"**: Without progress, the user can't tell if they should wait or interrupt.

## How to Fix

### Fix A: Add Context logging at tool boundaries (minimal, do first)

Inject `ctx: Context` into search tools and log lifecycle events:

```python
from fastmcp import Context

@mcp.tool(description="Search for POIs via WebSearch (server-side).")
async def search_pois(session_id: str, ctx: Context) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    await ctx.info(f"Starting POI search — this may take several minutes...")
    await ctx.report_progress(progress=0, total=3, message="Launching search subprocess")

    prompt = _build_poi_search_prompt(state)
    schema_path = config.CONTRACTS_DIR / "poi-candidates.json"

    try:
        result = await _run_claude_search(prompt, schema_path, ctx=ctx)
    except SearchError as e:
        await ctx.error(f"POI search failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=1, total=3, message="Validating results")
    # ... validation ...

    await ctx.report_progress(progress=2, total=3, message="Syncing to database")
    # ... bridge import ...

    await ctx.report_progress(progress=3, total=3, message="Search complete")
    return { ... }
```

This gives the user 4 checkpoints: start, search done, validation done, bridge done.

### Fix B: Stream stderr for heartbeat (medium effort)

Instead of `proc.communicate()`, read stderr line-by-line for heartbeat signals. `claude -p` writes progress to stderr:

```python
async def _run_claude_search(prompt, schema_path, ctx=None):
    proc = await asyncio.create_subprocess_exec(
        claude_cli, "-p", prompt, ...,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Stream stderr for heartbeat while stdout buffers
    async def _read_stderr():
        lines = []
        async for line in proc.stderr:
            text = line.decode(errors="replace").strip()
            lines.append(text)
            if ctx:
                await ctx.debug(f"[search subprocess] {text}")
        return "\n".join(lines)

    stderr_task = asyncio.create_task(_read_stderr())

    try:
        stdout_bytes = await asyncio.wait_for(
            proc.stdout.read(), timeout=config.SEARCH_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SearchError(...)

    await proc.wait()
    stderr_text = await stderr_task
    # ... parse stdout_bytes ...
```

### Fix C: Periodic heartbeat via asyncio task (simple, effective)

If subprocess doesn't emit stderr, send periodic "still working" notifications:

```python
async def _run_claude_search(prompt, schema_path, ctx=None):
    proc = await asyncio.create_subprocess_exec(...)

    async def _heartbeat():
        elapsed = 0
        while True:
            await asyncio.sleep(30)
            elapsed += 30
            if ctx:
                await ctx.info(f"Search in progress... ({elapsed}s elapsed)")

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=config.SEARCH_TIMEOUT_SECONDS
        )
    finally:
        heartbeat.cancel()
```

This sends a "still alive" message every 30 seconds.

## Recommended Priority

1. **Fix A immediately** — 10 lines, gives user 4 progress checkpoints
2. **Fix C next** — 15 lines, fills the gap during the subprocess wait
3. **Fix B optionally** — more complex, only if `claude -p` stderr is useful

## Files Involved

| File | Line | Issue |
|------|------|-------|
| `mcp_server/server.py` | 271-305 | `_run_claude_search` has no progress callbacks |
| `mcp_server/server.py` | 497, 534, 575 | `search_pois/restaurants/hotels` don't inject `Context` |
| `mcp_server/config.py` | 73 | 600s timeout with no intermediate feedback |
| (none) | — | No `from fastmcp import Context` anywhere in server |
