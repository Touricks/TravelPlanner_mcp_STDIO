import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.hard_rules import check_hard_rules
from rules.soft_rules import check_soft_rules

GUARDRAILS_PATH = Path(__file__).resolve().parent.parent / "assets" / "configs" / "guardrails.yaml"
GUARDRAILS = yaml.safe_load(GUARDRAILS_PATH.read_text())


def _make_day(day_num, items):
    return {"date": f"2026-04-{16 + day_num}", "day_num": day_num, "region": "SF", "items": items}


def _make_itinerary(days):
    return {"trip_id": "test", "start_date": "2026-04-17", "end_date": "2026-04-25", "days": days}


class TestNatureSunset:
    def test_nature_before_1900_passes(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Beach", "style": "nature", "start_time": "09:00", "end_time": "18:00", "duration_minutes": 540},
        ])])
        assert check_hard_rules(it, GUARDRAILS) == []

    def test_nature_after_1900_fails(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Sunset Hike", "style": "nature", "start_time": "18:00", "end_time": "20:00", "duration_minutes": 120},
        ])])
        violations = check_hard_rules(it, GUARDRAILS)
        assert len(violations) == 1
        assert "Sunset Hike" in violations[0]["detail"]

    def test_food_after_1900_ok(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Late Dinner", "style": "food", "start_time": "19:00", "end_time": "21:00", "duration_minutes": 120},
        ])])
        assert check_hard_rules(it, GUARDRAILS) == []


class TestStaffedClosing:
    def test_tech_before_1600_passes(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Museum", "style": "tech", "start_time": "10:00", "end_time": "15:00", "duration_minutes": 300},
        ])])
        assert check_hard_rules(it, GUARDRAILS) == []

    def test_culture_after_1600_fails(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Gallery", "style": "culture", "start_time": "14:00", "end_time": "17:00", "duration_minutes": 180},
        ])])
        violations = check_hard_rules(it, GUARDRAILS)
        assert len(violations) == 1
        assert "Gallery" in violations[0]["detail"]


class TestTimeOverlap:
    def test_no_overlap_passes(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "A", "style": "food", "start_time": "09:00", "end_time": "10:00", "duration_minutes": 60},
            {"name_en": "B", "style": "food", "start_time": "10:30", "end_time": "11:30", "duration_minutes": 60},
        ])])
        assert check_hard_rules(it, GUARDRAILS) == []

    def test_overlap_detected(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "A", "style": "food", "start_time": "09:00", "end_time": "10:30", "duration_minutes": 90},
            {"name_en": "B", "style": "food", "start_time": "10:00", "end_time": "11:00", "duration_minutes": 60},
        ])])
        violations = check_hard_rules(it, GUARDRAILS)
        overlap_violations = [v for v in violations if v["rule"] == "time_overlap"]
        assert len(overlap_violations) == 1

    def test_parent_child_overlap_suppressed(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Chinatown Visit", "style": "culture", "start_time": "10:00", "end_time": "12:00", "duration_minutes": 120},
            {"name_en": "Dim Sum", "style": "food", "start_time": "10:30", "end_time": "11:30", "duration_minutes": 60, "parent_item_index": 0},
        ])])
        violations = check_hard_rules(it, GUARDRAILS)
        overlap_violations = [v for v in violations if v["rule"] == "time_overlap"]
        assert len(overlap_violations) == 0


class TestTravelTime:
    def test_sufficient_gap_passes(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "A", "style": "food", "start_time": "09:00", "end_time": "10:00", "duration_minutes": 60},
            {"name_en": "B", "style": "food", "start_time": "11:30", "end_time": "12:30", "duration_minutes": 60, "preceding_travel_minutes": 60},
        ])])
        assert check_hard_rules(it, GUARDRAILS) == []

    def test_insufficient_gap_fails(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Chef Chu's", "style": "food", "start_time": "13:30", "end_time": "15:00", "duration_minutes": 90},
            {"name_en": "Whale Watch", "style": "nature", "start_time": "15:30", "end_time": "18:00", "duration_minutes": 150, "preceding_travel_minutes": 90},
        ])])
        violations = check_hard_rules(it, GUARDRAILS)
        travel_violations = [v for v in violations if v["rule"] == "travel_time"]
        assert len(travel_violations) == 1


class TestSoftRules:
    def test_meal_coverage_warning(self):
        it = _make_itinerary([_make_day(1, [
            {"name_en": "Museum", "style": "tech", "start_time": "09:00", "end_time": "12:00", "duration_minutes": 180},
        ])])
        warnings = check_soft_rules(it, GUARDRAILS)
        meal_warnings = [w for w in warnings if w["rule"] == "meal_coverage"]
        assert len(meal_warnings) == 1
        assert "lunch and dinner" in meal_warnings[0]["detail"]

    def test_daily_pace_warning(self):
        items = [
            {"name_en": f"POI {i}", "style": "culture", "start_time": f"{8+i}:00", "end_time": f"{8+i}:30", "duration_minutes": 30}
            for i in range(8)
        ]
        it = _make_itinerary([_make_day(1, items)])
        profile = {"travel_pace": {"pois_per_day": [3, 5]}}
        warnings = check_soft_rules(it, GUARDRAILS, profile)
        pace_warnings = [w for w in warnings if w["rule"] == "daily_pace"]
        assert len(pace_warnings) == 1

    def test_region_cluster_warning(self):
        items = [
            {"name_en": "A", "style": "food", "start_time": "09:00", "end_time": "10:00", "duration_minutes": 60, "region": "SF"},
            {"name_en": "B", "style": "food", "start_time": "11:00", "end_time": "12:00", "duration_minutes": 60, "region": "Oakland"},
            {"name_en": "C", "style": "food", "start_time": "13:00", "end_time": "14:00", "duration_minutes": 60, "region": "San Jose"},
            {"name_en": "D", "style": "food", "start_time": "15:00", "end_time": "15:30", "duration_minutes": 30, "region": "Palo Alto"},
        ]
        it = _make_itinerary([_make_day(1, items)])
        warnings = check_soft_rules(it, GUARDRAILS)
        region_warnings = [w for w in warnings if w["rule"] == "region_cluster"]
        assert len(region_warnings) == 1
