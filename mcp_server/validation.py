from __future__ import annotations

import logging
from typing import Any

import jsonschema

from mcp_server.artifact_store import load_artifact
from mcp_server.config import load_contract, load_guardrails

log = logging.getLogger(__name__)


def validate_schema(stage: str, data: Any) -> list[dict]:
    """Validate data against the JSON Schema contract for a stage."""
    contract = load_contract(stage)
    if not contract:
        return []

    errors = []
    validator = jsonschema.Draft202012Validator(contract)
    for error in validator.iter_errors(data):
        errors.append({
            "rule": "schema",
            "item": ".".join(str(p) for p in error.absolute_path) or "(root)",
            "detail": error.message,
        })
    return errors


def validate_stage(stage: str, data: Any, trip_id: str) -> list[dict]:
    """Run all validations appropriate for a stage.

    Returns list of violations (empty = valid).
    """
    # 1. JSON Schema validation
    violations = validate_schema(stage, data)
    if violations:
        return violations

    # 2. Stage-specific semantic validation
    if stage == "scheduling":
        violations.extend(_validate_scheduling(data))
    elif stage == "restaurants":
        violations.extend(_validate_restaurants(data, trip_id))
    elif stage == "hotels":
        violations.extend(_validate_hotels(data, trip_id))

    return violations


def _validate_scheduling(data: dict) -> list[dict]:
    """Run hard rule checks on itinerary."""
    from rules.hard_rules import check_hard_rules

    guardrails = load_guardrails()
    return check_hard_rules(data, guardrails)


def _validate_restaurants(data: dict, trip_id: str) -> list[dict]:
    """Validate restaurant recommendations against itinerary."""
    violations = []
    itinerary = load_artifact(trip_id, "itinerary")
    if not itinerary:
        return violations

    valid_days = {day["day_num"] for day in itinerary.get("days", [])}
    for i, rec in enumerate(data.get("recommendations", [])):
        day_num = rec.get("day_num")
        if day_num is not None and day_num not in valid_days:
            violations.append({
                "rule": "restaurant_day_ref",
                "item": rec.get("name_en", f"recommendation[{i}]"),
                "detail": f"day_num {day_num} not in itinerary (valid: {sorted(valid_days)})",
            })
        if not rec.get("near_poi"):
            violations.append({
                "rule": "restaurant_near_poi",
                "item": rec.get("name_en", f"recommendation[{i}]"),
                "detail": "near_poi is required to link restaurant to itinerary",
            })
    return violations


def _validate_hotels(data: dict, trip_id: str) -> list[dict]:
    """Validate hotel recommendations against itinerary."""
    violations = []
    itinerary = load_artifact(trip_id, "itinerary")
    if not itinerary:
        return violations

    for i, rec in enumerate(data.get("recommendations", [])):
        if not rec.get("check_in"):
            violations.append({
                "rule": "hotel_check_in",
                "item": rec.get("name", f"recommendation[{i}]"),
                "detail": "check_in date is required",
            })
        if not rec.get("check_out"):
            violations.append({
                "rule": "hotel_check_out",
                "item": rec.get("name", f"recommendation[{i}]"),
                "detail": "check_out date is required",
            })
    return violations


def run_full_review(trip_id: str, skip_codex: bool = False) -> dict:
    """Run Stage 5 review: hard rules + soft rules + optional Codex.

    Returns the merged review report.
    """
    from review.merge_report import merge_reports
    from rules.hard_rules import check_hard_rules
    from rules.soft_rules import check_soft_rules

    itinerary = load_artifact(trip_id, "itinerary") or {}
    restaurants = load_artifact(trip_id, "restaurants") or {}
    hotels = load_artifact(trip_id, "hotels") or {}
    guardrails = load_guardrails()

    # Load profile for soft rules
    profile = None
    try:
        from profile.schema import load_profile
        from mcp_server.config import PROFILE_PATH

        if PROFILE_PATH.exists():
            profile = load_profile(PROFILE_PATH)
    except Exception:
        log.warning("Failed to load profile for soft rule checks", exc_info=True)

    # Hard + soft rule checks
    hard_violations = check_hard_rules(itinerary, guardrails)
    soft_warnings = check_soft_rules(itinerary, guardrails, profile)

    rule_report = {
        "trip_id": trip_id,
        "hard_violations": hard_violations,
        "soft_warnings": soft_warnings,
        "pass": len(hard_violations) == 0,
    }

    # Codex review (optional)
    codex_report: dict = {"items": []}
    if not skip_codex:
        try:
            from review.codex_review import run_codex_review

            codex_report = {"items": run_codex_review(itinerary, restaurants, hotels)}
        except Exception:
            log.warning("Codex review failed; proceeding without it", exc_info=True)

    merged = merge_reports(rule_report, codex_report)
    merged["trip_id"] = trip_id

    return merged
