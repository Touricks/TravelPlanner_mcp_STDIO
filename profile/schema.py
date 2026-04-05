from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from typing import Optional

import yaml


VALID_PRIORITIES = {"must_visit", "nice_to_have", "flexible"}
VALID_BUDGET_TIERS = {"budget", "moderate", "premium"}
VALID_STYLES = {"nature", "tech", "culture", "food", "landmark", "coffee"}

REQUIRED_SECTIONS = {"identity", "travel_interests", "travel_style"}


def load_profile(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Profile must be a YAML mapping, got {type(data).__name__}")
    validate_profile(data)
    return data


def load_profile_safe(path: Path) -> dict:
    """Load profile, returning empty dict if missing or invalid."""
    try:
        return load_profile(path)
    except (FileNotFoundError, ValueError, yaml.YAMLError):
        return {}


def save_profile(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def validate_profile(data: dict) -> None:
    missing = REQUIRED_SECTIONS - set(data.keys())
    if missing:
        raise ValueError(f"Profile missing required sections: {missing}")

    if "travel_pace" in data:
        pace = data["travel_pace"]
        pois = pace.get("pois_per_day")
        if pois is not None:
            if not (isinstance(pois, list) and len(pois) == 2):
                raise ValueError(
                    "travel_pace.pois_per_day must be a [min, max] list of integers, "
                    f"e.g. [3, 5]. Got: {pois!r}"
                )
            if pois[0] > pois[1]:
                raise ValueError("pois_per_day min must be <= max")

    if "wishlist" in data:
        if not isinstance(data["wishlist"], list):
            raise ValueError(
                "wishlist must be a list of dicts, e.g. "
                '[{"name_en": "Place", "priority": "must_visit"}]. '
                f"Got {type(data['wishlist']).__name__}."
            )
        for i, item in enumerate(data["wishlist"]):
            if not isinstance(item, dict):
                raise ValueError(
                    f"wishlist[{i}] must be a dict with 'name_en' key. "
                    f"Got {type(item).__name__}."
                )
            if "name_en" not in item:
                raise ValueError(f"wishlist[{i}] missing name_en")
            pri = item.get("priority", "flexible")
            if pri not in VALID_PRIORITIES:
                raise ValueError(f"wishlist[{i}] invalid priority: {pri}")

    if "dietary" in data:
        tier = data["dietary"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            raise ValueError(f"Invalid dietary.budget_tier: {tier}")

    if "accommodation" in data:
        tier = data["accommodation"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            raise ValueError(f"Invalid accommodation.budget_tier: {tier}")


def validate_profile_structure(data: dict) -> None:
    """Validate structural constraints on present sections only.

    Unlike validate_profile, this does NOT check for required sections.
    Used during incremental profile building (profile_collection stage).
    """
    if "travel_pace" in data:
        pace = data["travel_pace"]
        pois = pace.get("pois_per_day")
        if pois is not None:
            if not (isinstance(pois, list) and len(pois) == 2):
                raise ValueError(
                    "travel_pace.pois_per_day must be a [min, max] list of integers, "
                    f"e.g. [3, 5]. Got: {pois!r}"
                )
            if pois[0] > pois[1]:
                raise ValueError("pois_per_day min must be <= max")

    if "wishlist" in data:
        if not isinstance(data["wishlist"], list):
            raise ValueError(
                "wishlist must be a list of dicts, e.g. "
                '[{"name_en": "Place", "priority": "must_visit"}]. '
                f"Got {type(data['wishlist']).__name__}."
            )
        for i, item in enumerate(data["wishlist"]):
            if not isinstance(item, dict):
                raise ValueError(
                    f"wishlist[{i}] must be a dict with 'name_en' key. "
                    f"Got {type(item).__name__}."
                )
            if "name_en" not in item:
                raise ValueError(f"wishlist[{i}] missing name_en")
            pri = item.get("priority", "flexible")
            if pri not in VALID_PRIORITIES:
                raise ValueError(f"wishlist[{i}] invalid priority: {pri}")

    if "dietary" in data:
        tier = data["dietary"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            raise ValueError(f"Invalid dietary.budget_tier: {tier}")

    if "accommodation" in data:
        tier = data["accommodation"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            raise ValueError(f"Invalid accommodation.budget_tier: {tier}")


def check_profile_completeness(data: dict) -> dict:
    """Check profile readiness for trip planning. Aligned with validate_profile."""
    missing_required: list[str] = []
    missing_optional: list[str] = []
    structural_issues: list[str] = []

    # Required sections — must exist AND be non-empty
    for section in REQUIRED_SECTIONS:
        if section not in data or not data[section]:
            missing_required.append(section)

    # Structural validation on present sections
    if "travel_pace" in data:
        pace = data["travel_pace"]
        pois = pace.get("pois_per_day")
        if pois is not None:
            if not (isinstance(pois, list) and len(pois) == 2 and pois[0] <= pois[1]):
                structural_issues.append(
                    "travel_pace.pois_per_day must be a [min, max] list of integers, "
                    f"e.g. [3, 5]. Got: {pois!r}"
                )

    if "wishlist" in data:
        if not isinstance(data["wishlist"], list):
            structural_issues.append(
                "wishlist must be a list of dicts, e.g. "
                '[{"name_en": "Place", "priority": "must_visit"}]. '
                f"Got {type(data['wishlist']).__name__}."
            )
        else:
            for i, item in enumerate(data["wishlist"]):
                if not isinstance(item, dict):
                    structural_issues.append(
                        f"wishlist[{i}] must be a dict with 'name_en' key. "
                        f"Got {type(item).__name__}."
                    )
                    continue
                if "name_en" not in item:
                    structural_issues.append(f"wishlist[{i}]: missing name_en")
                pri = item.get("priority", "flexible")
                if pri not in VALID_PRIORITIES:
                    structural_issues.append(f"wishlist[{i}]: invalid priority {pri}")

    if "dietary" in data:
        tier = data["dietary"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            structural_issues.append(f"dietary.budget_tier: invalid tier {tier}")

    if "accommodation" in data:
        tier = data["accommodation"].get("budget_tier")
        if tier is not None and tier not in VALID_BUDGET_TIERS:
            structural_issues.append(f"accommodation.budget_tier: invalid tier {tier}")

    # Optional but useful sections
    optional = {"travel_pace", "wishlist", "dietary", "accommodation"}
    for section in optional:
        if section not in data or not data[section]:
            missing_optional.append(section)

    return {
        "complete": len(missing_required) == 0 and len(structural_issues) == 0,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "structural_issues": structural_issues,
    }


def deep_merge(base: dict, overlay: dict) -> dict:
    # Lists are replaced wholesale, not appended
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
