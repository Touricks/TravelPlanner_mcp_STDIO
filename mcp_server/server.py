from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

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

    # For search stages, tell the agent to call the corresponding search tool
    search_tool_names = {"poi_search": "search_pois", "restaurants": "search_restaurants", "hotels": "search_hotels"}
    if stage in config.SEARCH_STAGES:
        tool_name = search_tool_names[stage]
        return {
            "status": "action_required",
            "stage": stage,
            "instructions": f"Call {tool_name}(session_id) to execute server-side search.",
            "input_artifacts": {},
            "output_schema": {},
            "prior_errors": state.prior_errors.get(stage, []),
        }

    instructions = ""
    context: dict[str, str] = {}
    try:
        from pipeline.stages.stage_prompts import load_prompt

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
    from profile.schema import load_profile
    from profile.trip_prefs import merge_with_profile

    profile = load_profile(config.PROFILE_PATH)
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
# Server-side search via claude -p subprocess
# ---------------------------------------------------------------------------

async def _run_claude_search(prompt: str, schema_path: Path) -> dict:
    """Run claude -p with WebSearch as async subprocess."""
    claude_cli = config.find_claude_cli()
    schema = schema_path.read_text(encoding="utf-8")

    proc = await asyncio.create_subprocess_exec(
        claude_cli, "-p", prompt,
        "--output-format", "json",
        "--json-schema", schema,
        "--allowedTools", "WebSearch",
        "--max-turns", "10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=config.SEARCH_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SearchError(f"Search timed out after {config.SEARCH_TIMEOUT_SECONDS}s")

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")[:500]
        raise SearchError(f"claude -p exited with code {proc.returncode}: {stderr_text}")

    stdout_text = stdout_bytes.decode(errors="replace")
    try:
        output = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise SearchError(f"Failed to parse claude -p output as JSON: {e}")

    return output.get("structured_output", output)


def _build_poi_search_prompt(state: WorkflowState) -> str:
    """Build a self-contained POI search prompt for subprocess."""
    import yaml

    prefs = _load_trip_prefs(state.trip_id)
    profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
    destination = prefs.get("destination", state.trip_id)
    profile_yaml = yaml.dump(profile, allow_unicode=True, default_flow_style=False)

    return (
        f"You are a travel POI search agent. Find Points of Interest for a trip to {destination}.\n\n"
        f"## Traveler Profile\n{profile_yaml}\n\n"
        f"## Instructions\n"
        f"1. Search for POIs matching the traveler's interests.\n"
        f"2. For each POI, provide: name in English and Chinese, style category, "
        f"full address, typical visit duration, operating hours, description.\n"
        f"3. Include all wishlist items with their stated priority.\n"
        f"4. Add agent-suggested POIs that match the profile.\n"
        f"5. Aim for 30-50 candidate POIs.\n"
        f"6. Verify operating hours are current.\n\n"
        f"Return a JSON object matching the poi-candidates schema."
    )


def _build_restaurant_search_prompt(state: WorkflowState) -> str:
    """Build a self-contained restaurant search prompt for subprocess."""
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    itinerary_json = json.dumps(itinerary, indent=2, ensure_ascii=False)

    return (
        f"You are a restaurant recommendation agent. Given this itinerary, "
        f"recommend restaurants for each day.\n\n"
        f"## Itinerary\n{itinerary_json}\n\n"
        f"## Rules\n"
        f"- For each day, recommend one lunch and one dinner restaurant.\n"
        f"- Restaurants must be geographically close to that day's scheduled POIs.\n"
        f"- Include bilingual names (English + Chinese).\n"
        f"- Note if reservation is required.\n\n"
        f"Return a JSON object matching the restaurants schema."
    )


def _build_hotel_search_prompt(state: WorkflowState) -> str:
    """Build a self-contained hotel search prompt for subprocess."""
    itinerary = artifact_store.load_artifact(state.session_id, "itinerary") or {}
    itinerary_json = json.dumps(itinerary, indent=2, ensure_ascii=False)

    return (
        f"You are a hotel recommendation agent. Given this itinerary, "
        f"recommend hotels for each night.\n\n"
        f"## Itinerary\n{itinerary_json}\n\n"
        f"## Rules\n"
        f"- Group nights by region cluster from the itinerary.\n"
        f"- Include bilingual names where possible.\n"
        f"- Include booking URLs if available.\n\n"
        f"Return a JSON object matching the hotels schema."
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(description="Initialize a new trip and start the planning workflow. Returns session_id for all subsequent calls.")
def start_trip(
    destination: str,
    start_date: str,
    end_date: str,
    overrides: Optional[dict] = None,
) -> dict[str, Any]:
    from profile.trip_prefs import create_trip_prefs, save_trip_prefs

    cleanup_stale_sessions()

    prefs = create_trip_prefs(destination, start_date, end_date, overrides)
    trip_id = prefs["trip_id"]

    # Save trip prefs to legacy location (for profile merge)
    td = config.trip_dir(trip_id)
    td.mkdir(parents=True, exist_ok=True)
    save_trip_prefs(td / "trip-prefs.yaml", prefs)

    state = WorkflowState(trip_id)
    state.save()

    # Also save trip prefs in session dir for self-contained access
    save_trip_prefs(config.session_dir(state.session_id) / "trip-prefs.yaml", prefs)

    try:
        profile = _load_merged_profile(trip_id)
        profile_summary = {
            k: profile.get(k)
            for k in ("identity", "travel_interests", "travel_style", "travel_pace")
            if k in profile
        }
    except Exception:
        log.warning("Failed to load profile for trip %s", trip_id, exc_info=True)
        profile_summary = {}

    return {
        "session_id": state.session_id,
        "trip_id": trip_id,
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

    return {
        "status": "accepted",
        "next_action": _build_action(state),
    }


# ---------------------------------------------------------------------------
# Server-side search tools (3)
# ---------------------------------------------------------------------------

@mcp.tool(description="Search for POIs via WebSearch (server-side). Agent does NOT use WebSearch directly.")
async def search_pois(session_id: str) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    prompt = _build_poi_search_prompt(state)
    schema_path = config.CONTRACTS_DIR / "poi-candidates.json"

    try:
        result = await _run_claude_search(prompt, schema_path)
    except SearchError as e:
        log.error("POI search failed: %s", e)
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    violations = validation.validate_schema("poi_search", result)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "poi_search", result)
    state.complete_stage("poi_search")

    candidates = result.get("candidates", [])
    return {
        "status": "complete",
        "candidates_count": len(candidates),
        "sample": [c.get("name_en", "") for c in candidates[:5]],
        "next_action": _build_action(state),
    }


@mcp.tool(description="Search for restaurants via WebSearch (server-side).")
async def search_restaurants(session_id: str) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    prompt = _build_restaurant_search_prompt(state)
    schema_path = config.CONTRACTS_DIR / "restaurants.json"

    try:
        result = await _run_claude_search(prompt, schema_path)
    except SearchError as e:
        log.error("Restaurant search failed: %s", e)
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    violations = validation.validate_stage("restaurants", result, session_id)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "restaurants", result)
    state.complete_stage("restaurants")

    recs = result.get("recommendations", [])
    return {
        "status": "complete",
        "recommendations_count": len(recs),
        "next_action": _build_action(state),
    }


@mcp.tool(description="Search for hotels via WebSearch (server-side).")
async def search_hotels(session_id: str) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    prompt = _build_hotel_search_prompt(state)
    schema_path = config.CONTRACTS_DIR / "hotels.json"

    try:
        result = await _run_claude_search(prompt, schema_path)
    except SearchError as e:
        log.error("Hotel search failed: %s", e)
        return {"status": "search_failed", "error": str(e), "partial_results": []}

    violations = validation.validate_stage("hotels", result, session_id)
    if violations:
        return {"status": "validation_failed", "violations": violations}

    artifact_store.save_artifact(session_id, "hotels", result)
    state.complete_stage("hotels")

    recs = result.get("recommendations", [])
    return {
        "status": "complete",
        "recommendations_count": len(recs),
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


@mcp.tool(description="Update traveler profile (additive deep merge).")
def update_profile(updates: dict) -> dict[str, Any]:
    from profile.schema import deep_merge, load_profile, save_profile, validate_profile

    profile = load_profile(config.PROFILE_PATH)
    merged = deep_merge(profile, updates)
    validate_profile(merged)
    save_profile(config.PROFILE_PATH, merged)

    return {
        "status": "updated",
        "profile_summary": {
            k: merged.get(k)
            for k in ("identity", "travel_interests", "travel_style", "travel_pace")
            if k in merged
        },
    }


@mcp.tool(description="List all sessions with their workflow status.")
def list_trips() -> dict[str, Any]:
    return {"sessions": list_all_sessions()}


@mcp.tool(description="Cancel (abandon) a trip. Cleans up session directory.")
def cancel_trip(
    session_id: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(session_id)
    state.cancel(reason)
    return {"status": "cancelled", "session_id": session_id, "reason": reason}


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
