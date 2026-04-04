# TravelPlannerAgent

A travel planning system that uses an MCP server to guide a Claude agent through an autonomous 7-stage workflow: from user intent to a published Notion travel plan with itineraries, restaurants, hotels, and review notes.

## How It Works

```
User: "Plan a trip to Tokyo, Apr 10-18"
            |
            v
  +---------------+       +--------------------+
  |  Claude Agent  | <---> | travel-planner MCP |   (stdio)
  |                |       |                    |
  |  - WebSearch   |       |  - workflow state  |
  |  - Notion MCP  |       |  - validation      |
  |  - reasoning   |       |  - stage prompts   |
  +---------------+       +--------------------+
            |
            v
  +---------------+
  |  Notion MCP   |  (4 databases)
  +---------------+
```

The MCP server acts as a **workflow orchestrator** — it manages state, validates artifacts, and tells the agent what to do next. The agent does the **generation work** — searching for POIs, scheduling itineraries, and publishing to Notion.

### The Autonomous Loop

After the user makes a request, the agent runs a self-driven loop with no human intervention:

```
resume_trip(workspace_id) or resume_latest()
    |
    +---> found?  resume from where it left off
    +---> not found?
            |
            v
start_trip(destination, dates, workspace_tag="tokyo-spring")
    |                                  returns session_id + workspace_id
    v
+-> get_next_action(session_id) -----> returns stage instructions
|       |
|       v
|   Agent generates artifact       (WebSearch, scheduling, etc.)
|       |
|       v
|   submit_artifact(session_id, stage, data)
|       |
|       +---> rejected? fix violations, resubmit (max 3 attempts)
|       +---> accepted? loop back to get_next_action
|       +---> blocked?  ask user for help
|
+-- repeat until all stages complete
```

### Session Resumption

Sessions persist across conversations via `workspace_id`. When a conversation closes, the agent can resume later:

1. `resume_trip(workspace_id)` — resume a specific session (workspace_id returned by start_trip)
2. `resume_latest()` — auto-resume the most recently active session, or list multiple for user to pick
3. The agent prompt includes a Step 0 Resume Check that runs before starting any new trip

### The 7 Stages

| # | Stage | What the Agent Does | What the Server Does |
|---|-------|--------------------|--------------------|
| 1 | **POI Search** | WebSearch for 30-50 points of interest | Validates against JSON Schema |
| 2 | **Scheduling** | Arranges POIs into a day-by-day itinerary | Validates with hard rule engine (sunset times, venue closings, time overlaps, travel time) |
| 3 | **Restaurants** | WebSearch for lunch/dinner near each day's POIs | Validates day references and near_poi links |
| 4 | **Hotels** | WebSearch for hotels near nightly region clusters | Validates check-in/check-out dates |
| 5 | **Review** | (none — server-side) | Runs hard rules + soft rules + optional Codex review, merges into review report |
| 6 | **Notion** | Creates 4 Notion databases via Notion MCP | Generates the publishing manifest, tracks partial publish progress |
| 7 | **Verify** | Screenshots Notion page via Playwright | Marks trip as complete |

### Review & Regression

Stage 5 (Review) is special — it runs entirely server-side. If hard constraint violations are found, the server **regresses the workflow** back to the offending stage with a machine-readable remediation payload:

```json
{
  "status": "regressed",
  "target_stage": "scheduling",
  "violations": [{"rule": "nature_sunset", "item": "Mount Fuji", "detail": "ends at 20:00, limit is 19:00"}],
  "stale_artifacts": ["itinerary", "restaurants", "hotels"],
  "valid_artifacts": ["poi_candidates"],
  "remediation_hint": "Fix 1 violation(s) (nature_sunset). Affected: Mount Fuji"
}
```

The agent then regenerates only the stale artifacts and resubmits.

### Error Recovery

- **3-attempt budget** per stage — after 3 failed submissions, the stage is blocked
- **`resolve_blocked`** tool — human can retry (reset attempts), skip (advance past), or override (accept as-is)
- **Max 2 regressions** per trip — prevents infinite review loops
- **`cancel_trip`** — abandon a trip at any point

## MCP Server Reference

### Tools (17)

| Tool | Description |
|------|-------------|
| `start_trip` | Initialize trip with destination, dates, optional workspace_tag |
| `get_next_action` | Get stage instructions, input artifacts, output schema, prior errors |
| `submit_artifact` | Validate (JSON Schema + rule engine) and save a stage's output |
| `search_pois` | Server-side POI search via claude -p subprocess |
| `search_restaurants` | Server-side restaurant search via claude -p subprocess |
| `search_hotels` | Server-side hotel search via claude -p subprocess |
| `run_review` | Server-side Stage 5: hard rules + soft rules + optional Codex review |
| `build_notion_manifest` | Generate Notion manifest with 4 database configs + entries |
| `record_notion_urls` | Track per-database publish progress (supports partial publish) |
| `complete_trip` | Mark workflow as complete after verification |
| `get_workflow_status` | Read-only status check (current stage, attempts, artifacts) |
| `update_profile` | Additive deep-merge into user profile |
| `complete_profile_collection` | Signal profile collection is done, server validates completeness |
| `list_trips` | Discover all trips, optionally filter by workspace_id or workspace_tag |
| `cancel_trip` | Abandon a trip |
| `resolve_blocked` | Human-assisted recovery: retry / skip / override |
| `resume_trip` | Resume an active session by workspace_id (cross-conversation) |
| `resume_latest` | Resume the most recently active session, or list multiple to pick |

### Resources (7)

| URI | Description |
|-----|-------------|
| `travel://config/guardrails` | Scheduling constraint rules (YAML) |
| `travel://config/property-mapping` | Notion database property schemas |
| `travel://trip/{id}/profile` | Merged user profile (base + trip overrides) |
| `travel://trip/{id}/artifact/{name}` | Stage artifacts: `poi-candidates`, `itinerary`, `restaurants`, `hotels`, `review-report` |
| `travel://trip/{id}/state` | Workflow state (current stage, attempts, errors) |
| `travel://trip/{id}/notion-manifest` | Cached Notion publishing manifest |
| `travel://config/contract/{name}` | JSON Schema contracts per stage |

### Prompts (1)

| Prompt | Description |
|--------|-------------|
| `plan_trip` | Programs the agent's autonomous control loop. Takes `user_request` as argument. |

## Project Structure

```
SETUP.md                 Full setup guide (prerequisites, troubleshooting)
requirements-mcp.txt     MCP server venv dependencies
requirements-mcp-dev.txt Dev/test dependencies
.mcp.json.example        MCP server registration template (copy to .mcp.json)
tripdb/                  SQLite data layer (schema, 11 CLI commands, seed scripts)
mcp_server/              MCP server (17 tools, 7 resources, 1 prompt)
  server.py                FastMCP entry point
  workflow.py              State machine (stage transitions, regression, recovery)
  validation.py            JSON Schema + rule engine validation
  artifact_store.py        Atomic artifact read/write
  config.py                Paths, constants, shared utilities
  prompts.py               plan_trip prompt template
rules/                   Constraint engine
  hard_rules.py            4 hard constraints (sunset, closing, overlap, travel time)
  soft_rules.py            3 soft rules (pace, region cluster, meal coverage)
profile/                 User profile CRUD with deep-merge semantics
review/                  Codex CLI integration + report merging
output/                  Notion manifest builder + property mapping
pipeline/                Shell-based pipeline runner (alternative to MCP)
config/                  User profile (profile.yaml)
assets/
  configs/               Guardrails YAML + JSON Schema contracts
  prompts/               Stage-specific prompt templates
  data/{trip_id}/        Generated trip artifacts
```

## Quick Start

```bash
# 1. Create venv and install deps
python3.12 -m venv .venv-mcp
.venv-mcp/bin/pip install -r requirements-mcp.txt

# 2. Initialize the database
python3 -m tripdb.seed.import_all

# 3. Register the MCP server
claude mcp add -s project travel-planner -- "$(pwd)/.venv-mcp/bin/python3" -m mcp_server.server

# 4. Verify
.venv-mcp/bin/python3 -c "from mcp_server.server import mcp; print(f'OK: {len(mcp._tool_manager._tools)} tools')"
```

For the full setup guide (prerequisites, troubleshooting, two-Python-target explanation), see **[SETUP.md](SETUP.md)**.

### Use it

In Claude Code (or any MCP client), the `travel-planner` server will be available:

> Plan a 5-day trip to Kyoto, Japan, May 10-14. Slow pace, temples and gardens.

To resume a trip in a new conversation:

> Resume my Kyoto trip.

The agent's Step 0 Resume Check will call `resume_latest()` and pick up where it left off.

## Guardrails

Hard constraints (block pipeline if violated):

| Rule | Constraint |
|------|-----------|
| `nature_sunset` | Nature POIs must end before 19:00 |
| `staffed_closing` | Tech/culture/landmark venues must end before 16:00 |
| `time_overlap` | No overlapping time slots (parent-child exempt) |
| `travel_time` | Gap between POIs must fit travel time |

Soft constraints (generate warnings):

| Rule | Constraint |
|------|-----------|
| `daily_pace` | 3-5 POIs per day (from profile) |
| `region_cluster` | Max 3 distinct regions per day |
| `meal_coverage` | Each day should have lunch + dinner windows |

## Testing

```bash
# Run full test suite (338 tests, ~1s)
.venv-mcp/bin/python3 -m pytest tests/ -v --tb=short

# Run MCP workflow E2E tests only
.venv-mcp/bin/python3 -m pytest tests/test_miami_e2e.py -v
```

| Suite | What it tests |
|-------|---------------|
| `tests/test_miami_e2e.py` | Full MCP workflow E2E: start_trip through complete_trip, bridge sync, session isolation, workspace resumption |
| `tests/test_pipeline_e2e.py` | Rule engine + manifest builder with SF fixture data |
| `tests/data/test_e2e.py` | CLI lifecycle (add/schedule/confirm/reschedule/drop/export) |
| `tests/data/test_bridge.py` | MCP artifact -> SQLite bridge sync (import, dedup, idempotency, workspace) |
| `tests/data/test_cli.py` | CLI command unit tests (all 11 commands) |
| `tests/data/test_schema.py` | Database schema constraints, views, triggers |
| `tests/test_rules.py` | Hard + soft rule engine with edge cases |
| `tests/test_profile*.py` | Profile loading, validation, completeness, elicitation workflow |

## Bilingual Output

All artifacts and Notion entries include both English and Chinese fields (`name_en` / `name_cn`). The 4 Notion databases are:

- **Itinerary** (board view, grouped by day)
- **Restaurants** (table view)
- **Hotels** (table view)
- **Notices** (table view — flags and rejections from review)
