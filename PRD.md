---
project: TravelPlannerAgent
version: v1.0
created_at: 2026-04-02
updated_at: 2026-04-02
---

# TravelPlannerAgent — Product Requirements Document

## 1. Project Identity

- **Name**: TravelPlannerAgent
- **Problem statement**: The prototype (TravelPlannerNotion) solves local-to-Notion sync but leaves four gaps: shallow user profiling (no travel pace or wishlist), no time guardrails (nature POIs scheduled after dark, staffed venues after closing), no structured restaurant/hotel workflow (bolted on without itinerary context), and poor Notion readability (single database instead of sectioned output).
- **Target user**: Bilingual (Chinese + English) data-driven traveler using Claude Code as planning interface.
- **Scope**: Agent-driven travel planning pipeline with rule-based validation and multi-model review. Prototype serves as reference data layer; this project builds the orchestration, guardrails, and visualization pipeline from scratch.

## 2. Core Requirements

| # | Requirement | Priority | Acceptance Criteria |
|---|-------------|----------|---------------------|
| R1 | Persistent user profile with incremental updates | MUST | profile.yaml stores travel pace, style preferences, POI wishlist; new trip adds fields without overwriting existing ones |
| R2 | 7-stage agent pipeline (profile → POI search → scheduling → restaurant/hotel → review → Notion → verify) | MUST | SF trip processed through all 7 stages with YAML/JSON contract between each stage |
| R3 | Time guardrails: nature POIs before 19:00, staffed venues before 16:00 | MUST | Rule engine rejects or flags violations before Codex review; zero violations in final output |
| R4 | Restaurant recommendations tied to itinerary regions and meal windows | MUST | Each day has lunch and dinner recommendations near that day's POI cluster |
| R5 | Hotel recommendations based on nightly location clusters | MUST | Hotels placed near the densest POI region for each night block |
| R6 | Codex review on generated YAML/JSON for soft-judgment issues (pace balance, route efficiency, duplicate coverage) | MUST | Codex produces structured review with accept/flag/reject per item |
| R7 | Notion output as 4 separate databases: Itinerary, Restaurants, Hotels, Notices | MUST | Each database has board or table view with correct properties; parent page links all four |
| R8 | Rule engine for hard constraints (time windows, overlap detection, travel time feasibility) | SHOULD | Configurable rules in YAML; violations block pipeline progression |
| R9 | Screenshot verification of Notion output via Playwright or computer-use | COULD | Automated screenshot of each database view; visual diff or Codex review of screenshot |

## 3. Deliverables

- **Primary deliverable**: Working 7-stage agent pipeline that transforms user preferences + destination into a validated, visually organized Notion travel plan.
- **v1 definition of done**: SF trip (Apr 17-25, 2026) processed through the full pipeline, producing 4 Notion databases with guardrail-compliant scheduling, contextual restaurant/hotel recommendations, and a Codex review report.

## 4. Key Use Cases

### UC1: Full pipeline — new trip planning

**Actor:** Traveler
**Flow:**
1. User provides destination and dates ("SF, Apr 17-25")
2. Agent loads persistent profile.yaml, asks for trip-specific preferences (pace, wishlist POIs like Sequoia)
3. Server searches for POIs via Codex web discovery + Claude structured transform, generates candidate list
4. Agent schedules POIs with guardrails (nature < 19:00, staffed < 16:00, no overlaps)
5. Agent recommends restaurants near each day's POI cluster for lunch/dinner windows
6. Agent recommends hotels based on nightly location density
7. Rule engine validates hard constraints; Codex reviews soft judgment
8. Agent publishes to Notion as 4 databases
9. Agent takes screenshot to verify visual output
**Edge cases:**
- Wishlist POI is closed during trip dates → flag to user, suggest alternative
- No restaurants found near a remote POI cluster → expand search radius, note in Notices
- Codex flags pace imbalance (8 POIs on Day 1, 2 on Day 5) → agent rebalances

### UC2: Incremental profile update

**Actor:** Returning traveler
**Flow:**
1. User says "I now prefer slow-paced trips, max 3 POIs per day"
2. Agent updates profile.yaml travel_pace field without overwriting other preferences
3. Next trip planning uses updated pace constraint

### UC3: Post-generation review and adjustment

**Actor:** Traveler reviewing Notion output
**Flow:**
1. User views Notion board and says "Day 3 is too packed, move Muir Woods to Day 4"
2. Agent reschedules via CLI, re-runs guardrail check, updates Notion
3. Codex re-reviews affected days only (incremental review)

## 5. Assumptions and Dependencies

### Assumptions

| # | Assumption | Status | Impact if wrong |
|---|-----------|--------|-----------------|
| A1 | Prototype SQLite schema and CLI commands remain stable | confirmed | Would need migration scripts |
| A2 | Notion MCP supports batch database creation (up to 100 items) | confirmed | Would need chunked creation |
| A3 | Codex CLI is available for structured review | assumed | Fall back to Claude self-review with adversarial prompt |
| A4 | WebSearch returns sufficient POI data (hours, addresses) | assumed | May need Google Places API fallback |

### Dependencies

| # | Dependency | Purpose | Risk if unavailable |
|---|-----------|---------|---------------------|
| D1 | SQLite + CLI (prototype) | Data layer for trips, POIs, itinerary | Core functionality blocked |
| D2 | Notion MCP | Visualization output | Can fall back to YAML/Markdown export |
| D3 | Codex CLI | Soft-judgment review | Use Claude adversarial prompt as fallback |
| D4 | Playwright / computer-use MCP | Screenshot verification | Manual verification acceptable for v1 |
| D5 | WebSearch | POI and restaurant/hotel discovery | Manual input acceptable |

## 6. Constraints and Non-Goals

### Non-Goals (explicitly out of scope for v1)
- Multi-trip parallel management (one active trip at a time)
- Notion bidirectional sync (one-way publish only)
- Automatic booking (generates recommendation lists, not reservations)
- Mobile app or mobile-optimized output
- Real-time collaborative editing

### Known Limitations
- Codex review latency may slow the pipeline (async acceptable)
- Screenshot verification depends on Notion page load time
- WebSearch POI data quality varies by destination

## 7. Metrics and Targets

| Metric | Baseline (prototype) | Target (v1) |
|--------|---------------------|-------------|
| Guardrail violations in final output | unmeasured | 0 |
| Restaurant/hotel coverage per day | 0% (not implemented) | 100% (lunch + dinner + hotel per night) |
| Notion output sections | 1 database | 4 databases |
| Profile fields captured | 6 (basic) | 12+ (pace, wishlist, dietary, budget) |
| Codex review coverage | 0% | 100% of generated YAML before Notion push |

## Changelog

| Version | Date | What changed | Why |
|---------|------|-------------|-----|
| v1.0 | 2026-04-02 | Initial PRD | Project bootstrap via /start |
