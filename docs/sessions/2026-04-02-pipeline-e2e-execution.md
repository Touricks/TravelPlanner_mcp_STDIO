# Pipeline E2E Execution — SF Trip (Apr 17-25, 2026)

**Date:** 2026-04-02
**Scope:** Execute pipeline stages 2-6 against SF trip data (PRD R2)

## What was done

1. **Profile extended** — Added travel_pace (3-5 POIs/day), wishlist (10 items with priorities), dietary preferences, accommodation preferences to prototype/userProfile/profile.yaml.

2. **Stage 2: POI candidates** — Generated poi-candidates.json (33 candidates) from prototype pois.yaml. Styles: nature, tech, culture, food, landmark. Priorities: must_visit, nice_to_have, agent_suggested.

3. **Stage 3: Itinerary scheduling** — Generated itinerary.json (9 days, 33 items). Resolved guardrail compliance by reordering items within days so staffed venues (tech/culture/landmark) finish before 16:00 and nature POIs before 19:00. Required reducing durations on Carmel, Monterey, Santa Barbara, Hearst Castle to fit hard constraints. Rule engine: 0 hard violations.

4. **Stage 4: Restaurants + Hotels** — Used Codex CLI (codex exec) for web search. 9 parallel restaurant searches + 8 hotel searches produced 18 restaurant recommendations and 8 hotel bookings.

5. **Stage 5: Review** — Rule engine (0 hard, 9 soft meal_coverage warnings) + Codex review (1 accept, 3 flags, 1 advisory reject on Day 6 LA→Sequoia pacing). Merged into review-report.json.

6. **Stage 6: Notion publishing** — Created parent page "SF & California Coast v3 — Pipeline Output" with 4 databases: Itinerary (33 entries, board view by day), Restaurants (18 entries), Hotels (8 entries), Notices (14 entries). All bilingual.

## Key decisions

- **claude -p fallback**: claude -p with --json-schema was too slow (15+ min per stage, $1.77/call). Switched to generating artifacts directly in-session + Codex for web search.
- **Guardrail compliance**: Prototype schedule violated staffed_closing rule on multiple days. Fixed by reordering items (staffed before nature) and reducing durations. Trade-off: Carmel reduced to 15min, Santa Barbara to 25min.
- **Codex CLI**: Uses `codex exec --skip-git-repo-check` (not `codex -q` which doesn't exist in v0.118.0).

## Artifacts

All under `assets/data/2026-04-san-francisco/`:
- poi-candidates.json (15,512 bytes, 33 candidates)
- itinerary.json (14,881 bytes, 9 days, 33 items)
- restaurants.json (5,758 bytes, 18 recommendations)
- hotels.json (2,868 bytes, 8 nights)
- review-report.json (3,468 bytes, 14 items: 1 accept, 12 flag, 1 reject)

## Notion

Parent page: https://www.notion.so/3379db12bca88143bbd5f2d92d2204a2

## Tests

30/30 passing (unchanged from previous session).
