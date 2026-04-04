# Phase 2: CLI Write Layer — Design Specification

> **Status:** Reviewed (Codex GPT-5.4, 2026-03-21)
> **Date:** 2026-03-21
> **Depends on:** Phase 1 (SQLite backend — complete, 98 tests passing)
> **Implements:** agent-db-proposal.md Phase 2

---

## 1. Overview

The CLI write layer is a Python module at `assets/database/cli/trip.py` using the `click` framework (v8.3.1). It provides validated write commands to the SQLite database, sitting between the user/agent and raw SQL.

```
User / Claude Code agent
      |
      v
  trip.py (click CLI)     ← validated writes, audit logging
      |
      v
  travel.db (SQLite)      ← 8 tables, 9 triggers, 10 views
      |
      v
  Notion MCP              ← publish-only push (via manifest)
```

**Why not raw SQL?** Per Codex v2 review: "An LLM generating UPDATE + INSERT INTO audit_log will eventually forget steps, violate constraints, or skip sync metadata." The CLI handles audit logging, maps_url computation, sort_order maintenance, and input validation automatically.

---

## 2. Design Decisions

### Q1: How does the CLI find the database?
**Precedence:** `--db` flag > `TRAVEL_DB` env var > default `assets/database/travel.db` (resolved from project root via `CLAUDE.md` detection).

### Q2: How are audit_log entries created?
**Application-level INSERT** in each command function, not SQL triggers. Triggers would fire on imports and sync_status changes, producing noise. The CLI has semantic context (action name, actor, before/after snapshots) that triggers cannot infer. A shared `log_audit()` helper serializes old/new values as JSON.

### Q3: How does `trip push-notion` work?
**Manifest-based handoff with batch ID.** The CLI generates a JSON manifest with a unique `manifest_id` and per-entity content hashes. Claude Code reads the manifest and calls Notion MCP. After success, the agent runs `trip mark-synced --manifest-id <ID>` which verifies each entity's current state matches the manifest version before marking synced. This prevents acknowledging stale or wrong records after partial failures.

### Q4: How is sort_order computed?
**Integer gap-based ranking** (revised per Codex review). Use INTEGER `sort_key` with wide initial gaps (1024, 2048, 3072...) instead of REAL midpoints. On insert between neighbors, use integer midpoint. When gap exhausted (<1 between neighbors), renumber that day's items in one transaction. This avoids floating-point precision degradation from repeated midpoint insertions. Note: schema currently uses REAL — migrate to INTEGER in implementation.

### Q5: How are places/items referenced?
**Mode-aware resolver.** For **write commands** (schedule, reschedule, confirm, drop, remove-place): accept UUID or integer ID only — deterministic targeting for agent safety. For **read commands** (status): additionally accept name prefix via case-insensitive LIKE, with hard-fail on ambiguity (never "first match wins"). Per Codex review: fuzzy resolution on writes risks silent mistakes; determinism > convenience for agent-first tools.

### Q6: How does export-yaml format output?
**Match existing pois.yaml schema exactly.** Duration: `90→1.5h`, `60→1h`, `30→30min`. Time: reconstruct from `time_start-time_end`. Group by date with comment separators.

---

## 3. Command Reference

### 3.1 `trip status`

```
trip status [--verbose]
```

Read-only dashboard showing table counts, sync state, alerts, and per-day overview. Queries: row counts, `v_pending_sync` grouped by entity_type, `day_summary`, `open_risks`, `incomplete_todos`, `unscheduled_places`.

**Expected output:**
```
Trip: San Francisco & California Coast (Apr 17-25, 2026)

  Tables           Count    Sync Status      Pending  Synced
  ────────────────────────  ───────────────────────────────
  places              46    itinerary_items     46       0
  itinerary_items     46    hotels               7       0
  hotels               7    risks                7       0
  risks                7
  todos               11    Alerts: 7 open risks, 11 incomplete todos
  reservations         5
```

### 3.2 `trip add-place`

```
trip add-place NAME_EN [--cn NAME_CN] --style STYLE [--city CITY] [--address ADDR] [--source SOURCE]
```

- `--style`: REQUIRED. One of: nature, tech, culture, food, landmark, coffee
- `--address`: If provided, auto-computes `maps_url`
- `--source`: Default `user`
- Inserts into `places`, logs to `audit_log`

**Output:** `Added place #47 (uuid: a1b2...) "Name" | style: food | city: SF`

### 3.3 `trip schedule`

```
trip schedule PLACE_REF --day DAY_NUM [--time HH:MM] [--duration MINUTES] [--region TEXT] [--notes TEXT]
```

- `PLACE_REF`: Resolved via id/uuid/name
- `--day`: REQUIRED. Validated against trip date range (1-9 for SF trip)
- Computes `date` from day number, `sort_order` from day+time
- Inserts into `itinerary_items`, logs to `audit_log`

**Output:** `Scheduled "Name" on Day 3 (2026-04-19) | time: 14:00 | item #47`

**Errors:** Place not found, day out of range, place soft-deleted, ambiguous name match

### 3.4 `trip reschedule`

```
trip reschedule ITEM_REF [--day DAY_NUM] [--time HH:MM] [--duration MINUTES]
```

At least one option required. Snapshots old values, applies changes, recomputes sort_order. Triggers auto-update `updated_at` and `sync_status` if item was synced.

**Output:** `Rescheduled "Name" (#1): Day 1 18:30 → Day 2 09:00`

### 3.5 `trip confirm`

```
trip confirm ITEM_REF
```

Sets `decision='confirmed'`. No-op if already confirmed. Warns if previously rejected.

### 3.6 `trip drop`

```
trip drop ITEM_REF [--reason TEXT]
```

Sets `decision='rejected'`. Place remains in database. If `--reason`, appends to notes.

**Output:** `Dropped "Name" (Day 3). Place still available for rescheduling.`

### 3.7 `trip remove-place`

```
trip remove-place PLACE_REF [--force]
```

Soft-deletes place (`deleted_at=now()`). Cascades to all itinerary_items for that place. Requires `--force` if active visits exist.

### 3.8 `trip push-notion`

```
trip push-notion [--dry-run] [--output FILE]
```

- `--dry-run`: Show pending counts without generating manifest
- Queries `v_pending_sync` and `v_full_itinerary`
- Categorizes entities as "create" (no notion_page_id) or "update" (has page_id, modified)
- Outputs JSON manifest with Notion-compatible property dicts

**Manifest structure:**
```json
{
  "trip_id": "2026-04-san-francisco",
  "generated_at": "...",
  "creates": [{"item_uuid": "...", "properties": {...}, "body": "..."}],
  "updates": [{"item_uuid": "...", "notion_page_id": "...", "properties": {...}}]
}
```

### 3.9 `trip mark-synced`

```
trip mark-synced UUID [--notion-id PAGE_ID]
```

After agent pushes to Notion, sets `sync_status='synced'`, `last_synced_at=now()`, and optionally `notion_page_id`.

### 3.10 `trip update-place` (added per Codex review)

```
trip update-place PLACE_REF [--name NAME_EN] [--cn NAME_CN] [--style STYLE] [--city CITY] [--address ADDR]
```

Corrects place metadata after creation. At least one option required. Snapshots old values, applies changes, recomputes maps_url if address changed. Triggers handle updated_at and sync_dirty.

### 3.11 `trip export-yaml`

```
trip export-yaml [--output FILE]
```

Exports SQLite → pois.yaml matching original format. Duration conversion: `90→1.5h`. Default output: `trips/{trip_id}/pois.yaml`.

---

## 4. Data Flow

Every write command follows this pattern:

```
1. Resolve references (id/uuid/name → row)
2. Validate inputs (CHECK values, date ranges, required fields)
3. Snapshot old values (for updates)
4. Execute write (INSERT/UPDATE — triggers fire automatically)
5. Retrieve new values
6. Insert audit_log entry
7. Print confirmation
```

### Trigger Responsibility Split

| Concern | Handled by | CLI does |
|---------|-----------|----------|
| `updated_at` | Schema triggers | Nothing |
| `sync_status` dirty | Schema triggers | Nothing |
| `audit_log` entries | **CLI** | Full responsibility |
| `maps_url` computation | **CLI** | Compute before INSERT |
| `sort_order` computation | **CLI** | Compute before INSERT/UPDATE |
| UUID generation | Schema DEFAULT | Nothing |

### audit_log — Service Layer Pattern (revised per Codex review)

Audit logging lives in a **repository/service layer** (`utils.py`), not scattered across click handlers. All write operations go through service functions that wrap INSERT/UPDATE + audit in a single transaction. This prevents drift when new write paths are added.

```python
# In utils.py — all writes go through these functions
def create_place(conn, trip_id, *, name_en, style, actor='agent', **kwargs):
    """INSERT place + audit_log entry in one transaction."""
    # ... INSERT INTO places ...
    # ... INSERT INTO audit_log ...
    conn.commit()
    return place_id, uuid

def update_decision(conn, trip_id, item_id, decision, *, actor='agent', reason=None):
    """UPDATE decision + audit_log in one transaction."""
    # ... snapshot old, UPDATE, INSERT audit ...
    conn.commit()
```

The click handlers become thin wrappers: parse args → call service function → format output.

---

## 5. Push Strategy

Three-step handoff between CLI and Claude Code agent:

```
Step 1: CLI generates manifest
  $ trip push-notion --output push-manifest.json

Step 2: Agent reads manifest, calls Notion MCP
  - For "create": notion-create-pages with properties + body
  - For "update": notion-update-page with changed properties
  - Collects notion_page_id for each created page

Step 3: CLI records sync results
  $ trip mark-synced <uuid> --notion-id <page_id>
```

**Why manifest?** The CLI cannot call MCP directly (it's a Claude Code plugin). The manifest is a structured contract. Partial failures are safe — only successful items get marked synced; the next push picks up the rest.

---

## 6. Testing Strategy

Tests in `assets/database/tests/test_cli.py` using `click.testing.CliRunner` + existing conftest fixtures.

### New Fixture

```python
@pytest.fixture
def db_file(tmp_path, schema_sql):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO trips (...) VALUES (...)")
    conn.commit()
    conn.close()
    return db_path
```

### Test Plan

| Command | Key Assertions |
|---------|---------------|
| `add-place` | Row in places, audit_log entry, maps_url computed from address |
| `schedule` | Row in itinerary_items, date computed from day, sort_order correct |
| `confirm` | decision='confirmed', audit_log with old/new |
| `drop` | decision='rejected', place still active, notes appended if --reason |
| `reschedule` | Updated row, sync_dirty trigger fires on synced items |
| `remove-place` | deleted_at set, cascade to items, --force required if active |
| `push-notion` | Manifest JSON structure, counts match v_pending_sync |
| `mark-synced` | sync_status='synced', last_synced_at set, notion_page_id stored |
| `export-yaml` | Duration conversion (90→1.5h), time reconstruction, format match |
| `status` | Correct counts, handles empty DB |

---

## 7. Module Structure

```
assets/database/cli/
    __init__.py
    trip.py              # click CLI entry point + commands
    utils.py             # resolve_ref, log_audit, compute_sort_order,
                         #   format_maps_url, minutes_to_duration_text
    notion_manifest.py   # push manifest generation (separated for testability)
```

### Implementation Sequence

| Sprint | Commands | Rationale |
|--------|----------|-----------|
| 1 | `status`, `add-place`, `schedule` | Foundation: DB connection, resolver, sort_order, audit |
| 2 | `confirm`, `drop`, `reschedule`, `remove-place`, `update-place` | Mutations: decision changes, soft delete, cascade, metadata correction |
| 3 | `export-yaml`, `push-notion`, `mark-synced` | Sync: YAML export, Notion manifest, sync loop |

### Dependencies
- `click` 8.3.1 (installed)
- `sqlite3`, `json`, `urllib.parse`, `datetime`, `pathlib` (stdlib)
- No new external dependencies

---

## 8. Expected Results — Sample Session

```bash
# Check state
$ python3 -m assets.database.cli.trip status
Trip: San Francisco & California Coast (Apr 17-25, 2026)
  places: 46 | itinerary_items: 46 | hotels: 7
  Pending sync: 60 entities | Open risks: 7

# Add a new place
$ python3 -m assets.database.cli.trip add-place "Ghirardelli Square" \
    --cn "吉拉德利广场" --style landmark --city "San Francisco" \
    --address "900 North Point St, San Francisco, CA 94109"
Added place #47 (uuid: f7e8d9c0-...) "Ghirardelli Square"

# Schedule it
$ python3 -m assets.database.cli.trip schedule 47 --day 9 --time 11:00 --duration 60
Scheduled "Ghirardelli Square" on Day 9 (2026-04-25) | time: 11:00-12:00

# Confirm it
$ python3 -m assets.database.cli.trip confirm f7e8d9c0
Confirmed: "Ghirardelli Square" (Day 9, 11:00)

# Check push status
$ python3 -m assets.database.cli.trip push-notion --dry-run
Push summary: 48 pending itinerary_items, 7 hotels, 7 risks

# Export to YAML
$ python3 -m assets.database.cli.trip export-yaml
Exported 47 POIs to trips/2026-04-san-francisco/pois.yaml
```

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Name resolver ambiguity | Error with disambiguation list; require exact match on collision |
| Push manifest staleness | Include `generated_at`; agent regenerates if >5min old |
| Audit_log growth | Not a concern at ~100s of entries; add archival in v4 if needed |
| Click framework overhead | Minimal — click is lightweight; argparse is the only alternative |
| Agent forgets mark-synced step | push-notion output includes reminder; next push re-detects pending |
| Sort key precision loss (REAL midpoints) | Use INTEGER gap-based ranking with renumber on exhaustion |
| mark-synced acknowledges wrong records | Tie to manifest_id; verify entity version matches before marking |

---

## 10. Codex Review Log

**Reviewer:** Codex (GPT-5.4)
**Date:** 2026-03-21
**Model:** gpt-5.4

### Findings Accepted

| # | Finding | Severity | Action Taken |
|---|---------|----------|-------------|
| 1 | `mark-synced` needs manifest_id binding for sync safety | Blocker | Added `manifest_id` to push strategy; mark-synced verifies entity version |
| 2 | Fuzzy name resolution on writes is risky | Blocker | Write commands now UUID/ID only; name prefix kept for reads |
| 3 | REAL midpoint sort keys degrade | Suggestion | Changed to INTEGER gap-based ranking with renumber |
| 4 | Audit logging should be in service layer, not click handlers | Suggestion | Redesigned: service functions in utils.py wrap write + audit |
| 5 | Missing `update-place` command | Suggestion | Added `trip update-place` to command reference |

### Findings Noted (no change)

| Finding | Rationale for no change |
|---------|----------------------|
| Add temp-file DB tests | Agreed in principle; will implement during Sprint 4 (testing) |
| Make `mark-synced` admin-only | Not needed — agent is the primary user; restricting access adds friction |
| `export-yaml` lowest priority in Sprint 3 | Keeping current order; export is useful for debugging during sync development |

### Findings Deferred

| Finding | Deferred to |
|---------|------------|
| Add `unschedule` command (distinct from `drop`) | v4 — current semantics of `drop` (reject decision) are sufficient |
