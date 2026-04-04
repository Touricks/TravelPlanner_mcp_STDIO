# Setup Guide

## Prerequisites

| Requirement | Purpose | Check |
|-------------|---------|-------|
| Python 3.12+ | MCP server runtime | `python3.12 --version` |
| Claude CLI | Server-side search (search_pois, search_restaurants, search_hotels) | `claude --version` |
| Notion MCP | Stage 6: publish to Notion (optional — pipeline works through Stage 5 without it) | Check your MCP client config |

## Step 1: Create the MCP server venv

```bash
python3.12 -m venv .venv-mcp
.venv-mcp/bin/pip install -r requirements-mcp.txt

# For development/testing:
.venv-mcp/bin/pip install -r requirements-mcp-dev.txt
```

The MCP server runs in `.venv-mcp/` (Python 3.12). The rest of the project (`tripdb/`, `rules/`, `profile/`) is Python 3.9-compatible and does not need a separate install.

## Step 2: Initialize the database

```bash
# Option A: Full rebuild with seed data (from legacy trips)
python3 -m tripdb.seed.import_all

# Option B: Empty database (schema only, no seed data)
.venv-mcp/bin/python3 -c "
import sqlite3
from pathlib import Path
conn = sqlite3.connect('tripdb/travel.db')
conn.executescript(Path('tripdb/schema.sql').read_text())
conn.close()
print('Created tripdb/travel.db')
"
```

This creates `tripdb/travel.db`. The MCP server works without it (bridge operations skip gracefully), but `resume_trip` and session queries will fall back to slow disk scans instead of indexed SQLite lookups.

## Step 3: Register the MCP server

### Option A: One-liner via Claude CLI (recommended)

```bash
# Run from the project root
claude mcp add -s project travel-planner -- "$(pwd)/.venv-mcp/bin/python3" -m mcp_server.server
```

This registers the server in the project-scoped config. The server self-resolves its `PROJECT_ROOT` from `__file__`, so no `cwd` or `PYTHONPATH` env vars are needed.

### Option B: Manual `.mcp.json`

```bash
cp .mcp.json.example .mcp.json
```

Edit `.mcp.json` and replace `/ABSOLUTE/PATH/TO/proj-travel_planner` with your actual project root:

```json
{
  "mcpServers": {
    "travel-planner": {
      "command": ".venv-mcp/bin/python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/home/you/proj-travel_planner",
      "env": { "PYTHONPATH": "/home/you/proj-travel_planner" }
    }
  }
}
```

### Option C: JSON string (full control)

```bash
claude mcp add-json -s project travel-planner '{
  "command": "'"$(pwd)"'/.venv-mcp/bin/python3",
  "args": ["-m", "mcp_server.server"],
  "cwd": "'"$(pwd)"'",
  "env": {"PYTHONPATH": "'"$(pwd)"'"}
}'
```

Claude Code reads `.mcp.json` from the project root automatically. Use `-s user` instead of `-s project` to register globally.

## Step 4: Verify

```bash
# Check server loads without errors
.venv-mcp/bin/python3 -c "
from mcp_server.server import mcp
print(f'Server OK: {len(mcp._tool_manager._tools)} tools registered')
"

# Check claude CLI is reachable (needed for search tools)
claude --version

# Run the test suite
.venv-mcp/bin/python3 -m pytest tests/ -v --tb=short
```

Expected: 338 tests pass, ~1 second.

## Step 5: Use it

In your MCP client (Claude Code, etc.), the `travel-planner` server will appear with 17 tools. Start planning:

> Plan a 5-day trip to Kyoto, Japan, May 10-14. Slow pace, temples and gardens.

Or use the `plan_trip` MCP prompt for the full autonomous workflow.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: mcp` | Wrong Python or venv not activated | Use `.venv-mcp/bin/python3`, not system Python |
| `FileNotFoundError: claude CLI not found` | `claude` not on PATH | Install Claude CLI, verify with `which claude` |
| `SQLite DB not found, skipping bridge` | `tripdb/travel.db` doesn't exist | Run Step 2 |
| Search tools return errors | Claude CLI can't run `claude -p` | Ensure `claude` is authenticated and working |
| `.mcp.json` not picked up | Paths are relative or wrong | Use absolute paths in `cwd` and `PYTHONPATH` |

## Two Python Targets

This project has two distinct Python version requirements:

| Component | Python Version | Why |
|-----------|---------------|-----|
| `mcp_server/` | 3.12+ | MCP SDK (FastMCP) requires 3.10+; we target 3.12 |
| `tripdb/`, `rules/`, `profile/`, `review/`, `output/` | 3.9+ | Uses `from __future__ import annotations` and `Optional[X]` syntax for broad compatibility |

Only the MCP server venv (`.venv-mcp/`) needs Python 3.12. The shared modules are imported by the server at runtime but are written to be 3.9-compatible.
