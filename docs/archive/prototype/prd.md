---
project: TravelPlannerNotion
version: v1.0
created_at: 2026-03-21
updated_at: 2026-03-21
---

# TravelPlannerNotion — Product Requirements Document

## 1. Project Identity

- **Name**: TravelPlannerNotion
- **Problem statement**: No existing tool bridges the "brainstorm a trip" phase and the "organized, shareable itinerary" output. Notion has templates but a steep learning curve; dedicated travel apps lack flexibility. Users who plan trips collaboratively with AI end up with rich data (POIs, schedules, risk warnings) trapped in local files with no visual, shareable output.
- **Target user**: Bilingual (Chinese + English) travelers who plan data-driven trips using Claude Code and want structured Notion output without learning Notion's database system.
- **Scope**: CLI workflow tool (Claude Code + Notion MCP)

## 2. Core Requirements

| # | Requirement | Priority | Acceptance Criteria |
|---|-------------|----------|---------------------|
| R1 | Create a Notion travel plan page from local YAML trip data via MCP | MUST | Running the sync produces a Notion page with Travel Itinerary database containing all POIs from pois.yaml |
| R2 | Travel Itinerary database supports bilingual POI names (English + Chinese) | MUST | Each POI page has both `Name` (English) and `Chinese Name` fields populated |
| R3 | POIs are organized by Day (board view) and filterable by Region/Style | MUST | Notion board view shows Day 1-N columns; Group and Style select properties allow filtering |
| R4 | Auto-generate To-Do checklist from route analysis risk warnings and logistics | SHOULD | To-Do section contains actionable items derived from route-analysis.md (ticket bookings, road checks, gear prep) |
| R5 | Multi-LLM review trail preserved in audit log | SHOULD | audit-log.yaml records reviewer responses, accepted/rejected inputs, and decision summaries per revision |
| R6 | Packing List and Expenses databases created with correct schema | SHOULD | Empty databases with the same schema as the Japan template are created under the travel plan page |
| R7 | Each POI page contains a Google Maps link constructed from address | SHOULD | POI page body includes a clickable link to maps.google.com with the POI address |
| R8 | Trip metadata (dates, transport, daily schedule) displayed on parent page | COULD | Parent page header or description section shows trip dates, car rental info, and daily schedule |

## 3. Deliverables

- **Primary deliverable**: Working Claude Code workflow that reads `pois.yaml` + `input.md` + `route-analysis.md` and creates a complete Notion travel plan page via MCP
- **v1 definition of done**: SF trip (Apr 17-25, 2026) successfully synced to Notion with 33 POIs, board view, To-Dos, and supporting databases

## 4. Key Use Cases

### UC1: First-time sync — local YAML to Notion

**Actor:** Traveler (project owner)
**Flow:**
1. User has completed trip planning in Claude Code (POIs in pois.yaml, route analysis done, audit reviewed)
2. User runs sync workflow via Claude Code
3. System creates parent Notion page with two-column layout
4. System creates Travel Itinerary, Packing List, and Expenses databases
5. System batch-creates 33 POI pages with properties + Google Maps links
6. System creates board view grouped by Day
7. User opens Notion page and sees organized trip plan

**Edge cases:**
- Notion MCP not connected → fail with clear error message
- POI missing required fields (name_en, date) → skip POI, warn user
- Batch create fails mid-way → report which POIs succeeded/failed

### UC2: Review and refine in Notion

**Actor:** Traveler + travel companions
**Flow:**
1. User shares Notion page link with travel companions
2. Companions browse POIs by Day (board view) or by Region (filter)
3. Companions check/uncheck Visited status, add Notes
4. User updates Status field (pending → confirmed/rejected)

**Edge cases:**
- Companion edits POI properties in Notion → changes stay in Notion only (no round-trip to YAML)

## 5. Assumptions and Dependencies

### Assumptions

| # | Assumption | Status | Impact if wrong |
|---|-----------|--------|-----------------|
| A1 | Notion MCP supports creating pages with `<columns>` layout in content | assumed | Fall back to sequential (non-column) layout |
| A2 | Notion MCP `create-pages` can batch 33 pages in one call | assumed | Split into smaller batches |
| A3 | multi_select properties accept JSON array strings | assumed | Change property format |
| A4 | User has Notion MCP server configured and authenticated | confirmed | Sync cannot proceed without MCP |

### Dependencies

| # | Dependency | Version/Constraint | Risk if unavailable |
|---|-----------|-------------------|---------------------|
| D1 | Notion MCP Server (plugin:Notion:notion) | Current | Core dependency — sync impossible without it |
| D2 | Claude Code CLI | Current | Entry point for the workflow |
| D3 | Local trip data (pois.yaml, input.md) | Structured YAML/MD | No data to sync |

## 6. Constraints and Non-Goals

### Non-Goals (explicitly out of scope for v1)

- **Notion → YAML round-trip sync**: Changes in Notion are NOT synced back to local files
- **Auto-generated POI images**: Users add photos manually in Notion after sync
- **Multi-trip management**: v1 handles one trip at a time; no trip list or dashboard
- **Packing List / Expenses auto-fill**: These databases are created empty with correct schema
- **Guided trip planning**: v1 does NOT guide users through planning a trip; it only syncs existing plans to Notion

### Known Limitations

- Notion MCP content creation may not support all Notion block types (columns, synced blocks)
- No offline support — requires internet for MCP calls
- POI data must be in the specific pois.yaml schema to sync

### Risks

- Notion MCP API may have rate limits on batch page creation
- Column layout in Notion-flavored Markdown is not fully documented — may require fallback

## 7. Metrics and Targets

N/A — personal project / research prototype.

## 8. Success Criteria

1. SF trip synced to Notion with all 33 POIs visible in board view
2. Each POI has bilingual name, time, duration, style, and Google Maps link
3. To-Do checklist contains logistics items from route analysis
4. Visual structure matches Japan Travel Planner template pattern

## Changelog

| Version | Date | What changed | Why |
|---------|------|-------------|-----|
| v1.0 | 2026-03-21 | Initial PRD | Project bootstrap via /start |
