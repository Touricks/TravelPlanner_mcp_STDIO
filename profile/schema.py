from pathlib import Path
from copy import deepcopy

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
                raise ValueError("travel_pace.pois_per_day must be a [min, max] list")
            if pois[0] > pois[1]:
                raise ValueError("pois_per_day min must be <= max")

    if "wishlist" in data:
        for i, item in enumerate(data["wishlist"]):
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


def deep_merge(base: dict, overlay: dict) -> dict:
    # Lists are replaced wholesale, not appended
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
