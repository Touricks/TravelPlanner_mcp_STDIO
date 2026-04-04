from __future__ import annotations

from datetime import datetime
from typing import Optional


def _parse_time(t: str) -> datetime:
    return datetime.strptime(t, "%H:%M")


def _in_window(time_str: str, window: list[str]) -> bool:
    t = _parse_time(time_str)
    return _parse_time(window[0]) <= t <= _parse_time(window[1])


def check_soft_rules(itinerary: dict, guardrails: dict, profile: Optional[dict] = None) -> list[dict]:
    warnings = []
    soft = guardrails.get("soft_rules", {})

    if "daily_pace" in soft:
        warnings.extend(_check_daily_pace(itinerary, soft["daily_pace"], profile))
    if "region_cluster" in soft:
        warnings.extend(_check_region_cluster(itinerary, soft["region_cluster"]))
    if "meal_coverage" in soft:
        warnings.extend(_check_meal_coverage(itinerary, soft["meal_coverage"]))

    return warnings


def _check_daily_pace(itinerary: dict, rule: dict, profile: Optional[dict]) -> list[dict]:
    warnings = []
    pace_range = None
    if profile:
        pace_range = (profile.get("travel_pace") or {}).get("pois_per_day")
    if not pace_range:
        return warnings

    min_pace, max_pace = pace_range
    for day in itinerary.get("days", []):
        items = day.get("items", [])
        # count only top-level items (not nested children)
        top_count = sum(1 for it in items if it.get("parent_item_index") is None)
        if top_count < min_pace or top_count > max_pace:
            warnings.append({
                "rule": "daily_pace",
                "day_num": day.get("day_num"),
                "detail": f"Day {day['day_num']} has {top_count} POIs (target: {min_pace}-{max_pace})",
            })
    return warnings


def _check_region_cluster(itinerary: dict, rule: dict) -> list[dict]:
    warnings = []
    max_regions = rule.get("max_distinct_regions", 3)

    for day in itinerary.get("days", []):
        regions = set()
        for item in day.get("items", []):
            r = item.get("region") or day.get("region")
            if r:
                regions.add(r)
        if len(regions) > max_regions:
            warnings.append({
                "rule": "region_cluster",
                "day_num": day.get("day_num"),
                "detail": f"Day {day['day_num']} spans {len(regions)} regions: {', '.join(sorted(regions))}",
            })
    return warnings


def _check_meal_coverage(itinerary: dict, rule: dict) -> list[dict]:
    warnings = []
    lunch_window = rule.get("lunch_window", ["11:30", "13:30"])
    dinner_window = rule.get("dinner_window", ["17:30", "19:30"])

    for day in itinerary.get("days", []):
        items = day.get("items", [])
        has_lunch = any(
            it.get("style") in ("food", "coffee") and
            it.get("start_time") and _in_window(it["start_time"], lunch_window)
            for it in items
        )
        has_dinner = any(
            it.get("style") in ("food", "coffee") and
            it.get("start_time") and _in_window(it["start_time"], dinner_window)
            for it in items
        )
        missing = []
        if not has_lunch:
            missing.append("lunch")
        if not has_dinner:
            missing.append("dinner")
        if missing:
            warnings.append({
                "rule": "meal_coverage",
                "day_num": day.get("day_num"),
                "detail": f"Day {day['day_num']} missing {' and '.join(missing)} window",
            })
    return warnings
