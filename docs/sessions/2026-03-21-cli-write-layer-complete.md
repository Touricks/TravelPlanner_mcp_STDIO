---
date: 2026-03-21
title: "CLI write layer complete — 11 commands, 160 tests"
task_source: progress-next-steps
files_changed: 5
---

# CLI write layer complete — 11 commands, 160 tests

## Objective

Implement Phase 2 of the agent-db-proposal: a click-based CLI write layer that lets agents interact with the travel SQLite database through validated commands instead of raw SQL. The design spec was written, Codex-reviewed, and implemented across 3 sprints.

## Changes

### Design Spec + Codex Review
- Created `design/core/cli-write-layer-spec.md` — 395-line spec covering 11 commands, push strategy, testing plan
- Codex (GPT-5.4) reviewed: 2 blockers fixed (manifest_id binding, UUID-only for writes), 3 suggestions accepted (integer sort keys, service layer pattern, update-place command)
- Created `.claude/rules/cli-write-layer.md` — implementation rules with quick reference

### CLI Implementation (3 Sprints)
- **Sprint 1** (foundation): `trip status`, `trip add-place`, `trip schedule` + shared utils (resolver, audit logger, DB discovery, sort_order)
- **Sprint 2** (mutations): `trip confirm`, `trip drop`, `trip reschedule`, `trip update-place`, `trip remove-place`
- **Sprint 3** (sync/export): `trip export-yaml`, `trip push-notion` (dry-run only), `trip mark-synced`

### Files Modified
| File | Change |
|------|--------|
| `assets/database/cli/__init__.py` | Created — empty package marker |
| `assets/database/cli/utils.py` | Created — 18 functions: infrastructure (4), helpers (4), resolver (3), audit (1), services (6) |
| `assets/database/cli/trip.py` | Created — click group + 11 commands |
| `assets/database/tests/conftest.py` | Added `db_file` fixture for CLI tests |
| `assets/database/tests/test_cli.py` | Created — 62 CLI tests across 12 test classes |
| `design/core/cli-write-layer-spec.md` | Created — full design spec with Codex review log |
| `.claude/rules/cli-write-layer.md` | Created + updated — all 11 commands documented |

## Decisions

- **Service layer pattern**: All write logic in `utils.py` service functions, click handlers are thin wrappers. This ensures audit logging happens consistently and enables unit testing without CLI invocation.
- **DRY resolver**: Extracted `_resolve_by_ref()` generic function; `resolve_place()` and `resolve_item()` are thin wrappers. Avoids duplicating 25 lines of ID/UUID resolution.
- **Manifest-based push deferred**: `push-notion` currently only shows dry-run counts. Full manifest generation (manifest_id, content hashes, notion_manifest.py) is deferred until hooks integration is explored.

## Issues and Follow-ups

- **push-notion manifest generation**: Not yet implemented. The command shows pending counts but doesn't generate the JSON manifest. Requires `notion_manifest.py` module with manifest_id and per-entity content hashes.
- **push-notion full workflow**: The three-step handoff (CLI generates manifest → agent calls MCP → CLI marks synced) is designed but only the dry-run and mark-synced steps work.
- **sort_order migration**: Design spec calls for INTEGER gap-based sort keys; current schema uses REAL. The CLI computes sort_order as float (matching existing import data). Migration deferred.
- **Existing Notion-only entries**: 13 restaurant/coffee POIs added directly to Notion are not yet in pois.yaml or SQLite. Need `trip import` or manual sync.
