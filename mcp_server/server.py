from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server import artifact_store, config, validation
from mcp_server.prompts import PLAN_TRIP_PROMPT
from mcp_server.workflow import WorkflowState, cleanup_stale_sessions, list_all_sessions

log = logging.getLogger(__name__)

mcp = FastMCP(
    "travel-planner",
    instructions=(
        "MCP server for autonomous travel planning. "
        "Use the plan_trip prompt to start. "
        "Search stages (POI, restaurants, hotels) run server-side via WebSearch — "
        "the agent should call search tools, NOT use WebSearch directly."
    ),
)


# ---------------------------------------------------------------------------
# Search error type
# ---------------------------------------------------------------------------

class SearchError(Exception):
    pass


# ---------------------------------------------------------------------------
# Bridge helpers (JSON artifact → SQLite sync)
# ---------------------------------------------------------------------------

def _get_db_connection():
    """Get SQLite connection for bridge operations. Returns None if DB absent."""
    import sqlite3 as _sqlite3
    db_path = config.DB_PATH
    if not db_path.exists():
        log.warning("SQLite DB not found at %s, skipping bridge", db_path)
        return None
    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _bridge_call(fn, *args, **kwargs) -> Optional[dict]:
    """Call a bridge function with DB connection management.

    Returns bridge result dict or None if DB unavailable.
    Bridge failures are logged and recorded in bridge_sync, not swallowed.
    """
    conn = _get_db_connection()
    if not conn:
        return None
    try:
        result = fn(conn, *args, **kwargs)
        if result and result.get("status") == "failed":
            log.error("Bridge sync failed: %s", result.get("error"))
        return result
    except Exception as e:
        log.error("Bridge exception: %s", e, exc_info=True)
        return {"status": "failed", "error": str(e)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_action(state: WorkflowState) -> dict[str, Any]:
    stage = state.current_stage

    if state.status == "complete":
        return {"status": "complete", "summary": _session_summary(state)}

    if state.status in ("blocked", "cancelled"):
        return {
            "status": "blocked",
            "stage": stage,
            "reason": state.block_reason or f"Trip is {state.status}",
            "max_retries_exceeded": state.is_blocked(stage),
        }

    # Profile collection — interactive stage
    if stage == "profile_collection":
        return _build_profile_collection_action(state)

    # For search stages, tell the agent to call the corresponding search tool
    search_tool_names = {"poi_search": "search_pois", "restaurants": "search_restaurants", "hotels": "search_hotels"}
    if stage in config.SEARCH_STAGES:
        tool_name = search_tool_names[stage]
        if stage == "poi_search":
            hint = (
                "Call discover_poi_names(session_id) to preview POI names, "
                f"then call {tool_name}(session_id) to collect metadata in parallel. "
                "Optional: max_results (default: trip_days × max_pois_per_day from profile). "
                "POI search runs in parallel (~2-3 min). "
                "Monitor via travel://session/{session_id}/poi-search-progress."
            )
        else:
            hint = f"Call {tool_name}(session_id). Optional: time_limit_seconds (default 120)."
        return {
            "status": "action_required",
            "stage": stage,
            "instructions": hint,
            "input_artifacts": {},
            "output_schema": {},
            "prior_errors": state.prior_errors.get(stage, []),
        }

    instructions = ""
    context: dict[str, str] = {}
    try:
        from mcp_server.prompt_loader import load_prompt

        if stage == "scheduling":
            context["guardrails"] = config.GUARDRAILS_PATH.read_text(encoding="utf-8")

        prompt_name = config.STAGE_PROMPTS.get(stage)
        if prompt_name:
            instructions = load_prompt(prompt_name, context)
    except Exception as e:
        log.warning("Prompt loading failed for stage %s: %s", stage, e, exc_info=True)
        instructions = f"Execute stage: {stage}."

    input_artifacts: dict[str, Any] = {}
    for name in config.STAGE_INPUT_ARTIFACTS.get(stage, []):
        art = artifact_store.load_artifact(state.session_id, name)
        if art:
            input_artifacts[name] = art

    output_schema = config.load_contract(stage)

    return {
        "status": "action_required",
        "stage": stage,
        "instructions": instructions,
        "input_artifacts": input_artifacts,
        "output_schema": output_schema,
        "prior_errors": state.prior_errors.get(stage, []),
    }


def _session_summary(state: WorkflowState) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "trip_id": state.trip_id,
        "status": state.status,
        "completed_stages": state.completed_stages,
        "notion_urls": state.notion_urls,
        "artifacts": artifact_store.list_artifacts(state.session_id),
    }


def _load_trip_prefs(trip_id: str) -> dict:
    from profile.trip_prefs import load_trip_prefs

    prefs_path = config.trip_dir(trip_id) / "trip-prefs.yaml"
    try:
        return load_trip_prefs(prefs_path)
    except (FileNotFoundError, ValueError):
        return {}


def _load_merged_profile_from_prefs(trip_id: str, prefs: dict) -> dict:
    from profile.schema import load_profile_safe
    from profile.trip_prefs import merge_with_profile

    profile = load_profile_safe(config.PROFILE_PATH)
    if prefs:
        profile = merge_with_profile(profile, prefs)
    return profile


def _load_merged_profile(trip_id: str) -> dict:
    prefs = _load_trip_prefs(trip_id)
    return _load_merged_profile_from_prefs(trip_id, prefs)


def _determine_regression_target(violations: list[dict]) -> str:
    rules = {v.get("rule", "") for v in violations}
    if rules & {"restaurant_day_ref", "restaurant_near_poi"}:
        return "restaurants"
    if rules & {"hotel_check_in", "hotel_check_out"}:
        return "hotels"
    return "scheduling"


# ---------------------------------------------------------------------------
# Profile collection helpers
# ---------------------------------------------------------------------------

_UNSET = object()


def _build_profile_collection_action(state: WorkflowState) -> dict[str, Any]:
    """Build action for the profile_collection stage."""
    import yaml
    from profile.schema import check_profile_completeness, load_profile_safe

    profile = load_profile_safe(config.PROFILE_PATH)
    completeness = check_profile_completeness(profile)

    # Load Layer 2 questions, filter out already-answered ones
    all_questions = config.load_profile_questions()
    unanswered = _filter_answered_questions(all_questions, profile)

    # Load Layer 3 destination questions
    prefs = _load_trip_prefs(state.trip_id)
    destination = prefs.get("destination", state.trip_id)
    dest_questions = config.load_destination_questions(destination)
    dest_unanswered = _filter_answered_questions(dest_questions, profile)

    # Build prompt from template
    profile_yaml = yaml.dump(profile, allow_unicode=True, default_flow_style=False) if profile else "No profile yet."
    instructions = ""
    try:
        from mcp_server.prompt_loader import load_prompt
        instructions = load_prompt("stage-1-profile-collection", {
            "destination": destination,
            "profile_state": profile_yaml,
            "missing_fields": json.dumps(completeness, indent=2),
            "structured_questions": json.dumps(unanswered, indent=2, ensure_ascii=False),
            "destination_questions": json.dumps(dest_unanswered, indent=2, ensure_ascii=False),
        })
    except Exception as e:
        log.warning("Profile collection prompt loading failed: %s", e)
        instructions = "Collect the traveler's profile information through conversation."

    return {
        "status": "user_interaction_required",
        "stage": "profile_collection",
        "instructions": instructions,
        "current_profile": profile,
        "completeness": completeness,
        "questions": unanswered,
        "destination_questions": dest_unanswered,
    }


def _filter_answered_questions(questions: list[dict], profile: dict) -> list[dict]:
    """Filter out questions whose target field already exists in the profile.

    Uses a sentinel to distinguish 'field absent' from 'field has falsey value'.
    Empty lists, empty strings, 0, False are all valid answers.
    """
    unanswered = []
    for q in questions:
        field_path = q.get("field", "")
        parts = field_path.split(".")
        val: Any = profile
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part, _UNSET)
            else:
                val = _UNSET
                break
        if val is _UNSET:
            unanswered.append(q)
    return unanswered


# ---------------------------------------------------------------------------
# Server-side search: Codex discovery + claude -p transformation
# ---------------------------------------------------------------------------

async def _run_codex_search(
    prompt: str, ctx: Optional[Context] = None, timeout: Optional[int] = None,
) -> str:
    """Run codex exec for web search discovery. Returns raw stdout text."""
    effective_timeout = timeout or config.CODEX_SEARCH_TIMEOUT_SECONDS
    proc = await asyncio.create_subprocess_exec(
        "codex", "exec", "--skip-git-repo-check", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _heartbeat() -> None:
        elapsed = 0
        while True:
            await asyncio.sleep(30)
            elapsed += 30
            try:
                if ctx:
                    await ctx.info(f"Search in progress... ({elapsed}s elapsed)")
                    await ctx.report_progress(
                        progress=elapsed,
                        total=effective_timeout,
                        message=f"Codex discovery ({elapsed}s elapsed)",
                    )
                log.info("Heartbeat: codex search %ds elapsed", elapsed)
            except Exception:
                pass

    hb = asyncio.create_task(_heartbeat())
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SearchError(
            f"Codex search timed out after {effective_timeout}s"
        )
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")[:500]
        raise SearchError(f"codex exec exited with code {proc.returncode}: {stderr_text}")

    stdout_text = stdout_bytes.decode(errors="replace").strip()
    if not stdout_text:
        raise SearchError("Codex search returned empty output")

    return stdout_text


async def _run_claude_transform(
    transform_prompt: str, schema_path: Path,
) -> dict:
    """Run claude -p --bare for structured transformation only (no web search)."""
    claude_cli = config.find_claude_cli()
    schema = schema_path.read_text(encoding="utf-8")

    proc = await asyncio.create_subprocess_exec(
        claude_cli, "-p", transform_prompt,
        "--bare",
        "--output-format", "json",
        "--json-schema", schema,
        "--max-turns", "3",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=config.TRANSFORM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SearchError(
            f"Transform timed out after {config.TRANSFORM_TIMEOUT_SECONDS}s"
        )

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")[:500]
        raise SearchError(f"claude -p exited with code {proc.returncode}: {stderr_text}")

    stdout_text = stdout_bytes.decode(errors="replace")
    try:
        output = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise SearchError(f"Failed to parse transform output as JSON: {e}")

    return output.get("structured_output", output)


_SECONDS_PER_POI = 25


def _compute_poi_target(state: WorkflowState) -> int:
    """Derive POI count from trip duration × max pois_per_day from profile."""
    from datetime import date

    prefs = _load_trip_prefs(state.trip_id)
    try:
        start = date.fromisoformat(prefs.get("dates", {}).get("start", ""))
        end = date.fromisoformat(prefs.get("dates", {}).get("end", ""))
        trip_days = (end - start).days + 1
    except (ValueError, TypeError):
        trip_days = 3

    profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
    pace = (profile.get("travel_pace") or {}).get("pois_per_day", [3, 5])
    max_per_day = pace[-1] if isinstance(pace, list) and pace else 5

    return trip_days * max_per_day


def _estimate_search_timeout(max_results: int) -> int:
    """~25s per POI, clamped to [30, 900]."""
    return max(10, min(max_results * _SECONDS_PER_POI, 900))


def _build_poi_search_prompt(state: WorkflowState, max_results: int = 15) -> str:
    import yaml

    prefs = _load_trip_prefs(state.trip_id)
    profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
    destination = prefs.get("destination", state.trip_id)
    profile_yaml = yaml.dump(profile, allow_unicode=True, default_flow_style=False)

    return (
        f"You are a travel research agent. Search the web for Points of Interest "
        f"for a trip to {destination}.\n\n"
        f"## Traveler Profile\n{profile_yaml}\n\n"
        f"## What to Find\n"
        f"For each POI, you MUST provide all of the following:\n"
        f"- Name in English AND Chinese (name_en, name_cn)\n"
        f"- Style category (nature, tech, culture, food, landmark, or coffee)\n"
        f"- Full street address and city\n"
        f"- Latitude and longitude coordinates\n"
        f"- Current operating hours\n"
        f"- Typical visit duration in minutes\n"
        f"- Brief description\n"
        f"- Source URL where you found the information\n\n"
        f"## Requirements\n"
        f"- Include all wishlist items from the profile with their stated priority.\n"
        f"- Add agent-suggested POIs that match the traveler's interests.\n"
        f"- Return at most {max_results} candidate POIs.\n"
        f"- Prioritize must_visit wishlist items, then nice_to_have, then agent suggestions.\n"
    )


def _build_poi_transform_prompt(raw_text: str) -> str:
    return (
        f"Structure the following raw POI research findings into the required JSON format.\n\n"
        f"## Raw Findings\n{raw_text}\n\n"
        f"## Rules\n"
        f"- Map each finding to a candidate object in the schema.\n"
        f"- Do NOT invent values for fields absent from the source text.\n"
        f"- Omit optional fields rather than guessing.\n"
        f"- Generate candidate_id as sha256(name_en|address)[:12].\n"
    )


def _build_name_discovery_prompt(
    destination: str, profile_yaml: str, remaining_slots: int,
) -> str:
    return (
        f"You are a travel research assistant. Based on the traveler profile below, "
        f"suggest {remaining_slots} Points of Interest for a trip to {destination}.\n\n"
        f"## Traveler Profile\n{profile_yaml}\n\n"
        f"## Rules\n"
        f"- Suggest POIs that match the traveler's stated interests.\n"
        f"- Each suggestion needs: name_en (English name) and priority (always 'agent_suggested').\n"
        f"- Optionally include name_cn (Chinese name) and style "
        f"(nature, tech, culture, food, landmark, or coffee).\n"
        f"- Do NOT repeat any names the traveler already listed in their wishlist.\n"
        f"- Prioritize iconic or highly-rated places the traveler is likely to enjoy.\n"
    )


def _build_single_poi_search_prompt(
    poi_name: str, destination: str, profile_yaml: str,
) -> str:
    return (
        f"You are a travel research agent. Search the web for detailed information "
        f"about \"{poi_name}\" in {destination}.\n\n"
        f"## What to Find\n"
        f"- Full name in English AND Chinese\n"
        f"- Style category (nature, tech, culture, food, landmark, or coffee)\n"
        f"- Full street address and city\n"
        f"- Latitude and longitude coordinates\n"
        f"- Current operating hours\n"
        f"- Typical visit duration in minutes\n"
        f"- Brief description (2-3 sentences)\n"
        f"- Source URL where you found the information\n\n"
        f"## Traveler Context\n{profile_yaml}\n\n"
        f"Return all information you can find. Be factual — do not invent details.\n"
    )


async def _search_single_poi(
    poi_name: str,
    destination: str,
    profile_yaml: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        prompt = _build_single_poi_search_prompt(poi_name, destination, profile_yaml)
        try:
            raw = await _run_codex_search(
                prompt, ctx=None, timeout=config.CODEX_PER_POI_TIMEOUT_SECONDS,
            )
            return {"name_en": poi_name, "status": "complete", "raw_text": raw}
        except Exception as e:
            log.warning("POI search failed for %s: %s", poi_name, e)
            return {"name_en": poi_name, "status": "failed", "error": str(e)}


async def _search_pois_parallel(
    state: WorkflowState,
    poi_list: list[dict[str, Any]],
    ctx: Optional[Context] = None,
) -> tuple[str, list[dict[str, Any]]]:
    import yaml

    prefs = _load_trip_prefs(state.trip_id)
    profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
    destination = prefs.get("destination", state.trip_id)
    profile_yaml = yaml.dump(profile, allow_unicode=True, default_flow_style=False)

    semaphore = asyncio.Semaphore(config.CODEX_PARALLEL_LIMIT)
    tasks = [
        asyncio.ensure_future(
            _search_single_poi(poi["name_en"], destination, profile_yaml, semaphore)
        )
        for poi in poi_list
    ]

    completed = 0
    total = len(tasks)
    results: list[dict[str, Any]] = []
    for coro in asyncio.as_completed(tasks):
        result = await coro
        completed += 1
        results.append(result)
        _update_poi_progress(state.session_id, "searching", poi_list, results)
        if ctx:
            await ctx.report_progress(
                progress=completed, total=total,
                message=f"Searched {completed}/{total} POIs ({result['name_en']})",
            )

    successes = [r for r in results if r["status"] == "complete"]
    failures = [r for r in results if r["status"] == "failed"]

    if len(successes) < len(poi_list) * 0.5:
        raise SearchError(
            f"Majority of POI searches failed ({len(failures)}/{total}). "
            f"Succeeded: {[s['name_en'] for s in successes]}"
        )

    merged_raw = "\n\n---\n\n".join(r["raw_text"] for r in successes)
    return merged_raw, failures


def _update_poi_progress(
    session_id: str,
    phase: str,
    poi_list: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    from datetime import datetime, timezone

    result_map = {r["name_en"]: r for r in results}
    per_poi = {}
    for poi in poi_list:
        name = poi["name_en"]
        if name in result_map:
            r = result_map[name]
            per_poi[name] = {"status": r["status"], "error": r.get("error")}
        else:
            per_poi[name] = {"status": "pending"}

    progress = {
        "phase": phase,
        "poi_names": [p["name_en"] for p in poi_list],
        "results": per_poi,
        "completed": sum(1 for r in results if r["status"] == "complete"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total": len(poi_list),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    config.atomic_write_json(
        config.session_dir(session_id) / "poi-search-progress.json", progress,
    )


def _build_restaurant_search_prompt(state: WorkflowState) -> str:
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    itinerary_json = json.dumps(itinerary, indent=2, ensure_ascii=False)

    return (
        f"You are a restaurant research agent. Search the web for restaurant "
        f"recommendations based on this travel itinerary.\n\n"
        f"## Itinerary\n{itinerary_json}\n\n"
        f"## What to Find\n"
        f"For each restaurant, you MUST provide all of the following:\n"
        f"- Name in English AND Chinese (name_en, name_cn)\n"
        f"- Cuisine type\n"
        f"- Full street address\n"
        f"- Price tier (budget, moderate, or premium)\n"
        f"- Whether reservation is required\n"
        f"- Booking URL if available\n"
        f"- Which day number and meal (lunch or dinner) this restaurant serves\n"
        f"- Which nearby POI from the itinerary it is close to (near_poi)\n\n"
        f"## Requirements\n"
        f"- Recommend one lunch and one dinner restaurant per day.\n"
        f"- Restaurants must be geographically close to that day's scheduled POIs.\n"
        f"- Include bilingual names (English + Chinese).\n"
    )


def _build_restaurant_transform_prompt(raw_text: str, itinerary: dict) -> str:
    itin_json = json.dumps(itinerary, indent=2, ensure_ascii=False)
    return (
        f"Structure the following raw restaurant research findings into the required JSON format.\n\n"
        f"## Raw Findings\n{raw_text}\n\n"
        f"## Itinerary (for cross-referencing day numbers and regions)\n{itin_json}\n\n"
        f"## Rules\n"
        f"- Each recommendation must include day_num and near_poi from the itinerary.\n"
        f"- Do NOT invent values for fields absent from the source text.\n"
        f"- Omit optional fields rather than guessing.\n"
    )


def _build_hotel_search_prompt(state: WorkflowState) -> str:
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    itinerary_json = json.dumps(itinerary, indent=2, ensure_ascii=False)

    return (
        f"You are a hotel research agent. Search the web for hotel "
        f"recommendations based on this travel itinerary.\n\n"
        f"## Itinerary\n{itinerary_json}\n\n"
        f"## What to Find\n"
        f"For each hotel, you MUST provide all of the following:\n"
        f"- Name in English AND Chinese where possible (name_en, name_cn)\n"
        f"- Full street address\n"
        f"- Price tier (budget, moderate, or premium)\n"
        f"- Booking URL if available\n"
        f"- Which region cluster from the itinerary it covers\n"
        f"- Which night range (check-in and check-out dates)\n\n"
        f"## Requirements\n"
        f"- Group nights by region cluster from the itinerary.\n"
        f"- Include bilingual names where possible.\n"
    )


def _build_hotel_transform_prompt(raw_text: str, itinerary: dict) -> str:
    itin_json = json.dumps(itinerary, indent=2, ensure_ascii=False)
    return (
        f"Structure the following raw hotel research findings into the required JSON format.\n\n"
        f"## Raw Findings\n{raw_text}\n\n"
        f"## Itinerary (for cross-referencing region clusters and nights)\n{itin_json}\n\n"
        f"## Rules\n"
        f"- Do NOT invent values for fields absent from the source text.\n"
        f"- Omit optional fields rather than guessing.\n"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(description="Initialize a new trip and start the planning workflow. Returns session_id and workspace_id for all subsequent calls. Pass optional workspace_tag for human-readable labeling.")
def start_trip(
    destination: str,
    start_date: str,
    end_date: str,
    overrides: Optional[dict] = None,
    workspace_tag: Optional[str] = None,
) -> dict[str, Any]:
    from mcp_server.validation import validate_date_params
    from profile.schema import check_profile_completeness, load_profile_safe
    from profile.trip_prefs import create_trip_prefs, save_trip_prefs

    date_violations = validate_date_params(start_date, end_date)
    if date_violations:
        return {
            "status": "error",
            "error": "invalid_dates",
            "violations": date_violations,
            "hint": "Ask the user for valid travel dates in YYYY-MM-DD format.",
        }

    cleanup_stale_sessions()

    prefs = create_trip_prefs(destination, start_date, end_date, overrides)
    trip_id = prefs["trip_id"]

    # Save trip prefs to legacy location (for profile merge)
    td = config.trip_dir(trip_id)
    td.mkdir(parents=True, exist_ok=True)
    save_trip_prefs(td / "trip-prefs.yaml", prefs)

    workspace_id = uuid.uuid4().hex[:12]
    state = WorkflowState(trip_id, workspace_id=workspace_id, workspace_tag=workspace_tag)

    # Conditional profile_collection insertion
    profile = load_profile_safe(config.PROFILE_PATH)
    completeness = check_profile_completeness(profile)
    if not completeness["complete"]:
        state.stages = ["profile_collection"] + list(config.STAGES)
        state.current_stage = "profile_collection"

    state.save()

    # Also save trip prefs in session dir for self-contained access
    save_trip_prefs(config.session_dir(state.session_id) / "trip-prefs.yaml", prefs)

    # Build profile summary from merged profile (safe — won't crash)
    try:
        merged = _load_merged_profile(trip_id)
        profile_summary = {
            k: merged.get(k)
            for k in ("identity", "travel_interests", "travel_style", "travel_pace")
            if k in merged
        }
    except Exception:
        log.warning("Failed to load profile for trip %s", trip_id, exc_info=True)
        profile_summary = {}

    # Bridge: ensure trip + session exist in SQLite
    from tripdb.bridge import ensure_trip as _ensure_trip, register_session as _register
    _bridge_call(_ensure_trip, trip_id, destination, start_date, end_date)
    _bridge_call(_register, state.session_id, trip_id, workspace_id, workspace_tag)

    return {
        "session_id": state.session_id,
        "trip_id": trip_id,
        "workspace_id": workspace_id,
        "workspace_tag": workspace_tag,
        "profile_complete": completeness["complete"],
        "profile_summary": profile_summary,
        "first_action": _build_action(state),
    }


@mcp.tool(description="Get the next action the agent should perform.")
def get_next_action(session_id: str) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    return _build_action(state)


@mcp.tool(description="Submit a stage artifact for validation and storage. Use for scheduling stage only — search stages use search tools.")
def submit_artifact(
    session_id: str,
    stage: str,
    data: dict,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)

    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    violations = validation.validate_stage(stage, data, session_id)

    if violations:
        attempt = state.record_attempt(stage, violations)
        if state.is_blocked(stage):
            state.block(f"Max attempts exceeded for {stage}")
            return {
                "status": "blocked",
                "stage": stage,
                "violations": violations,
                "attempt": attempt,
                "max_attempts": config.MAX_ATTEMPTS_PER_STAGE,
                "reason": f"Failed {attempt} times at stage {stage}",
            }
        state.save()
        return {
            "status": "rejected",
            "violations": violations,
            "attempt": attempt,
            "max_attempts": config.MAX_ATTEMPTS_PER_STAGE,
        }

    artifact_store.save_artifact(session_id, stage, data)
    state.complete_stage(stage)

    # Bridge: import scheduling artifact to SQLite
    bridge_status = None
    if stage == "scheduling":
        from tripdb.bridge import import_itinerary as _import_itin
        cmap = artifact_store.load_artifact(session_id, "candidate-map") or {}
        br = _bridge_call(_import_itin, session_id, state.trip_id, data, cmap)
        bridge_status = br.get("status") if br else None

    return {
        "status": "accepted",
        "bridge_status": bridge_status,
        "next_action": _build_action(state),
    }


# ---------------------------------------------------------------------------
# Server-side search tools (4)
# ---------------------------------------------------------------------------

@mcp.tool(description=(
    "Quickly identify POI names to search for a trip. "
    "Extracts wishlist items from profile and uses claude -p to suggest additional names. "
    "Fast (~10s, no web search). Call before search_pois to preview names."
))
async def discover_poi_names(
    session_id: str,
    ctx: Context,
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    import yaml

    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    if max_results is None:
        max_results = _compute_poi_target(state)
    max_results = max(5, min(max_results, 50))

    prefs = _load_trip_prefs(state.trip_id)
    profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
    destination = prefs.get("destination", state.trip_id)

    wishlist = profile.get("wishlist") or []
    poi_names: list[dict[str, Any]] = []
    for item in wishlist:
        poi_names.append({
            "name_en": item.get("name_en", ""),
            "name_cn": item.get("name_cn", ""),
            "priority": item.get("priority", "nice_to_have"),
        })

    remaining = max_results - len(poi_names)
    if remaining > 0:
        profile_yaml = yaml.dump(profile, allow_unicode=True, default_flow_style=False)
        prompt = _build_name_discovery_prompt(destination, profile_yaml, remaining)
        schema_path = config.CONTRACTS_DIR / "poi-names.json"
        try:
            suggestions = await _run_claude_transform(prompt, schema_path)
            for s in suggestions.get("poi_names", []):
                poi_names.append({
                    "name_en": s.get("name_en", ""),
                    "name_cn": s.get("name_cn", ""),
                    "priority": s.get("priority", "agent_suggested"),
                })
        except SearchError as e:
            await ctx.info(f"Suggestion generation failed, proceeding with wishlist only: {e}")

    poi_names = poi_names[:max_results]

    result = {"destination": destination, "poi_names": poi_names}
    config.atomic_write_json(
        config.session_dir(session_id) / "poi-names.json", result,
    )
    _update_poi_progress(session_id, "discovered", poi_names, [])

    return {
        "status": "complete",
        "count": len(poi_names),
        "names": [p["name_en"] for p in poi_names],
        "next": "Call search_pois(session_id) to collect metadata in parallel.",
    }


@mcp.tool(description=(
    "Discover POI candidates for a trip via parallel web search. "
    "Returns structured candidates with bilingual names, coordinates, hours, and descriptions. "
    "Runs server-side (agent must NOT call WebSearch). "
    "Call discover_poi_names first to preview names, or this tool auto-discovers if needed. "
    "max_results defaults to trip_days × max_pois_per_day (from profile); "
    "override to search fewer (faster) or more (broader pool)."
))
async def search_pois(
    session_id: str,
    ctx: Context,
    max_results: Optional[int] = None,
    time_limit_seconds: Optional[int] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    if max_results is None:
        max_results = _compute_poi_target(state)
    max_results = max(5, min(max_results, 50))

    total_phases = 5
    await ctx.report_progress(progress=0, total=total_phases, message="Loading POI names")

    names_path = config.session_dir(session_id) / "poi-names.json"
    poi_list: list[dict[str, Any]] = []
    if names_path.exists():
        saved = json.loads(names_path.read_text(encoding="utf-8"))
        poi_list = saved.get("poi_names", [])
    if not poi_list:
        await ctx.info("No pre-discovered names found, running inline discovery...")
        result = await discover_poi_names(session_id, ctx, max_results)
        if result.get("status") != "complete":
            return result
        poi_list = json.loads(
            names_path.read_text(encoding="utf-8")
        ).get("poi_names", [])

    poi_list = poi_list[:max_results]
    await ctx.info(
        f"Searching {len(poi_list)} POIs in parallel "
        f"(max {config.CODEX_PARALLEL_LIMIT} concurrent)..."
    )
    await ctx.report_progress(
        progress=1, total=total_phases,
        message=f"Parallel search: {len(poi_list)} POIs",
    )

    try:
        merged_raw, failures = await _search_pois_parallel(state, poi_list, ctx)
    except SearchError as e:
        await ctx.error(f"POI parallel search failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=2, total=total_phases, message="Structuring results")
    transform_prompt = _build_poi_transform_prompt(merged_raw)
    schema_path = config.CONTRACTS_DIR / "poi-candidates.json"
    try:
        result = await _run_claude_transform(transform_prompt, schema_path)
    except SearchError as e:
        await ctx.error(f"POI transform failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=3, total=total_phases, message="Validating")
    violations = validation.validate_schema("poi_search", result)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "poi_search", result)
    state.complete_stage("poi_search")

    await ctx.report_progress(progress=4, total=total_phases, message="Importing to database")
    from tripdb.bridge import import_pois as _import_pois
    bridge_result = _bridge_call(_import_pois, state.session_id, state.trip_id, result)
    if bridge_result:
        artifact_store.save_artifact(session_id, "candidate-map", bridge_result.get("candidate_map", {}))

    failed_names = {f["name_en"] for f in failures}
    final_results = [
        {"name_en": p["name_en"], "status": "failed" if p["name_en"] in failed_names else "complete"}
        for p in poi_list
    ]
    _update_poi_progress(session_id, "complete", poi_list, final_results)
    await ctx.report_progress(progress=5, total=total_phases, message="Search complete")
    candidates = result.get("candidates", [])
    return {
        "status": "complete",
        "candidates_count": len(candidates),
        "sample": [c.get("name_en", "") for c in candidates[:5]],
        "failed_pois": [f["name_en"] for f in failures],
        "bridge_status": bridge_result.get("status") if bridge_result else None,
        "next_action": _build_action(state),
    }


@mcp.tool(description=(
    "Discover restaurant recommendations near scheduled POIs via web search. "
    "Returns structured recommendations with bilingual names, cuisine, price tier, and day assignment. "
    "Runs server-side (agent must NOT call WebSearch). "
    "time_limit_seconds defaults to 120; override to constrain."
))
async def search_restaurants(
    session_id: str,
    ctx: Context,
    time_limit_seconds: int = 120,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    time_limit_seconds = max(10, min(time_limit_seconds, 900))

    await ctx.info(f"Starting restaurant search ({time_limit_seconds}s limit)...")
    await ctx.report_progress(progress=0, total=4, message="Starting codex discovery")

    search_prompt = _build_restaurant_search_prompt(state)
    try:
        raw_text = await _run_codex_search(search_prompt, ctx=ctx, timeout=time_limit_seconds)
    except SearchError as e:
        await ctx.error(f"Restaurant search failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=1, total=4, message="Structuring results")
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    transform_prompt = _build_restaurant_transform_prompt(raw_text, itinerary)
    schema_path = config.CONTRACTS_DIR / "restaurants.json"
    try:
        result = await _run_claude_transform(transform_prompt, schema_path)
    except SearchError as e:
        await ctx.error(f"Restaurant transform failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=2, total=4, message="Validating")
    violations = validation.validate_stage("restaurants", result, session_id)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "restaurants", result)
    state.complete_stage("restaurants")

    await ctx.report_progress(progress=3, total=4, message="Importing to database")
    from tripdb.bridge import import_restaurants as _import_rest
    itin = artifact_store.load_artifact(session_id, "itinerary") or {}
    trip_start = itin.get("start_date", "")
    if not trip_start:
        prefs = _load_trip_prefs(state.trip_id)
        trip_start = prefs.get("dates", {}).get("start", "")
    br = _bridge_call(_import_rest, state.session_id, state.trip_id, result,
                      trip_start)

    await ctx.report_progress(progress=4, total=4, message="Search complete")
    recs = result.get("recommendations", [])
    return {
        "status": "complete",
        "recommendations_count": len(recs),
        "bridge_status": br.get("status") if br else None,
        "next_action": _build_action(state),
    }


@mcp.tool(description=(
    "Discover hotel recommendations grouped by itinerary region clusters via web search. "
    "Returns structured recommendations with bilingual names, price tier, and night ranges. "
    "Runs server-side (agent must NOT call WebSearch). "
    "time_limit_seconds defaults to 120; override to constrain."
))
async def search_hotels(
    session_id: str,
    ctx: Context,
    time_limit_seconds: int = 120,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    time_limit_seconds = max(10, min(time_limit_seconds, 900))

    await ctx.info(f"Starting hotel search ({time_limit_seconds}s limit)...")
    await ctx.report_progress(progress=0, total=4, message="Starting codex discovery")

    search_prompt = _build_hotel_search_prompt(state)
    try:
        raw_text = await _run_codex_search(search_prompt, ctx=ctx, timeout=time_limit_seconds)
    except SearchError as e:
        await ctx.error(f"Hotel search failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=1, total=4, message="Structuring results")
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    transform_prompt = _build_hotel_transform_prompt(raw_text, itinerary)
    schema_path = config.CONTRACTS_DIR / "hotels.json"
    try:
        result = await _run_claude_transform(transform_prompt, schema_path)
    except SearchError as e:
        await ctx.error(f"Hotel transform failed: {e}")
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    await ctx.report_progress(progress=2, total=4, message="Validating")
    violations = validation.validate_stage("hotels", result, session_id)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "hotels", result)
    state.complete_stage("hotels")

    await ctx.report_progress(progress=3, total=4, message="Importing to database")
    from tripdb.bridge import import_hotels as _import_hotels
    br = _bridge_call(_import_hotels, state.session_id, state.trip_id, result)

    await ctx.report_progress(progress=4, total=4, message="Search complete")
    recs = result.get("recommendations", [])
    return {
        "status": "complete",
        "recommendations_count": len(recs),
        "bridge_status": br.get("status") if br else None,
        "next_action": _build_action(state),
    }


# ---------------------------------------------------------------------------
# Existing tools (updated to session_id)
# ---------------------------------------------------------------------------

@mcp.tool(description="Run Stage 5 review (rule engine + optional Codex). Server-side execution.")
def run_review(
    session_id: str,
    skip_codex: bool = False,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)

    review_report = validation.run_full_review(session_id, skip_codex)
    artifact_store.save_artifact(session_id, "review", review_report)

    # Bridge: import review risks to SQLite
    from tripdb.bridge import import_review_risks as _import_risks
    _bridge_call(_import_risks, state.session_id, state.trip_id, review_report)

    hard_violations = [
        item for item in review_report.get("items", [])
        if item.get("source") == "hard_rule" and item.get("verdict") == "reject"
    ]

    if hard_violations:
        target_stage = _determine_regression_target(hard_violations)
        result = state.regress_to(target_stage, hard_violations)
        return {"review_report": review_report, "hard_pass": False, **result}

    state.complete_stage("review")

    return {
        "review_report": review_report,
        "hard_pass": True,
        "next_action": _build_action(state),
    }


@mcp.tool(description="Generate Notion publishing manifest from validated artifacts.")
def build_notion_manifest(session_id: str) -> dict[str, Any]:
    from output.notion_publisher import build_manifest

    itinerary = artifact_store.load_artifact(session_id, "itinerary") or {}
    restaurants = artifact_store.load_artifact(session_id, "restaurants") or {}
    hotels = artifact_store.load_artifact(session_id, "hotels") or {}
    review_report = artifact_store.load_artifact(session_id, "review-report") or {}

    manifest = build_manifest(itinerary, restaurants, hotels, review_report)
    artifact_store.save_artifact(session_id, "notion-manifest", manifest)

    return {"manifest": manifest}


@mcp.tool(description="Record Notion URLs after publishing. Supports partial publish.")
def record_notion_urls(
    session_id: str,
    parent_page_url: str,
    database_ids: dict,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)

    state.record_notion_url("parent_page", parent_page_url)
    for db_name, db_id in database_ids.items():
        state.record_notion_url(db_name, db_id)

    required_dbs = {"itinerary", "restaurants", "hotels", "notices"}
    remaining = required_dbs - state.published_databases

    if remaining:
        state.save()
        return {
            "status": "partial",
            "published": sorted(state.published_databases),
            "remaining": sorted(remaining),
        }

    state.complete_stage("notion")

    return {"status": "accepted", "next_action": _build_action(state)}


@mcp.tool(description="Mark trip workflow as complete after verification.")
def complete_trip(
    session_id: str,
    verification_notes: Optional[str] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    state.complete_stage("verify")

    # Sync terminal status to SQLite
    from tripdb.bridge import update_session_status as _update_status
    _bridge_call(_update_status, session_id, "complete")

    return {
        "status": "complete",
        "summary": _session_summary(state),
        "verification_notes": verification_notes,
    }


@mcp.tool(description="Read-only workflow status check.")
def get_workflow_status(session_id: str) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    return {
        **state.to_dict(),
        "artifacts_available": artifact_store.list_artifacts(session_id),
    }


@mcp.tool(description=(
    "Update traveler profile (additive deep merge). Safe for incremental building.\n"
    "\n"
    "Key field formats:\n"
    "- wishlist: list of dicts, each with 'name_en' (required), "
    "'priority' ('must_visit'|'nice_to_have'|'flexible', default 'flexible').\n"
    '  Example: [{"name_en": "South Beach", "priority": "must_visit"}]\n'
    "- travel_pace.pois_per_day: [min, max] list of two ints, e.g. [3, 5]\n"
    "- dietary.budget_tier / accommodation.budget_tier: 'budget'|'moderate'|'premium'\n"
    "- dietary.restrictions: list of strings, e.g. [\"no pork\"]\n"
))
def update_profile(updates: dict) -> dict[str, Any]:
    from profile.schema import (
        deep_merge,
        load_profile_safe,
        save_profile,
        validate_profile_structure,
    )

    profile = load_profile_safe(config.PROFILE_PATH)
    merged = deep_merge(profile, updates)
    # Only validate structure of present sections (not required section presence),
    # so incremental profile building during profile_collection doesn't fail.
    validate_profile_structure(merged)
    save_profile(config.PROFILE_PATH, merged)

    return {
        "status": "updated",
        "profile_summary": {
            k: merged.get(k)
            for k in ("identity", "travel_interests", "travel_style", "travel_pace")
            if k in merged
        },
    }


@mcp.tool(description="Signal that profile collection is complete. Server validates profile completeness before advancing.")
def complete_profile_collection(session_id: str) -> dict[str, Any]:
    from profile.schema import check_profile_completeness, load_profile_safe

    state = WorkflowState.load(session_id)

    if state.current_stage != "profile_collection":
        return {
            "status": "error",
            "reason": f"Current stage is {state.current_stage}, not profile_collection",
        }

    profile = load_profile_safe(config.PROFILE_PATH)
    completeness = check_profile_completeness(profile)

    if not completeness["complete"]:
        return {
            "status": "incomplete",
            "completeness": completeness,
            "hint": "Continue asking about: " + ", ".join(
                completeness["missing_required"] + completeness["structural_issues"]
            ),
        }

    state.complete_stage("profile_collection")

    return {
        "status": "accepted",
        "completeness": completeness,
        "next_action": _build_action(state),
    }


@mcp.tool(description="List all sessions with their workflow status. Optionally filter by workspace_id or workspace_tag.")
def list_trips(
    workspace_id: Optional[str] = None,
    workspace_tag: Optional[str] = None,
) -> dict[str, Any]:
    sessions = list_all_sessions()
    if workspace_id:
        sessions = [s for s in sessions if s.get("workspace_id") == workspace_id]
    if workspace_tag:
        sessions = [s for s in sessions if workspace_tag in (s.get("workspace_tag") or "")]
    return {"sessions": sessions}


@mcp.tool(description="Cancel (abandon) a trip. Cleans up session directory.")
def cancel_trip(
    session_id: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    state.cancel(reason)

    # Sync terminal status to SQLite
    from tripdb.bridge import update_session_status as _update_status
    _bridge_call(_update_status, session_id, "cancelled")

    return {"status": "cancelled", "session_id": session_id, "reason": reason}


@mcp.tool(description="Resume an active session by workspace_id. Use after conversation restart when workspace_id is known.")
def resume_trip(workspace_id: str) -> dict[str, Any]:
    from tripdb.queries import find_active_session_by_workspace

    # 1. Query SQLite for active session with this workspace_id
    conn = _get_db_connection()
    session_row = None
    if conn:
        try:
            session_row = find_active_session_by_workspace(conn, workspace_id)
        finally:
            conn.close()

    # 2. If DB row found, validate against canonical workflow-state.json
    if session_row:
        session_id = session_row["id"]
        try:
            state = WorkflowState.load(session_id)
            # JSON is canonical: only resume if truly active or blocked
            if state.status in ("active", "blocked"):
                return {
                    "status": "resumed",
                    "session_id": state.session_id,
                    "trip_id": state.trip_id,
                    "workspace_id": state.workspace_id,
                    "workspace_tag": state.workspace_tag,
                    "current_stage": state.current_stage,
                    "completed_stages": state.completed_stages,
                    "workflow_status": state.status,
                    "next_action": _build_action(state),
                }
            # Stale DB row: JSON says complete/cancelled but DB said active
            return {"status": "not_found", "workspace_id": workspace_id}
        except FileNotFoundError:
            return {
                "status": "orphaned",
                "reason": f"Session {session_id} found in DB but workflow state file missing",
                "session_info": {
                    "session_id": session_id,
                    "trip_id": session_row.get("trip_id"),
                    "destination": session_row.get("destination"),
                },
            }

    # 3. Fallback: scan sessions/ dirs for matching workspace_id
    if config.SESSIONS_DIR.exists():
        for d in sorted(config.SESSIONS_DIR.iterdir(), reverse=True):
            state_file = d / "workflow-state.json"
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("workspace_id") == workspace_id and data.get("status") in ("active", "blocked"):
                    state = WorkflowState.from_dict(data)
                    return {
                        "status": "resumed",
                        "session_id": state.session_id,
                        "trip_id": state.trip_id,
                        "workspace_id": state.workspace_id,
                        "workspace_tag": state.workspace_tag,
                        "current_stage": state.current_stage,
                        "completed_stages": state.completed_stages,
                        "workflow_status": state.status,
                        "next_action": _build_action(state),
                    }
            except (FileNotFoundError, json.JSONDecodeError, KeyError):
                continue

    # 4. Not found
    return {"status": "not_found", "workspace_id": workspace_id}


@mcp.tool(description="Resume the most recently active session. Use when workspace_id is unknown after conversation restart.")
def resume_latest() -> dict[str, Any]:
    from tripdb.queries import find_all_active_sessions

    # 1. Query SQLite for active sessions
    conn = _get_db_connection()
    db_sessions = []
    if conn:
        try:
            db_sessions = find_all_active_sessions(conn)
        finally:
            conn.close()

    # 2. Validate each DB candidate against canonical JSON
    valid_sessions = []
    for row in db_sessions:
        sid = row.get("id") or row.get("session_id")
        try:
            state = WorkflowState.load(sid)
            if state.status in ("active", "blocked"):
                valid_sessions.append(state)
        except FileNotFoundError:
            continue

    # 3. Fallback: scan disk if DB returned nothing valid
    if not valid_sessions:
        all_sessions = list_all_sessions()
        for s in all_sessions:
            if s.get("status") in ("active", "blocked"):
                try:
                    state = WorkflowState.load(s["session_id"])
                    if state.status in ("active", "blocked"):
                        valid_sessions.append(state)
                except FileNotFoundError:
                    continue

    if not valid_sessions:
        return {"status": "no_active_sessions"}

    if len(valid_sessions) == 1:
        state = valid_sessions[0]
        return {
            "status": "resumed",
            "session_id": state.session_id,
            "trip_id": state.trip_id,
            "workspace_id": state.workspace_id,
            "workspace_tag": state.workspace_tag,
            "current_stage": state.current_stage,
            "completed_stages": state.completed_stages,
            "workflow_status": state.status,
            "next_action": _build_action(state),
        }

    # Multiple active sessions — return list for user to pick
    return {
        "status": "multiple_active",
        "sessions": [
            {
                "session_id": s.session_id,
                "trip_id": s.trip_id,
                "workspace_id": s.workspace_id,
                "workspace_tag": s.workspace_tag,
                "current_stage": s.current_stage,
                "workflow_status": s.status,
                "created_at": s.created_at,
            }
            for s in valid_sessions
        ],
        "action": "Call resume_trip(workspace_id) with your chosen session's workspace_id",
    }


@mcp.tool(description="Human-assisted recovery from blocked state.")
def resolve_blocked(
    session_id: str,
    action: str,
    user_note: Optional[str] = None,
) -> dict[str, Any]:
    if action not in ("retry", "skip", "override"):
        return {"status": "error", "reason": f"Invalid action: {action}. Use retry/skip/override."}

    state = WorkflowState.load(session_id)
    if state.status != "blocked":
        return {"status": "error", "reason": f"Trip is not blocked (status: {state.status})"}

    state.unblock(action)

    return {
        "status": "unblocked",
        "action_taken": action,
        "user_note": user_note,
        "next_action": _build_action(state),
    }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource(
    "travel://config/guardrails",
    description="Guardrails YAML — scheduling constraint definitions",
    mime_type="text/yaml",
)
def get_guardrails() -> str:
    return config.GUARDRAILS_PATH.read_text(encoding="utf-8")


@mcp.resource(
    "travel://config/property-mapping",
    description="Notion property schemas for 4 databases",
    mime_type="application/json",
)
def get_property_mapping() -> str:
    from output.property_mapping import (
        HOTEL_PROPERTIES,
        ITINERARY_PROPERTIES,
        NOTICES_PROPERTIES,
        RESTAURANT_PROPERTIES,
    )
    return json.dumps({
        "itinerary": ITINERARY_PROPERTIES,
        "restaurants": RESTAURANT_PROPERTIES,
        "hotels": HOTEL_PROPERTIES,
        "notices": NOTICES_PROPERTIES,
    }, indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://session/{session_id}/profile",
    description="Merged profile (base + trip overrides)",
    mime_type="text/yaml",
)
def get_session_profile(session_id: str) -> str:
    import yaml

    state = WorkflowState.load(session_id)
    profile = _load_merged_profile(state.trip_id)
    return yaml.dump(profile, allow_unicode=True, default_flow_style=False)


@mcp.resource(
    "travel://session/{session_id}/artifact/{name}",
    description="Stage artifact (poi-candidates, itinerary, restaurants, hotels, review-report)",
    mime_type="application/json",
)
def get_artifact(session_id: str, name: str) -> str:
    data = artifact_store.load_artifact(session_id, name)
    if data is None:
        return json.dumps({"error": f"Artifact '{name}' not found for session {session_id}"})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://session/{session_id}/state",
    description="Workflow state (current stage, attempts, errors)",
    mime_type="application/json",
)
def get_session_state(session_id: str) -> str:
    state = WorkflowState.load(session_id)
    return json.dumps(state.to_dict(), indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://session/{session_id}/notion-manifest",
    description="Generated Notion publishing manifest",
    mime_type="application/json",
)
def get_notion_manifest(session_id: str) -> str:
    data = artifact_store.load_artifact(session_id, "notion-manifest")
    if data is None:
        return json.dumps({"error": "Notion manifest not yet generated."})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://config/contract/{name}",
    description="JSON Schema contract for a stage",
    mime_type="application/json",
)
def get_contract(name: str) -> str:
    contract = config.load_contract(name)
    if not contract:
        return json.dumps({"error": f"Contract '{name}' not found"})
    return json.dumps(contract, indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://session/{session_id}/poi-names",
    description="Discovered POI names for search (output of discover_poi_names)",
    mime_type="application/json",
)
def get_poi_names(session_id: str) -> str:
    path = config.session_dir(session_id) / "poi-names.json"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({"error": "POI names not yet discovered."})


@mcp.resource(
    "travel://session/{session_id}/poi-search-progress",
    description="Real-time progress of parallel POI search (phase, per-POI status)",
    mime_type="application/json",
)
def get_poi_search_progress(session_id: str) -> str:
    path = config.session_dir(session_id) / "poi-search-progress.json"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({"phase": "not_started"})


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt(
    name="plan_trip",
    description="Autonomously plan a complete trip — server-side search, scheduling, validation, and Notion publishing.",
)
def plan_trip(user_request: str) -> str:
    return PLAN_TRIP_PROMPT.format(user_request=user_request)


if __name__ == "__main__":
    mcp.run(transport="stdio")
