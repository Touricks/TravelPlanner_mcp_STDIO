# TravelPlannerAgent

Architecture and stack: see ARCHITECTURE.md
Requirements: see PRD.md

## Rules

- Pipeline stages produce YAML artifacts with validated schemas; never pass unvalidated data between stages
- `tripdb/` is the canonical SQLite data layer; CLI (`python3 -m tripdb.cli.trip`) is the ONLY write interface; Python imports from tripdb are READ-ONLY (queries via views)
- Guardrail rules in assets/configs/guardrails.yaml are the single source of truth for scheduling constraints
- Hard constraint violations block pipeline progression; soft constraint violations generate warnings for Codex review
- Profile updates are additive: new fields merge into profile.yaml without overwriting existing values
- Restaurant and hotel recommendations must reference the itinerary they were derived from (day number + region)
- Notion output uses 4 separate databases: Itinerary (board view by day), Restaurants (table), Hotels (table), Notices (table)
- Bilingual output required: populate both English and Chinese fields on all Notion entries
- Codex review prompts live in assets/prompts/ and produce structured YAML reports (accept/flag/reject per item)
- All MCP tools use session_id (not trip_id) as primary key; start_trip returns session_id; artifacts stored in sessions/{session_id}/; backward compat via trip_id scan
- Agent does NOT use WebSearch directly; search stages (poi_search, restaurants, hotels) use server-side tools (search_pois, search_restaurants, search_hotels) that run claude -p subprocess with --allowedTools WebSearch
- Search results and workflow artifacts are session-scoped in sessions/{session_id}/, NOT in assets/data/; assets/data/ is reserved for legacy pipeline/run.sh only
- Use `from __future__ import annotations` and `Optional[X]` instead of `X | None` — system Python is 3.9
- Time overlap checker must suppress parent-child relationships via parent_item_index; nested activities are intentional overlaps, not violations
- Codex CLI invocations must use `codex exec --skip-git-repo-check` for non-interactive mode. Parse stdout by extracting the last valid JSON array — codex duplicates output with session metadata.

## MCP Server

- MCP server code lives in `mcp_server/`; runs in `.venv-mcp/` (Python 3.12, FastMCP)
- Registered in `.mcp.json` as `travel-planner` server; 15 tools, 7 resources, 1 prompt
- Workflow state persisted atomically to `sessions/{session_id}/workflow-state.json`
- Use the `plan_trip` MCP prompt to trigger autonomous trip planning
- Search tools (`search_pois`, `search_restaurants`, `search_hotels`) run `claude -p` as async subprocess; agent never calls WebSearch directly
- `submit_artifact` validates against JSON Schema + rule engine before saving; never bypass it
- `run_review` is server-side only — rule engine + Codex run in Python, not delegated to agent
- REVIEW regression returns machine-readable remediation payload with stale_artifacts list
- 3-attempt error budget per stage; `resolve_blocked` for human recovery
- `record_notion_urls` supports partial publish — call after each database creation
- Stale sessions (>24h, not active) auto-cleaned on `start_trip`

## Workflow

- Stage artifacts flow: profile.yaml → poi-candidates.yaml → itinerary.yaml → restaurants.yaml + hotels.yaml → review-report.yaml → Notion
- MCP workflow: `start_trip` → loop(`get_next_action` → generate → `submit_artifact`) → `run_review` → `build_notion_manifest` → Notion MCP → `complete_trip`
- Use /progress to log session outcomes
- Use /codex:rescue for Codex-assisted review and search enrichment
- Design documents go in docs/; generated trip data goes in assets/data/
