from __future__ import annotations

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
from mcp_server.workflow import WorkflowState, list_all_trips

log = logging.getLogger(__name__)

mcp = FastMCP(
    "travel-planner",
    instructions="MCP server for autonomous travel planning workflow. Use the plan_trip prompt to start an autonomous trip planning session.",
)


def _build_action(state: WorkflowState) -> dict[str, Any]:
    """Build the next action payload from current workflow state."""
    stage = state.current_stage

    if state.status == "complete":
        return {"status": "complete", "summary": _trip_summary(state)}

    if state.status in ("blocked", "cancelled"):
        return {
            "status": "blocked",
            "stage": stage,
            "reason": state.block_reason or f"Trip is {state.status}",
            "max_retries_exceeded": state.is_blocked(stage),
        }

    instructions = ""
    context: dict[str, str] = {}
    try:
        from pipeline.stages.stage_prompts import load_prompt

        if stage == "poi_search":
            import yaml
            prefs = _load_trip_prefs(state.trip_id)
            profile = _load_merged_profile_from_prefs(state.trip_id, prefs)
            context["profile"] = yaml.dump(profile, allow_unicode=True, default_flow_style=False)
            context["destination"] = prefs.get("destination", state.trip_id)
        elif stage == "scheduling":
            context["guardrails"] = config.GUARDRAILS_PATH.read_text(encoding="utf-8")

        prompt_name = config.STAGE_PROMPTS.get(stage)
        if prompt_name:
            instructions = load_prompt(prompt_name, context)
    except Exception as e:
        log.warning("Prompt loading failed for stage %s: %s", stage, e, exc_info=True)
        instructions = f"Execute stage: {stage}."

    input_artifacts: dict[str, Any] = {}
    for name in config.STAGE_INPUT_ARTIFACTS.get(stage, []):
        art = artifact_store.load_artifact(state.trip_id, name)
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


def _trip_summary(state: WorkflowState) -> dict[str, Any]:
    return {
        "trip_id": state.trip_id,
        "status": state.status,
        "completed_stages": state.completed_stages,
        "notion_urls": state.notion_urls,
        "artifacts": artifact_store.list_artifacts(state.trip_id),
    }


def _load_trip_prefs(trip_id: str) -> dict:
    from profile.trip_prefs import load_trip_prefs

    prefs_path = config.trip_dir(trip_id) / "trip-prefs.yaml"
    try:
        return load_trip_prefs(prefs_path)
    except (FileNotFoundError, ValueError):
        return {}


def _load_merged_profile_from_prefs(trip_id: str, prefs: dict) -> dict:
    """Load base profile and merge with already-loaded trip prefs."""
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
    """Derive the regression target stage from violation data."""
    rules = {v.get("rule", "") for v in violations}
    restaurant_rules = {"restaurant_day_ref", "restaurant_near_poi"}
    hotel_rules = {"hotel_check_in", "hotel_check_out"}
    if rules & restaurant_rules:
        return "restaurants"
    if rules & hotel_rules:
        return "hotels"
    return "scheduling"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(description="Initialize a new trip and start the planning workflow.")
def start_trip(
    destination: str,
    start_date: str,
    end_date: str,
    overrides: Optional[dict] = None,
) -> dict[str, Any]:
    from profile.trip_prefs import create_trip_prefs, save_trip_prefs

    prefs = create_trip_prefs(destination, start_date, end_date, overrides)
    trip_id = prefs["trip_id"]

    td = config.trip_dir(trip_id)
    td.mkdir(parents=True, exist_ok=True)
    save_trip_prefs(td / "trip-prefs.yaml", prefs)

    state = WorkflowState(trip_id)
    state.save()

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
        "trip_id": trip_id,
        "profile_summary": profile_summary,
        "first_action": _build_action(state),
    }


@mcp.tool(description="Get the next action the agent should perform in the workflow.")
def get_next_action(trip_id: str) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)
    return _build_action(state)


@mcp.tool(description="Submit a stage artifact for validation and storage.")
def submit_artifact(
    trip_id: str,
    stage: str,
    data: dict,
) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)

    if state.status != "active":
        return {"status": "blocked", "reason": f"Trip is {state.status}"}

    violations = validation.validate_stage(stage, data, trip_id)

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

    artifact_store.save_artifact(trip_id, stage, data)
    state.complete_stage(stage)

    return {
        "status": "accepted",
        "next_action": _build_action(state),
    }


@mcp.tool(description="Run Stage 5 review (rule engine + optional Codex). Server-side execution.")
def run_review(
    trip_id: str,
    skip_codex: bool = False,
) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)

    review_report = validation.run_full_review(trip_id, skip_codex)
    artifact_store.save_artifact(trip_id, "review", review_report)

    hard_violations = [
        item for item in review_report.get("items", [])
        if item.get("source") == "hard_rule" and item.get("verdict") == "reject"
    ]

    if hard_violations:
        target_stage = _determine_regression_target(hard_violations)
        result = state.regress_to(target_stage, hard_violations)
        return {
            "review_report": review_report,
            "hard_pass": False,
            **result,
        }

    state.complete_stage("review")

    return {
        "review_report": review_report,
        "hard_pass": True,
        "next_action": _build_action(state),
    }


@mcp.tool(description="Generate Notion publishing manifest from validated artifacts.")
def build_notion_manifest(trip_id: str) -> dict[str, Any]:
    from output.notion_publisher import build_manifest

    itinerary = artifact_store.load_artifact(trip_id, "itinerary") or {}
    restaurants = artifact_store.load_artifact(trip_id, "restaurants") or {}
    hotels = artifact_store.load_artifact(trip_id, "hotels") or {}
    review_report = artifact_store.load_artifact(trip_id, "review-report") or {}

    manifest = build_manifest(itinerary, restaurants, hotels, review_report)
    artifact_store.save_artifact(trip_id, "notion-manifest", manifest)

    return {"manifest": manifest}


@mcp.tool(description="Record Notion URLs after publishing. Supports partial publish (call per database).")
def record_notion_urls(
    trip_id: str,
    parent_page_url: str,
    database_ids: dict,
) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)

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

    return {
        "status": "accepted",
        "next_action": _build_action(state),
    }


@mcp.tool(description="Mark trip workflow as complete after verification.")
def complete_trip(
    trip_id: str,
    verification_notes: Optional[str] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)
    state.complete_stage("verify")

    return {
        "status": "complete",
        "summary": _trip_summary(state),
        "verification_notes": verification_notes,
    }


@mcp.tool(description="Read-only workflow status check.")
def get_workflow_status(trip_id: str) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)
    return {
        **state.to_dict(),
        "artifacts_available": artifact_store.list_artifacts(trip_id),
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


@mcp.tool(description="List all trips with their workflow status.")
def list_trips() -> dict[str, Any]:
    return {"trips": list_all_trips()}


@mcp.tool(description="Cancel (abandon) a trip.")
def cancel_trip(
    trip_id: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    state = WorkflowState.load(trip_id)
    state.cancel(reason)
    return {"status": "cancelled", "trip_id": trip_id, "reason": reason}


@mcp.tool(description="Human-assisted recovery from blocked state.")
def resolve_blocked(
    trip_id: str,
    action: str,
    user_note: Optional[str] = None,
) -> dict[str, Any]:
    if action not in ("retry", "skip", "override"):
        return {"status": "error", "reason": f"Invalid action: {action}. Use retry/skip/override."}

    state = WorkflowState.load(trip_id)
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
    "travel://trip/{trip_id}/profile",
    description="Merged profile (base + trip overrides)",
    mime_type="text/yaml",
)
def get_trip_profile(trip_id: str) -> str:
    import yaml

    profile = _load_merged_profile(trip_id)
    return yaml.dump(profile, allow_unicode=True, default_flow_style=False)


@mcp.resource(
    "travel://trip/{trip_id}/artifact/{name}",
    description="Stage artifact (poi-candidates, itinerary, restaurants, hotels, review-report)",
    mime_type="application/json",
)
def get_artifact(trip_id: str, name: str) -> str:
    data = artifact_store.load_artifact(trip_id, name)
    if data is None:
        return json.dumps({"error": f"Artifact '{name}' not found for trip {trip_id}"})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://trip/{trip_id}/state",
    description="Workflow state (current stage, attempts, errors)",
    mime_type="application/json",
)
def get_trip_state(trip_id: str) -> str:
    state = WorkflowState.load(trip_id)
    return json.dumps(state.to_dict(), indent=2, ensure_ascii=False)


@mcp.resource(
    "travel://trip/{trip_id}/notion-manifest",
    description="Generated Notion publishing manifest (cached after build_notion_manifest)",
    mime_type="application/json",
)
def get_notion_manifest(trip_id: str) -> str:
    data = artifact_store.load_artifact(trip_id, "notion-manifest")
    if data is None:
        return json.dumps({"error": "Notion manifest not yet generated. Call build_notion_manifest first."})
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
    description="Autonomously plan a complete trip — POI search, scheduling, validation, restaurant/hotel recommendations, and Notion publishing.",
)
def plan_trip(user_request: str) -> str:
    return PLAN_TRIP_PROMPT.format(user_request=user_request)


if __name__ == "__main__":
    mcp.run(transport="stdio")
