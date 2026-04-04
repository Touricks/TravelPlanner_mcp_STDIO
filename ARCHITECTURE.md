# TravelPlannerAgent — Architecture

## 1. Tech Stack

- **Language**: Python 3.11+ (rule engine, glue scripts) + Bash (pipeline runner)
- **Data layer**: SQLite (prototype schema) + Click CLI (prototype commands)
- **Agent orchestration**: `claude -p --output-format=json --json-schema` per stage (no LangGraph/LlamaIndex)
- **Schema enforcement**: JSON Schema contracts per stage, enforced at generation time by Claude API structured outputs
- **Validation**: Rule engine (Python, YAML-configured) + Codex CLI (soft judgment)
- **Output**: Notion MCP (4 databases) + Playwright/computer-use (screenshot verification)
- **Search**: WebSearch for POI/restaurant/hotel discovery
- **Profile storage**: YAML files (persistent profile + per-trip overlay)

## 2. Pipeline Architecture

Seven stages, linear with validation gates between stages 5→6.
Each stage runs as a `claude -p` call with a JSON Schema contract that guarantees output structure.

```
Stage 1: Profile Collection
  Input:  user message + existing profile.yaml
  Output: updated profile.yaml + trip-prefs.yaml
  Schema: contracts/profile.json
  Run:    claude -p (interactive — no --json-schema, dialogue-based)

Stage 2: POI Search
  Input:  profile.yaml + destination + dates
  Output: poi-candidates.json
  Schema: contracts/poi-candidates.json
  Run:    claude -p --json-schema contracts/poi-candidates.json --allowedTools "WebSearch"
  Enrich: codex "verify POI hours/addresses" on output

Stage 3: Itinerary Scheduling
  Input:  poi-candidates.json + profile.travel_pace + guardrails.yaml
  Output: itinerary.json
  Schema: contracts/itinerary.json
  Run:    claude -p --json-schema contracts/itinerary.json < poi-candidates.json
  Post:   python rules/evaluate.py itinerary.json guardrails.yaml (hard constraint check)

Stage 4: Restaurant & Hotel Recommendation
  Input:  itinerary.json (day regions + meal windows)
  Output: restaurants.json + hotels.json
  Schema: contracts/restaurants.json, contracts/hotels.json
  Run:    two claude -p calls, each with own schema, --allowedTools "WebSearch"

Stage 5: Review & Validation
  Input:  itinerary.json + restaurants.json + hotels.json
  Output: review-report.json (accept/flag/reject per item)
  Schema: contracts/review-report.json
  Run:    python rules/evaluate.py (hard) → codex review (soft) → merge into report
  Gate:   Pipeline blocks if any hard constraint fails

Stage 6: Notion Visualization
  Input:  validated JSON artifacts
  Output: 4 Notion databases (Itinerary, Restaurants, Hotels, Notices)
  Run:    claude -p --allowedTools "mcp__notion__*" --resume $SESSION
  Note:   Uses Notion MCP tools, not --json-schema (output is side-effect, not data)

Stage 7: Screenshot Verification
  Input:  Notion page URL
  Output: screenshots + visual review report
  Run:    claude -p --allowedTools "mcp__computer-use__*" or Playwright
```

### Pipeline Runner

The orchestrator is a shell script (`pipeline/run.sh`) that chains stages:

```bash
#!/bin/bash
set -euo pipefail
TRIP_DIR="assets/data/${TRIP_ID}"
CONTRACTS="assets/configs/contracts"

# Stage 2: POI search (schema-enforced)
claude -p "Search POIs for $DEST, $DATES. Profile: $(cat profile.yaml)" \
  --output-format json \
  --json-schema "$(cat $CONTRACTS/poi-candidates.json)" \
  --allowedTools "WebSearch" \
  --max-turns 10 \
  | jq '.structured_output' > "$TRIP_DIR/poi-candidates.json"

# Stage 3: Schedule (schema-enforced + rule engine post-check)
cat "$TRIP_DIR/poi-candidates.json" | \
  claude -p "Schedule these POIs. Guardrails: $(cat assets/configs/guardrails.yaml)" \
  --output-format json \
  --json-schema "$(cat $CONTRACTS/itinerary.json)" \
  | jq '.structured_output' > "$TRIP_DIR/itinerary.json"

python3 rules/evaluate.py "$TRIP_DIR/itinerary.json" assets/configs/guardrails.yaml

# Stage 4, 5, 6, 7 follow same pattern...
```

Key flags per stage:
- `--json-schema`: enforces output contract (stages 2-5)
- `--allowedTools`: pre-approves tools without prompting (WebSearch, Notion MCP)
- `--max-turns`: bounds agent loops per stage
- `--max-budget-usd`: cost ceiling per stage
- `--resume $SESSION_ID`: carries context between stages when needed

## 3. Module Structure

| Directory | Responsibility |
|-----------|---------------|
| `pipeline/` | `run.sh` pipeline runner + per-stage prompt templates |
| `rules/` | `evaluate.py` rule engine + `guardrails.yaml` definitions |
| `profile/` | `merge.py` profile CRUD (load, merge, validate profile.yaml) |
| `review/` | Codex integration: prompt construction, result parsing, report generation |
| `output/` | Notion publishing helpers (property mapping, batch operations) |
| `output/verify/` | Screenshot capture and visual verification |
| `assets/configs/` | `guardrails.yaml` + Notion schema templates |
| `assets/configs/contracts/` | JSON Schema files per stage (poi-candidates, itinerary, restaurants, hotels, review-report) |
| `assets/data/{trip}/` | Generated JSON artifacts per trip |
| `assets/prompts/` | Codex review prompts, stage-specific system prompts |
| `tripdb/` | Canonical SQLite data layer (schema, 11 CLI commands, seed scripts) |
| `config/` | User profile (`profile.yaml`) |

## 4. Data Flow

```
profile.yaml ──┐
                ├──→ [Stage 2: Search] ──→ poi-candidates.yaml
trip-prefs.yaml─┘                              │
                                               ▼
                                    [Stage 3: Schedule]
                                        │         │
                              guardrails.yaml    itinerary.yaml
                                                   │
                                          ┌────────┼────────┐
                                          ▼        ▼        ▼
                                    [Stage 4]  restaurants  hotels
                                        │         .yaml     .yaml
                                        ▼
                                  [Stage 5: Review]
                                   rule engine → Codex
                                        │
                                   review-report.yaml
                                        │
                                  [Stage 6: Notion]
                                  4 databases created
                                        │
                                  [Stage 7: Verify]
                                  screenshot + report
```

## 5. Guardrail Rules

Rules are defined in `assets/configs/guardrails.yaml` and evaluated by the rule engine:

| Rule | Type | Constraint |
|------|------|-----------|
| nature_sunset | hard | Nature POIs must end before 19:00 |
| staffed_closing | hard | Staffed venues must end before 16:00 |
| time_overlap | hard | No overlapping time slots on same day |
| travel_time | hard | Preceding travel time must fit between consecutive POIs |
| daily_pace | soft | POI count per day within profile.travel_pace range |
| region_cluster | soft | Minimize cross-region travel within a single day |
| meal_coverage | soft | Each day should have lunch (11:30-13:30) and dinner (17:30-19:30) windows |

Hard rules block pipeline at Stage 5. Soft rules generate warnings for Codex review.

Guardrails use belt-and-suspenders: constraints are embedded in the LLM prompt (Stage 3) for generation-time awareness, then validated post-hoc by the Python rule engine (Stage 5) as a hard gate.

## 6. Stage Contracts

Each stage produces a JSON artifact conforming to a JSON Schema. `claude -p --json-schema` enforces output conformance at the API level. Limits: ≤20 strict tools/request, ≤24 optional params across all strict schemas, ≤16 anyOf unions. Each pipeline stage uses 1 schema with max 14 optional params. The rule engine (`rules/evaluate.py`) handles semantic validation (guardrail rules) that JSON Schema cannot express.

Contract files in `assets/configs/contracts/`:

| Contract | Stage | Key fields |
|----------|-------|-----------|
| `poi-candidates.json` | 2 | name_en, name_cn, style, address, hours, lat/lng |
| `itinerary.json` | 3 | days[].items[]: poi_ref, start_time, end_time, duration, region |
| `restaurants.json` | 4 | day, meal_type (lunch/dinner), name, cuisine, near_poi, address |
| `hotels.json` | 4 | night_range, name, address, near_region, price_tier |
| `review-report.json` | 5 | items[]: ref, verdict (accept/flag/reject), reason, rule_id |

## 7. MCP Server (Autonomous Workflow)

A Python MCP server (`mcp_server/`) that guides a Claude agent through the entire workflow autonomously after intent recognition. Server-side search tools delegate WebSearch to `claude -p` subprocesses, keeping the agent's context clean.

**Transport:** stdio (registered in `.mcp.json`)
**Runtime:** `.venv-mcp/` (Python 3.12, FastMCP SDK) — separate from project's 3.9-compatible code
**Claude CLI:** Auto-detected at startup (`~/.local/bin/claude`, PATH, `/opt/homebrew/bin/claude`); cached after first call. Required for server-side search tools.

### Tools (15)

| Tool | Purpose |
|------|---------|
| `start_trip` | Initialize trip + session, returns `session_id` |
| `get_next_action` | Core orchestration — returns stage instructions + input artifacts + schema |
| `submit_artifact` | Validate (JSON Schema + rule engine) and save stage output |
| `search_pois` | **Server-side** POI search via `claude -p` async subprocess |
| `search_restaurants` | **Server-side** restaurant search via `claude -p` async subprocess |
| `search_hotels` | **Server-side** hotel search via `claude -p` async subprocess |
| `run_review` | Server-side Stage 5 (hard rules + soft rules + Codex) |
| `build_notion_manifest` | Generate 4-database Notion manifest |
| `record_notion_urls` | Track partial/complete Notion publish |
| `complete_trip` | Mark workflow complete |
| `get_workflow_status` | Read-only status |
| `update_profile` | Additive profile merge |
| `list_trips` | Discover existing sessions |
| `cancel_trip` | Abandon a trip |
| `resolve_blocked` | Human-assisted recovery (retry/skip/override) |

### Resources (7)

| URI Pattern | Type | Description |
|-------------|------|-------------|
| `travel://config/guardrails` | concrete | Guardrails YAML |
| `travel://config/property-mapping` | concrete | Notion property schemas |
| `travel://session/{id}/profile` | template | Merged profile |
| `travel://session/{id}/artifact/{name}` | template | Stage artifacts |
| `travel://session/{id}/state` | template | Workflow state |
| `travel://session/{id}/notion-manifest` | template | Cached Notion manifest |
| `travel://config/contract/{name}` | template | JSON Schema contracts |

### Session Management

- `start_trip` generates a `session_id` (12-char UUID hex); all subsequent tools use it
- Artifacts stored in `sessions/{session_id}/` (session-scoped, NOT in `assets/data/`)
- Backward compat: `WorkflowState.load()` resolves `trip_id` via scan if session_id not found
- Stale sessions (>24h, not active/complete) auto-cleaned on `start_trip`

### Search Architecture

Search tools (`search_pois`, `search_restaurants`, `search_hotels`) run `claude -p` with `--allowedTools "WebSearch"` as async subprocesses (`asyncio.create_subprocess_exec`, 600s timeout). The agent never uses WebSearch directly — it calls search tools and gets structured results back.

```
Agent ──search_pois(session_id)──> Server ──claude -p subprocess──> WebSearch
                                      └──> validates + saves + returns summary
```

### Workflow State Machine

```
start_trip → POI_SEARCH → SCHEDULING → RESTAURANTS → HOTELS → REVIEW → NOTION → VERIFY → COMPLETE
                                         ↑                       │
                                         └── regress on hard ────┘
```

- 3-attempt error budget per stage → blocked → `resolve_blocked`
- REVIEW regression resets attempt budget, marks downstream artifacts stale
- Max 2 regressions per trip

### Agent Loop

The `plan_trip` MCP prompt programs the agent to:
1. Call `start_trip` — returns `session_id`
2. For search stages: call `search_pois` / `search_restaurants` / `search_hotels`
3. For scheduling: generate artifact → `submit_artifact` → advance or retry
4. `run_review` (server-side validation gate)
5. `build_notion_manifest` → publish via Notion MCP → `record_notion_urls`
6. `complete_trip`

## 8. Constraints

- `tripdb/` SQLite schema is read-only from this project's perspective; writes go through CLI (`python3 -m tripdb.cli.trip`)
- Notion MCP batch limit: 100 items per create call
- Codex CLI invocation is async; pipeline waits for completion
- MCP server requires Python 3.10+ (runs in `.venv-mcp/`)
- `claude` CLI required for server-side search tools (auto-detected at startup)
