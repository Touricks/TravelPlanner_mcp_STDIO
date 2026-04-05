# BUG-005: codex:rescue Cannot Do WebSearch — Docs Claim It Can

## User advice
1. 首先， claude -p "You are a travel POI search agent..." 调用不但慢，而且json-schema的回复形式至今没有测试. Claude声称自己支持结构化返回，但速度呢？
2. 其次，只开一个webSearch功能，如何将返回的内容写入本地文件？目前并行agent返回的文件名不做差异化，如何保证写回的内容不会相互覆盖？这个功能需要并行吗？（搜索任务需要先划分搜索边界，并行才有价值）
3. 合理的alternative：通过/call-codex直接调用codex进行web Search. /codex:rescue相当于开了一个codex subagent，这个agent不支持webSearch

## Symptom
Project documentation references `codex:rescue` for "search enrichment" in Stages 2/4, but the agent is hardcoded to `tools: Bash` only. WebSearch is structurally impossible.

## Classification

**Architecture/documentation mismatch.** The tool boundary declaration promises capabilities that the underlying agent definition cannot deliver.

## Evidence

### What the docs claim

| Source | Claim |
|--------|-------|
| `CLAUDE.md:51` | "Use /codex:rescue for Codex-assisted review and **search enrichment**" |
| `tool-boundary.md:28` | "Purpose: Codex-assisted review, diagnosis, and **search enrichment** (Stage 2/4/5)" |
| `tool-boundary.md:29` | "Can do: Delegate investigation, review, or **search tasks** to Codex CLI" |
| `PRD.md:44` | "Agent searches for POIs via WebSearch + **Codex**, generates candidate list" |

### What codex:rescue actually supports

From the agent definition:

```yaml
tools: Bash   # ← allowlist mode: ONLY Bash available
```

From the command definition:

```yaml
allowed-tools: Bash(node:*), AskUserQuestion
```

The prompt explicitly forbids additional behavior:
> "Do not inspect the repository, read files, grep, monitor progress, poll status, fetch results..."
> "Your only job is to forward the user's rescue request to the Codex companion script."

### Proof by elimination

```
codex-rescue tools allowlist = {"Bash"}
WebSearch tool name           = "WebSearch"

"WebSearch" ∉ {"Bash"} → cannot be invoked
```

AgentDefinition uses allowlist mode (`resolveAgentTools()`): when a `tools` field exists, only listed tools are available. Everything else is excluded.

## Impact

- **Stage 2 (POI search)**: The `_run_claude_search` subprocess handles search via `claude -p --allowedTools WebSearch`. codex:rescue is not in this path — so search actually works, but the docs mislead about HOW.
- **Stage 4 (restaurants/hotels)**: Same — search is via subprocess, not codex:rescue.
- **Stage 5 (review)**: codex:rescue IS used here via `review/codex_review.py` which calls `codex exec`. This works because review is text analysis (no WebSearch needed). But `codex exec` itself also has no WebSearch.
- **Documentation trust**: Anyone reading tool-boundary.md or CLAUDE.md would believe codex:rescue can do search enrichment. If they try to use it for that, it silently fails (Codex returns empty results for web queries).

## How to Fix

### Fix A: Correct the documentation (do immediately)

Remove "search enrichment" claims from docs since search is handled by `_run_claude_search` subprocess, not codex:rescue.

**CLAUDE.md:51** — change to:
```
- Use /codex:rescue for Codex-assisted review and diagnosis
```

**tool-boundary.md:28-29** — change to:
```
- **Purpose in this project:** Codex-assisted review and diagnosis (Stage 5)
- **Can do:** Delegate review or diagnostic tasks to Codex CLI
```

**PRD.md:44** — change to:
```
3. Server searches for POIs via WebSearch subprocess, generates candidate list
```

### Fix B: If search enrichment is actually needed, use the existing subprocess pattern

The project already has a working search mechanism: `_run_claude_search` spawns `claude -p --bare --allowedTools WebSearch` (after BUG-004 fix). If Codex-enriched search is desired, the architecture should be:

```
search_pois → _run_claude_search (WebSearch) → raw candidates
           → _run_codex_enrichment (codex exec) → quality scoring
           → merge raw + enrichment → final candidates
```

This keeps search and review as separate concerns with appropriate tools for each.

### Fix C: If a single agent needs both WebSearch + review capabilities

Create a dedicated search-enrichment agent/skill with proper tool access:

```yaml
# NOT codex:rescue — a new purpose-built agent
tools: WebSearch, Read
```

But this is likely unnecessary given the existing `_run_claude_search` subprocess handles search well.

## Recommended Priority

**Fix A now** — correct 3 doc files to match reality. The actual search functionality works fine via `_run_claude_search`; only the documentation is wrong about which component does it.

## Files Involved

| File | Line | Issue |
|------|------|-------|
| `CLAUDE.md` | 51 | Claims codex:rescue does "search enrichment" |
| `.claude/rules/tool-boundary.md` | 28-29 | Claims codex:rescue does "search enrichment (Stage 2/4/5)" |
| `PRD.md` | 44 | Claims "WebSearch + Codex" for POI search |
| `review/codex_review.py` | 34 | Only place codex is actually invoked — review only, no search |
