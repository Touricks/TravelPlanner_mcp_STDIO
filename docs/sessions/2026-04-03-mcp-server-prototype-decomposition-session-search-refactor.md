---
date: 2026-04-03
title: MCP server + prototype decomposition + session/search refactor
task_source: user-request
files_changed: 25
---

# MCP server + prototype decomposition + session/search refactor

## Objective
Build a Python MCP server for autonomous travel planning, decompose the prototype directory into proper modules, then refactor the server to use session IDs and server-side WebSearch.

## Changes

### MCP Server (initial build + /simplify cleanup)
Built FastMCP server with 12 tools, 7 resources, and 1 prompt (`plan_trip`). Autonomous workflow: `start_trip` → `get_next_action` → `submit_artifact` loop → `run_review` → Notion publish → `complete_trip`. Code review via /simplify extracted shared `atomic_write_json`, added `complete_stage()` to fix leaky abstraction, removed redundant `published_databases` field, added logging to bare except blocks.

### Prototype Decomposition
Dissolved `prototype/` into main project structure per Codex adversarial review:
- `tripdb/` — SQLite schema, 11 CLI commands, seed scripts + sources
- `config/profile.yaml` — user profile
- `tests/data/` — 160 data layer tests
- `docs/archive/prototype/` — archived v1 design docs

### Session ID + Server-Side WebSearch (feat1+feat2)
Implemented in git worktree (`feat/session-id-server-search`), merged via fast-forward:
- All tools now use `session_id` as primary key (backward compat via trip_id scan)
- Artifacts stored in `sessions/{session_id}/` (not `assets/data/`)
- 3 new async search tools (`search_pois`, `search_restaurants`, `search_hotels`) via `claude -p` subprocess
- Claude CLI auto-detected at startup
- TTL-based session cleanup (>24h stale sessions removed)

### Files Modified
| File | Change |
|------|--------|
| `mcp_server/server.py` | Added 3 search tools, changed trip_id→session_id, async subprocess |
| `mcp_server/workflow.py` | Added session_id field, session-scoped paths, TTL cleanup |
| `mcp_server/config.py` | Added SESSIONS_DIR, SEARCH_STAGES, claude CLI auto-detect |
| `mcp_server/artifact_store.py` | Changed trip_dir→session_dir |
| `mcp_server/validation.py` | Changed trip_id→session_id throughout |
| `mcp_server/prompts.py` | Rewritten: agent no longer does WebSearch |
| `CLAUDE.md` | Updated CLI path to tripdb/, added MCP Server section |
| `ARCHITECTURE.md` | Added MCP server section, updated module table |
| `README.md` | Full project documentation |
| `.mcp.json` | MCP server registration |
| `.gitignore` | Added sessions/, .worktrees/, *.db |
| `tripdb/` | New: schema.sql, cli/, seed/ (from prototype) |
| `config/profile.yaml` | Moved from prototype/userProfile/ |
| `tests/data/` | 8 test files moved from prototype |
| `docs/archive/prototype/` | Archived v1 docs (PRD, architecture, learning) |

## Decisions
- **`tripdb/` not `data/`**: Codex flagged `data/` as conflicting with `assets/data/`. `tripdb` is unambiguous.
- **Session-scoped storage**: Codex flagged two-directory model risk. Simplified to sessions/ as sole canonical store.
- **Async subprocess**: Codex flagged blocking 5-15min calls as design bug. Used `asyncio.create_subprocess_exec`.
- **Backward compatible session_id**: Codex flagged full API migration as premature. Tools accept either ID type.
- **Dedicated search prompts**: Codex flagged prompt reuse as invalid (subprocess lacks conversation context).

## Issues and Follow-ups
- `claude -p` subprocess from MCP server is untested with real WebSearch (only mock data tested)
- CLAUDE.md MCP Server section still references old `assets/data/{trip_id}/` paths — needs update
- PRD.md does not reflect MCP server or session ID requirements
- README.md does not yet document session_id API
