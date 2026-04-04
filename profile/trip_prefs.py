from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from profile.schema import deep_merge, load_profile, save_profile, validate_profile


def create_trip_prefs(
    destination: str,
    start_date: str,
    end_date: str,
    overrides: Optional[dict] = None,
) -> dict:
    return {
        "trip_id": f"{start_date[:7]}-{destination.lower().replace(' ', '-')}",
        "destination": destination,
        "dates": {"start": start_date, "end": end_date},
        "overrides": overrides or {},
    }


def save_trip_prefs(path: Path, prefs: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(prefs, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_trip_prefs(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Trip prefs must be a YAML mapping, got {type(data).__name__}")
    return data


def merge_with_profile(profile: dict, trip_prefs: dict) -> dict:
    overrides = trip_prefs.get("overrides", {})
    if not overrides:
        return profile
    merged = deep_merge(profile, overrides)
    validate_profile(merged)
    return merged
