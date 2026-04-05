# BUG-002: update_profile Lacks Schema Hints — Agent Guesses Wrong 3 Times

## Symptom

After user provides a comprehensive profile, the agent calls `update_profile` 4 times:

| Attempt | Error | What went wrong |
|---------|-------|-----------------|
| 1 | `travel_pace.pois_per_day must be a [min, max] list` | Agent sent `"3-4"` (string) instead of `[3, 4]` (list) |
| 2 | `wishlist[0] missing name_en` | Agent sent `{"must_visit": ["South Beach",...], "nice_to_have": [...]}` (dict grouped by priority) |
| 3 | `wishlist[0] missing name_en` | Agent sent same dict-of-lists structure, now with `name_en`/`name_cn` inside sub-lists |
| 4 | (success) | Agent finally sent flat list: `[{"name_en":"...", "priority":"must_visit"}, ...]` |

## Classification

**Missing tool schema documentation → repeated agent structuring errors.** Server validation works correctly — the problem is that the agent has no way to know the expected format upfront.

## Root Cause

### 1. `update_profile` tool has no input schema documentation (`server.py:718`)

```python
@mcp.tool(description="Update traveler profile (additive deep merge). Safe for incremental building.")
def update_profile(updates: dict) -> dict[str, Any]:
```

The description says nothing about expected structure of `updates`. The agent must guess:
- Is `pois_per_day` a string `"3-4"`, an int `4`, or a list `[3, 4]`?
- Is `wishlist` a dict `{"must_visit": [...]}` or a flat list `[{"name_en":..., "priority":...}]`?

### 2. Error messages don't describe the correct format

When wishlist is a dict instead of a list, `validate_profile_structure` (`schema.py:91`) iterates dict keys via `enumerate()`:

```python
for i, item in enumerate(data["wishlist"]):  # iterates KEYS if wishlist is a dict
    if "name_en" not in item:                # "name_en" not in "must_visit" → True
```

The error `wishlist[0] missing name_en` is **misleading** — it implies the first list element lacks a field, when actually the entire structure is wrong (dict vs list). This confused the agent in attempt 3: it added `name_en` fields inside the nested dicts but kept the wrong top-level structure.

### 3. Prompt doesn't include profile schema (`prompts.py`)

The `plan_trip` prompt's profile_collection section says:

```
For EACH user response:
    Extract structured data
    Call update_profile(structured_data)
```

But never provides the expected schema shape for `structured_data`.

## Why This Matters

- **Wastes 3 of 3 error budget**: `MAX_ATTEMPTS_PER_STAGE = 3`. While `update_profile` isn't a stage submission (so doesn't formally count), three retries waste tokens and time.
- **Fragile error recovery**: The agent got attempt 3 wrong because the error message didn't clearly say "wishlist must be a list of objects" — it said `wishlist[0] missing name_en`, leading the agent to keep the dict structure and just add `name_en` inside.
- **Every new user hits this**: The schema shapes (especially `pois_per_day` as `[min, max]` and wishlist as flat list) are non-obvious. Different agents will guess differently each time.

## How to Fix

### Fix A: Add schema examples to tool description (recommended, minimal)

```python
@mcp.tool(description=(
    "Update traveler profile (additive deep merge). Safe for incremental building.\n"
    "Key format rules:\n"
    "- travel_pace.pois_per_day: [min, max] list, e.g. [3, 4]\n"
    "- wishlist: list of {name_en, name_cn?, priority?} objects, "
    "e.g. [{\"name_en\": \"South Beach\", \"priority\": \"must_visit\"}]\n"
    "  Valid priorities: must_visit, nice_to_have, flexible (default)\n"
    "- dietary.budget_tier / accommodation.budget_tier: budget | moderate | premium"
))
def update_profile(updates: dict) -> dict[str, Any]:
```

### Fix B: Improve validation error messages (defense in depth)

In `validate_profile_structure`, add a type check before iterating:

```python
if "wishlist" in data:
    if not isinstance(data["wishlist"], list):
        raise ValueError(
            "wishlist must be a list of objects with name_en, not a dict. "
            "Example: [{\"name_en\": \"Place\", \"priority\": \"must_visit\"}]"
        )
    for i, item in enumerate(data["wishlist"]):
        ...
```

Similarly for `pois_per_day`, enrich the error:

```python
raise ValueError(
    "travel_pace.pois_per_day must be a [min, max] list of integers, "
    "e.g. [3, 4]. Got: " + repr(pois)
)
```

### Fix C: Add profile schema to prompt context

Include a compact schema example in the `stage-1-profile-collection.md` prompt template so the agent knows the format before its first `update_profile` call.

## Recommended Priority

**Fix A + B together** — the tool description prevents first-attempt failures, and better error messages help recovery when they do happen.

## Files Involved

| File | Line | Issue |
|------|------|-------|
| `mcp_server/server.py` | 718 | Tool description has no format hints |
| `profile/schema.py` | 90-96 | No type guard on wishlist; misleading error when dict passed |
| `profile/schema.py` | 85-86 | Error doesn't show the invalid value |
| `mcp_server/prompts.py` | 50-53 | No schema shape in profile_collection instructions |
| `assets/prompts/stage-1-profile-collection.md` | — | Missing schema example |
