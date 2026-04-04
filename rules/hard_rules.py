from datetime import datetime


def _parse_time(t: str) -> datetime:
    return datetime.strptime(t, "%H:%M")


def check_hard_rules(itinerary: dict, guardrails: dict) -> list[dict]:
    violations = []
    hard = guardrails.get("hard_rules", {})

    if "nature_sunset" in hard:
        violations.extend(_check_time_limit(itinerary, hard["nature_sunset"]))
    if "staffed_closing" in hard:
        violations.extend(_check_time_limit(itinerary, hard["staffed_closing"]))
    if "time_overlap" in hard:
        violations.extend(_check_time_overlap(itinerary, hard["time_overlap"]))
    if "travel_time" in hard:
        violations.extend(_check_travel_time(itinerary))

    return violations


def _check_time_limit(itinerary: dict, rule: dict) -> list[dict]:
    violations = []
    styles = set(rule.get("applies_to", {}).get("style", []))
    constraint = rule.get("constraint", {})
    limit = constraint.get("value", "23:59")
    limit_dt = _parse_time(limit)

    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            if item.get("style") not in styles:
                continue
            end_time = item.get("end_time")
            if not end_time:
                continue
            if _parse_time(end_time) >= limit_dt:
                violations.append({
                    "rule": rule.get("description", "time_limit"),
                    "item": item.get("name_en", "unknown"),
                    "day_num": day.get("day_num"),
                    "detail": f"{item['name_en']} ends at {end_time}, limit is {limit}",
                })
    return violations


def _check_time_overlap(itinerary: dict, rule: dict) -> list[dict]:
    violations = []
    suppress_parent_child = rule.get("suppress_if") == "parent_child"

    for day in itinerary.get("days", []):
        items = day.get("items", [])
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if not (a.get("start_time") and a.get("end_time") and
                        b.get("start_time") and b.get("end_time")):
                    continue

                # suppress parent-child overlaps
                if suppress_parent_child:
                    if b.get("parent_item_index") == i or a.get("parent_item_index") == j:
                        continue

                a_end = _parse_time(a["end_time"])
                b_start = _parse_time(b["start_time"])
                b_end = _parse_time(b["end_time"])
                a_start = _parse_time(a["start_time"])

                if a_start < b_end and b_start < a_end:
                    violations.append({
                        "rule": "time_overlap",
                        "item": f"{a['name_en']} / {b['name_en']}",
                        "day_num": day.get("day_num"),
                        "detail": (
                            f"{a['name_en']} ({a['start_time']}-{a['end_time']}) "
                            f"overlaps {b['name_en']} ({b['start_time']}-{b['end_time']})"
                        ),
                    })
    return violations


def _check_travel_time(itinerary: dict) -> list[dict]:
    violations = []
    for day in itinerary.get("days", []):
        items = day.get("items", [])
        # only check consecutive non-nested items
        top_level = [it for it in items if it.get("parent_item_index") is None]
        sorted_items = sorted(top_level, key=lambda x: x.get("start_time", "00:00"))

        for i in range(1, len(sorted_items)):
            prev = sorted_items[i - 1]
            curr = sorted_items[i]
            travel_needed = curr.get("preceding_travel_minutes", 0)
            if not travel_needed:
                continue

            prev_end = _parse_time(prev.get("end_time", "00:00"))
            curr_start = _parse_time(curr.get("start_time", "23:59"))
            gap_minutes = (curr_start - prev_end).total_seconds() / 60

            if gap_minutes < travel_needed:
                violations.append({
                    "rule": "travel_time",
                    "item": f"{prev['name_en']} -> {curr['name_en']}",
                    "day_num": day.get("day_num"),
                    "detail": (
                        f"Only {int(gap_minutes)}min gap between "
                        f"{prev['name_en']} and {curr['name_en']}, "
                        f"but {travel_needed}min travel needed"
                    ),
                })
    return violations
