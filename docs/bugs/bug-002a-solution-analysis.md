# BUG-002a: Solution Analysis — Schema Enforcement for update_profile

## Proposed Approach

Use `claude -p --output-format json --json-schema profile.json` as a preprocessing step: the agent extracts user info into free text, a subprocess forces it into a validated JSON shape, then `update_profile` receives guaranteed-valid data.

## Verdict: Overkill for this specific problem, but the right pattern for a different one

### Why it's overkill here

The 3 failures aren't a *parsing* problem — the agent understood the user perfectly. It structured `pois_per_day` as `"3-4"` instead of `[3,4]` and wishlist as a dict-by-priority instead of a flat list. These are **format convention mismatches**, not comprehension failures.

Cheaper fixes that eliminate the same errors:

| Fix | Cost | Eliminates retries? |
|-----|------|-------------------|
| Better tool description (schema hints in docstring) | 0 tokens, 5 min | Yes — agent gets format right on first try |
| Better error messages ("wishlist must be a list, not dict") | 0 tokens, 5 min | Yes — agent self-corrects in 1 retry, not 3 |
| JSON Schema contract + `claude -p` subprocess | ~2k tokens per call, new infra | Yes — guaranteed valid |

The subprocess approach spawns an entire Claude instance, adds 10-30s latency, and costs tokens — all to solve a problem that a 3-line tool description fix handles for free.

### Where the subprocess approach IS the right pattern

The project already uses this pattern for **search stages** (`_run_claude_search` in `server.py:271`). It works there because:

1. **The subprocess does real work** (WebSearch) — it's not just reformatting
2. **The output is complex** (30-50 POI candidates with nested fields) — schema enforcement catches real structural issues
3. **The agent can't self-correct** — search results come from external data, not agent knowledge

For `update_profile`, the agent already has all the information (the user just said it). No external lookup needed. The only gap is knowing the target format.

### When to reconsider

If `update_profile` starts accepting richer structures (e.g., multi-source profile merges, bulk imports from external tools), then schema enforcement via subprocess becomes justified. For simple user-to-profile extraction, it's not.

## Recommended Fix

**Option 1: Enrich tool description** (do this now)

```python
@mcp.tool(description=(
    "Update traveler profile (additive deep merge). "
    "Format rules: "
    "travel_pace.pois_per_day → [min, max] int list (e.g. [3,4]). "
    "wishlist → list of {name_en, name_cn?, priority?} objects "
    "(priority: must_visit|nice_to_have|flexible). "
    "dietary/accommodation.budget_tier → budget|moderate|premium."
))
```

**Option 2: Add type guard in validation** (do this now)

```python
if "wishlist" in data:
    if not isinstance(data["wishlist"], list):
        raise ValueError(
            "wishlist must be a list of {name_en, priority} objects, "
            f"got {type(data['wishlist']).__name__}"
        )
```

Both are zero-cost, instant fixes. Together they prevent first-attempt failures AND make recovery faster when they do happen.
