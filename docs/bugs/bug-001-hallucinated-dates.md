# BUG-001: Agent Hallucinated Dates When User Omits Them

## Symptom

User: `Schedule a 5-day itinerary to MiaMi, FL`
Agent: calls `start_trip(destination="Miami, FL", start_date="2026-04-10", end_date="2026-04-14")`

Dates April 10-14 were **fabricated by the agent** — the user never specified them.

## Classification

**Prompt gap → agent hallucination.** Not a server default. Not a code bug.

## Root Cause

Three layers failed to guard against this:

### 1. `plan_trip` prompt has no missing-date instruction (`mcp_server/prompts.py:32`)

```
### 1. Initialize
Extract destination, start_date, end_date from the user request.
Call `start_trip(destination, start_date, end_date, ...)`.
```

The prompt says "extract" but never says what to do when dates **cannot** be extracted. The agent fills in the required parameters with plausible-sounding dates rather than asking the user.

### 2. `start_trip` tool has no validation (`mcp_server/server.py:372`)

`start_date: str` and `end_date: str` are required string parameters. The server:
- Accepts any string (no format validation)
- Has no "ask the user" fallback
- Has no default date logic

### 3. `create_trip_prefs` passes through blindly (`profile/trip_prefs.py:11`)

```python
def create_trip_prefs(destination, start_date, end_date, overrides=None):
    return {
        "trip_id": f"{start_date[:7]}-{destination.lower().replace(' ', '-')}",
        ...
    }
```

No validation on date format or reasonableness.

## Why This Matters

- **Silent data corruption**: The trip is initialized with wrong dates. All downstream artifacts (itinerary, hotel check-in/check-out, restaurant scheduling) are built on fabricated dates.
- **User trust**: The agent confidently states "April 10-14, 2026" as if the user chose it.
- **Compounding error**: Once dates are set via `start_trip`, there is no `update_trip_dates` tool to correct them without canceling and restarting.

## How to Fix

### Fix A: Prompt guard (minimal, recommended first)

In `mcp_server/prompts.py`, add a missing-info check before Step 1:

```
### 1. Initialize
Extract destination, start_date, end_date from the user request.
- If start_date or end_date cannot be determined from the request:
  ASK the user for the missing dates before calling start_trip.
  Do NOT invent or assume dates.
- If the user gives duration (e.g. "5 days") but no start date:
  ASK "When would you like to start?"
```

### Fix B: Server-side date validation (defense in depth)

In `start_trip` (`server.py:372`), add basic validation:

```python
from datetime import date as _date

# Validate date format
try:
    start = _date.fromisoformat(start_date)
    end = _date.fromisoformat(end_date)
except ValueError:
    return {"status": "error", "reason": f"Invalid date format. Use YYYY-MM-DD."}

# Validate range
if end <= start:
    return {"status": "error", "reason": "end_date must be after start_date"}
if (end - start).days > 30:
    return {"status": "error", "reason": "Trip exceeds 30-day maximum"}
```

### Fix C: Make dates optional + add profile_collection fallback (fullest fix)

Change `start_trip` signature to accept optional dates:

```python
def start_trip(
    destination: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    duration_days: Optional[int] = None,
    ...
)
```

If dates are missing, insert a "date_collection" micro-stage before `profile_collection` — or fold date collection into the profile_collection interactive stage.

## Recommended Priority

**Fix A immediately** (1-line prompt change, eliminates the hallucination).
**Fix B soon** (defense in depth, catches malformed dates too).
**Fix C later** (nice UX but larger refactor).

## Files Involved

| File | Line | Issue |
|------|------|-------|
| `mcp_server/prompts.py` | 32 | No missing-date instruction |
| `mcp_server/server.py` | 372 | No date validation in `start_trip` |
| `profile/trip_prefs.py` | 11 | No format/reasonableness check |
