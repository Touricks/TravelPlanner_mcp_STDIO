---
date: 2026-04-02
title: "Fix Codex review + reduce over-packed POIs"
task_source: progress-next-steps
files_changed: 4
---

# Fix Codex review + reduce over-packed POIs

## Objective

Fix the broken `codex_review.py` module (used dead `codex -q` CLI flag), then use the working Codex review to identify and fix over-packed days and compressed POI durations in the SF trip itinerary.

## Changes

### Codex CLI fix

Replaced `codex -q` with `codex exec --skip-git-repo-check` in both `review/codex_review.py` and `search/enrich.py`. Added `_extract_last_json_array()` to handle Codex's duplicated stdout format. Switched from hardcoded prompt to loading `assets/prompts/codex-review.md` via `load_prompt()`.

### Itinerary reduction (33 to 28 items)

Ran Codex review against current artifacts. Based on findings, dropped 5 POIs from over-packed days:
- Day 2 (6 to 3): dropped Half Moon Bay, Monterey town walk, Carmel-by-the-Sea. Restored Stanford to 90min, Aquarium to 150min.
- Day 5 (6 to 4): dropped Serra Cross, SpaceX exterior. Restored Griffith to 150min, LA Downtown to 90min.
- Day 3: restored Hearst Castle from 35min to 39min (constrained by 16:00 staffed_closing).
- Day 4: restored Santa Barbara from 25min to 39min (same constraint).

### Restaurant fixes

Codex flagged three restaurant mismatches caused by POI drops:
- Day 2 lunch: Cafe Capistrano (Half Moon Bay) replaced with Oren's Hummus (near Stanford)
- Day 7 lunch: Casa Mendoza (Three Rivers) replaced with packed picnic (Crescent Meadow)
- Day 8 dinner: Casa Mendoza (Three Rivers) replaced with China Live (SF Chinatown)

### Files Modified

| File | Change |
|------|--------|
| `review/codex_review.py` | Fixed CLI invocation, added template loading and JSON extraction |
| `search/enrich.py` | Same CLI fix |
| `assets/data/2026-04-san-francisco/itinerary.json` | Dropped 5 POIs, restored durations (33 to 28 items) |
| `assets/data/2026-04-san-francisco/restaurants.json` | Fixed 3 mismatched restaurants |

## Decisions

- Dropped POIs chosen by lowest priority (agent_suggested) and least value (exterior-only stops, 15min compressed visits).
- Hearst Castle and Santa Barbara remain compressed (39min each) because the 16:00 staffed_closing hard rule is the binding constraint given upstream travel chains. Cannot be improved without removing upstream POIs.
- Codex review runs as a post-hoc quality gate, not just for hard constraint checking. It catches proximity mismatches that the rule engine cannot detect.

## Issues and Follow-ups

- 5 dropped POI entries remain in Notion Itinerary database (no Notion delete API available via MCP).
- Codex still flags Day 9 SF route ordering (backtracking Chinatown to Mission to Wharf) and Day 5 hotel mismatch (Hollywood vs Downtown LA evening area).
