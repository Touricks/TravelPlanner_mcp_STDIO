# BUG-004: search_pois Spawns 49 Recursive Subprocesses (Fork Bomb)

## Symptom

A single `search_pois(session_id)` call produces **49 independent `claude -p` sessions**, all with the same prompt "You are a travel POI search agent...", all created within the same minute. Each session runs WebSearch independently, consuming tokens, API quota, and system resources.

Screenshot shows `Resume Session (10 of 49)` — all identical search prompts.

## Classification

**Critical — recursive subprocess spawning.** Resource exhaustion, runaway cost, potential rate-limiting.

## Root Cause

### The recursion chain

```
Parent agent
  └─ calls search_pois(session_id) via MCP
       └─ MCP server spawns: claude -p "You are a travel POI search agent..."
            └─ subprocess starts in PROJECT_ROOT (no cwd= override)
            └─ subprocess reads .mcp.json from working directory
            └─ .mcp.json starts ANOTHER travel-planner MCP server instance
            └─ subprocess now sees search_pois as an available MCP tool
            └─ model calls search_pois (it's a POI search prompt, search_pois looks relevant)
                 └─ NEW MCP server instance calls _run_claude_search
                 └─ spawns ANOTHER claude -p subprocess
                 └─ ... recursive spawning continues ...
```

### Three failures combine to create this:

#### 1. No `cwd=` isolation on subprocess (`server.py:276`)

```python
proc = await asyncio.create_subprocess_exec(
    claude_cli, "-p", prompt,
    "--output-format", "json",
    "--json-schema", schema,
    "--allowedTools", "WebSearch",
    "--max-turns", "10",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    # NO cwd= parameter! Inherits MCP server's working directory
)
```

The subprocess inherits the MCP server's working directory, which is `PROJECT_ROOT` — the same directory containing `.mcp.json`.

#### 2. `.mcp.json` defines the travel-planner server in PROJECT_ROOT

```json
{
  "mcpServers": {
    "travel-planner": {
      "command": ".venv-mcp/bin/python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/Users/carrick/ResearchWorkspace/proj-travel_planner"
    }
  }
}
```

When `claude -p` starts in this directory, it auto-discovers `.mcp.json` and starts a **new instance** of the travel-planner MCP server.

#### 3. `--allowedTools WebSearch` doesn't prevent MCP tool loading

`--allowedTools` controls which tools can execute without permission prompting — it does **not** prevent MCP servers from being loaded from `.mcp.json`. The subprocess gets both WebSearch AND all 18 travel-planner MCP tools. The model, seeing `search_pois` and a prompt about POI searching, naturally calls it — triggering recursion.

### Why 49?

Each subprocess has `--max-turns 10`. Across recursive levels with multiple tool-call turns, the total session count compounds. The recursion only stops when:
- `--max-turns` limit is hit at each level, or
- `SEARCH_TIMEOUT_SECONDS` (600s) expires, or
- System resources are exhausted

## Impact

- **Cost explosion**: 49 independent Claude sessions, each doing WebSearch. Estimated 49x normal token cost for a single search stage.
- **Rate limiting risk**: 49 concurrent WebSearch calls may trigger API rate limits.
- **10-minute freeze**: All 49 subprocesses must complete (or timeout) before the parent gets a result. This explains BUG-003's 10-minute wait.
- **Resource exhaustion**: 49 Python processes + 49 Claude CLI processes running simultaneously.
- **Applies to all 3 search tools**: `search_pois`, `search_restaurants`, `search_hotels` all use `_run_claude_search`.

## How to Fix

### Fix A: Use `--bare` flag (recommended, 1-line fix)

The `claude` CLI supports `--bare` mode which skips auto-discovery of `.mcp.json`, hooks, skills, and plugins:

```python
proc = await asyncio.create_subprocess_exec(
    claude_cli, "-p", prompt,
    "--bare",                    # ← ADD THIS: prevents .mcp.json loading
    "--output-format", "json",
    "--json-schema", schema,
    "--allowedTools", "WebSearch",
    "--max-turns", "10",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

This ensures the subprocess has ONLY WebSearch available — no MCP tools, no recursion.

### Fix B: Isolate working directory (defense in depth)

Even with `--bare`, set `cwd=` to a temp directory as defense-in-depth:

```python
import tempfile

proc = await asyncio.create_subprocess_exec(
    claude_cli, "-p", prompt,
    "--bare",
    "--output-format", "json",
    "--json-schema", schema,
    "--allowedTools", "WebSearch",
    "--max-turns", "10",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=tempfile.gettempdir(),   # ← No .mcp.json here
)
```

### Fix C: Add recursion guard (belt-and-suspenders)

Set an environment variable to detect recursive invocations:

```python
import os

env = os.environ.copy()
if env.get("TRAVEL_PLANNER_SEARCH_DEPTH"):
    raise SearchError("Recursive search detected — aborting")
env["TRAVEL_PLANNER_SEARCH_DEPTH"] = "1"

proc = await asyncio.create_subprocess_exec(
    claude_cli, "-p", prompt,
    "--bare",
    ...,
    env=env,
)
```

## Recommended Priority

**Fix A immediately** — single flag addition, eliminates the recursion entirely.
**Fix B alongside** — 1 extra line, prevents regression if `--bare` behavior changes.
**Fix C for paranoia** — useful if other subprocess patterns are added later.

## Files Involved

| File | Line | Issue |
|------|------|-------|
| `mcp_server/server.py` | 276-284 | `_run_claude_search` missing `--bare` and `cwd=` |
| `.mcp.json` | 1-12 | Defines travel-planner server in same directory subprocess runs in |
| `mcp_server/config.py` | 73 | 600s timeout allows recursion to run for 10 minutes |

## Relationship to Other Bugs

- **BUG-003** (10-minute silence): The 10-minute wait is partially explained by 49 subprocesses all running concurrently, each doing WebSearch. Fixing BUG-004 will likely reduce search time to 1-2 minutes.
