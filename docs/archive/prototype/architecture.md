# TravelPlannerNotion — Architecture

## 1. Tech Stack

- **Language**: YAML + Markdown (data layer), Python (Sentinel pipeline)
- **Frameworks**: Sentinel SDK (project maintenance), Notion MCP (output layer)
- **External services**: Notion API (via MCP server plugin:Notion:notion)
- **Entry point**: Claude Code CLI
- **Package manager**: N/A (no runtime dependencies; Sentinel pipeline uses Python stdlib)

## 2. Module Structure

| Directory | Responsibility | Key Files |
|-----------|---------------|-----------|
| `trips/` | Trip-scoped planning data — POIs, route analysis, audit trails | `{trip}/pois.yaml`, `{trip}/input.md`, `{trip}/route-analysis.md`, `{trip}/audit/` |
| `userProfile/` | User preferences and travel style | `profile.yaml` |
| `design/` | Product design artifacts — vision docs, competitor research, reports | `core/`, `references/`, `report/` |
| `docs/` | Project documentation — plans, session reports, export output | `notion-sync-plan.md`, `export/`, `import/` |

## 3. Data Flow

```
User (Claude Code)
  │
  ▼
trips/{trip}/input.md          ← Trip metadata (dates, transport)
trips/{trip}/pois.yaml         ← POI master list (33 entries, structured)
trips/{trip}/route-analysis.md ← Risk warnings, logistics, drive times
userProfile/profile.yaml       ← Travel interests, daily schedule, preferences
  │
  ▼ [Sync Workflow — reads local files, calls Notion MCP]
  │
  ├─→ notion-create-pages      → Parent page (two-column layout, To-Dos, Links)
  ├─→ notion-create-database ×3 → Travel Itinerary, Packing List, Expenses
  ├─→ notion-update-page        → Wire databases into parent page
  ├─→ notion-create-view        → Board view (by Day), table views
  └─→ notion-create-pages ×33   → POI pages with properties + Maps links
        │
        ▼
  Notion Workspace (shareable output)
```

## 4. Key Schemas

### POI Schema (pois.yaml → Notion Travel Itinerary)

| YAML Field | Notion Property | Type | Transform |
|-----------|----------------|------|-----------|
| name_en | Name | title | direct |
| name_cn | Chinese Name | text | direct |
| date | Day | select | Day N = (date - trip_start).days + 1 |
| — | Group | select | date → region lookup |
| style | Type | multi_select | nature/tech/culture/landmark → Attractions; food → Food |
| style | Style | select | direct |
| time | Time | text | direct |
| duration | Duration | text | direct |
| reason | Description | text | direct |
| note | Notes | text | direct |
| decision | Status | select | direct |
| — | Visited | checkbox | default NO |
| address | URL | url | → maps.google.com/?q={encoded_address} |
| address | page body | markdown | [address](maps_url) |

## 5. Constraints

- Notion MCP is the only output channel — no direct Notion API calls
- All trip data must conform to the pois.yaml schema for sync to work
- One-way sync only: local → Notion (no round-trip in v1)
- Column layout support in MCP content creation is assumed but unverified

## 6. Learned Facts

- To show a board view as the primary display in Notion, create a separate linked database view (data-source-url) rather than switching tabs on the source database. The linked view defaults to whichever view was created on it.
- The `_resolve_by_ref()` generic resolver handles both places and itinerary_items via table parameter. `resolve_place()` and `resolve_item()` are thin wrappers. Write commands accept UUID/ID only; name prefix is restricted to read commands.
- `trip push-notion` currently only shows dry-run counts. Full manifest generation with manifest_id and per-entity content hashes (notion_manifest.py) is deferred. The push workflow requires: CLI generates manifest → agent calls MCP → CLI marks synced.
