# TravelPlannerAgent

Architecture and stack: see ARCHITECTURE.md
Requirements: see PRD.md

## Rules

- Pipeline stages produce YAML artifacts with validated schemas; never pass unvalidated data between stages
- Prototype SQLite is the canonical data store; this project reads via CLI commands and SQL views, never writes SQL directly
- Guardrail rules in assets/configs/guardrails.yaml are the single source of truth for scheduling constraints
- Hard constraint violations block pipeline progression; soft constraint violations generate warnings for Codex review
- Profile updates are additive: new fields merge into profile.yaml without overwriting existing values
- Restaurant and hotel recommendations must reference the itinerary they were derived from (day number + region)
- Notion output uses 4 separate databases: Itinerary (board view by day), Restaurants (table), Hotels (table), Notices (table)
- Bilingual output required: populate both English and Chinese fields on all Notion entries
- Codex review prompts live in assets/prompts/ and produce structured YAML reports (accept/flag/reject per item)
- One active trip at a time; trip artifacts live in assets/data/{YYYY-MM-destination}/
- Use `from __future__ import annotations` and `Optional[X]` instead of `X | None` — system Python is 3.9
- Time overlap checker must suppress parent-child relationships via parent_item_index; nested activities are intentional overlaps, not violations
- Codex CLI invocations must use `codex exec --skip-git-repo-check` for non-interactive mode. Parse stdout by extracting the last valid JSON array — codex duplicates output with session metadata.

## MCP Server

- MCP server code lives in `mcp_server/`; runs in `.venv-mcp/` (Python 3.12, FastMCP)
- Registered in `.mcp.json` as `travel-planner` server
- The server manages workflow state, validates artifacts, and provides stage instructions; the agent does generation work
- Workflow state persisted atomically to `assets/data/{trip_id}/workflow-state.json`
- Use the `plan_trip` MCP prompt to trigger autonomous trip planning
- `submit_artifact` validates against JSON Schema + rule engine before saving; never bypass it
- `run_review` is server-side only — rule engine + Codex run in Python, not delegated to agent
- REVIEW regression returns machine-readable remediation payload with stale_artifacts list
- 3-attempt error budget per stage; `resolve_blocked` for human recovery
- `record_notion_urls` supports partial publish — call after each database creation

## Workflow

- Stage artifacts flow: profile.yaml → poi-candidates.yaml → itinerary.yaml → restaurants.yaml + hotels.yaml → review-report.yaml → Notion
- MCP workflow: `start_trip` → loop(`get_next_action` → generate → `submit_artifact`) → `run_review` → `build_notion_manifest` → Notion MCP → `complete_trip`
- Use /progress to log session outcomes
- Use /codex:rescue for Codex-assisted review and search enrichment
- Design documents go in docs/; generated trip data goes in assets/data/
