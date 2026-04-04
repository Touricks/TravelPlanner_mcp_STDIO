---
date: 2026-04-02
title: "Full pipeline implementation — Sprint 1-3"
task_source: user-request
files_changed: 33
---

# Full pipeline implementation — Sprint 1-3

## Objective

Build the complete TravelPlannerAgent pipeline from empty scaffolding to a tested, runnable system. The project addresses four identified problems with the prototype: shallow user profiling, missing time guardrails, no restaurant/hotel workflow, and poor Notion visualization.

## Changes

### Project Bootstrap

Initialized the project via /start with PRD.md, ARCHITECTURE.md, CLAUDE.md, and progress.yaml. Ran /routing to classify 58 skills (19 included, 32 excluded, 7 uncertain). Ran /boundary to generate tool-boundary.md with declarations for 19 skills and 3 MCP servers.

Updated ARCHITECTURE.md to use `claude -p --output-format=json --json-schema` as the orchestration mechanism — each pipeline stage gets guaranteed schema conformance from the Claude API, replacing the originally planned Python orchestration layer.

### Sprint 1: Foundation

Created profile module (schema.py, trip_prefs.py) with deep-merge semantics for persistent user profiles and per-trip overlays. Defined guardrails.yaml with 4 hard rules (nature sunset, staffed closing, time overlap, travel time) and 3 soft rules (daily pace, region cluster, meal coverage). Created 5 JSON Schema contracts for pipeline stage outputs. Built pipeline/run.sh as the 7-stage orchestrator.

### Sprint 2: Core Pipeline

Built the rule engine (rules/evaluate.py, hard_rules.py, soft_rules.py) with CLI entry point. Created stage prompt templates for Stages 2-5. Built review module (codex_review.py, merge_report.py) that merges hard rule violations, soft warnings, and Codex review items into a unified report. Created search/enrich.py for optional Codex-based POI enrichment.

### Sprint 3: Output and Tests

Built output/notion_publisher.py (manifest builder mapping itinerary/restaurant/hotel/review data to 4 Notion databases with property schemas). Created screenshot verification module. Wrote 30 tests across 3 files covering rule engine (13 tests), profile module (10 tests), and end-to-end pipeline integration (7 tests). All 30 tests pass.

### Files Modified

| File | Change |
|------|--------|
| PRD.md | Created — 9 requirements, 3 use cases, 4 non-goals |
| ARCHITECTURE.md | Created — 7-stage pipeline with claude -p --json-schema |
| CLAUDE.md | Created — 10 project rules |
| progress.yaml | Created and updated with session entry |
| .claude/rules/tool-boundary.md | Created — 19 skill boundaries |
| docs/tool-routing-report.md | Created — routing report (approved) |
| profile/schema.py | Created — profile YAML load/save/validate/merge |
| profile/trip_prefs.py | Created — per-trip overlay handling |
| assets/configs/guardrails.yaml | Created — 4 hard + 3 soft rules |
| assets/configs/contracts/*.json | Created — 5 JSON Schema contracts |
| pipeline/run.sh | Created — 7-stage pipeline orchestrator |
| pipeline/stages/stage_prompts.py | Created — prompt template loader |
| rules/evaluate.py | Created — rule engine CLI entry point |
| rules/hard_rules.py | Created — 4 hard constraint checkers |
| rules/soft_rules.py | Created — 3 soft constraint checkers |
| assets/prompts/*.md | Created — 7 stage prompt templates |
| search/enrich.py | Created — Codex POI enrichment |
| review/codex_review.py | Created — Codex review integration |
| review/merge_report.py | Created — multi-source report merger |
| output/notion_publisher.py | Created — Notion manifest builder |
| output/property_mapping.py | Created — JSON-to-Notion property maps |
| output/verify/screenshot.py | Created — verification prompt builder |
| tests/test_rules.py | Created — 13 rule engine tests |
| tests/test_profile.py | Created — 10 profile module tests |
| tests/test_pipeline_e2e.py | Created — 7 integration tests |

## Decisions

Python 3.9 compatibility: system Python is 3.9.6, which doesn't support `X | None` syntax. Used `from __future__ import annotations` with `Optional[X]` throughout.

Pipeline orchestration via shell script rather than Python framework: `claude -p --json-schema` provides guaranteed schema conformance at the API level, making a Python orchestration layer unnecessary. The shell script chains stages with `jq` for JSON extraction.

Belt-and-suspenders guardrails: constraints are both embedded in the LLM prompt (so the model schedules with awareness) and validated post-hoc by the Python rule engine (as a hard gate). Neither alone is sufficient.

## Issues and Follow-ups

The pipeline has not been run end-to-end with real `claude -p` calls — only the rule engine, merge report, and manifest builder have been tested with synthetic data. Stages 2-4 require WebSearch and real LLM invocations. Stage 6 requires Notion MCP. Stage 7 requires Playwright.
