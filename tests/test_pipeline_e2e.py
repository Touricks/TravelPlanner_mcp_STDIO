import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.hard_rules import check_hard_rules
from rules.soft_rules import check_soft_rules
from review.merge_report import merge_reports
from output.notion_publisher import build_manifest
from profile.schema import load_profile, deep_merge

GUARDRAILS_PATH = Path(__file__).resolve().parent.parent / "assets" / "configs" / "guardrails.yaml"
GOOD_ITINERARY = Path(__file__).resolve().parent / "fixtures" / "test_itinerary_good.json"
PROTOTYPE_PROFILE = Path(__file__).resolve().parent.parent / "prototype" / "userProfile" / "profile.yaml"


class TestEndToEnd:
    @pytest.fixture
    def guardrails(self):
        return yaml.safe_load(GUARDRAILS_PATH.read_text())

    @pytest.fixture
    def itinerary(self):
        return json.loads(GOOD_ITINERARY.read_text())

    @pytest.fixture
    def restaurants(self):
        return {
            "trip_id": "2026-04-san-francisco",
            "recommendations": [
                {"day_num": 1, "meal_type": "lunch", "name_en": "Chinatown Dim Sum", "cuisine": "Chinese", "address": "Grant Ave", "near_poi": "Chinatown"},
                {"day_num": 1, "meal_type": "dinner", "name_en": "Fisherman's Grotto", "cuisine": "Seafood", "address": "Pier 39", "near_poi": "Fisherman's Wharf"},
                {"day_num": 2, "meal_type": "lunch", "name_en": "Sam's Chowder House", "cuisine": "American", "address": "Half Moon Bay", "near_poi": "Half Moon Bay Beach"},
                {"day_num": 2, "meal_type": "dinner", "name_en": "Monterey Fish House", "cuisine": "Seafood", "address": "Monterey", "near_poi": "Monterey Aquarium"},
            ],
        }

    @pytest.fixture
    def hotels(self):
        return {
            "trip_id": "2026-04-san-francisco",
            "recommendations": [
                {"check_in": "2026-04-17", "check_out": "2026-04-18", "name": "Hotel Nikko SF", "address": "222 Mason St", "city": "San Francisco"},
                {"check_in": "2026-04-18", "check_out": "2026-04-19", "name": "Monterey Bay Inn", "address": "242 Cannery Row", "city": "Monterey"},
            ],
        }

    def test_rule_engine_passes_good_itinerary(self, itinerary, guardrails):
        violations = check_hard_rules(itinerary, guardrails)
        assert len(violations) == 0, f"Unexpected violations: {violations}"

    def test_soft_rules_generate_warnings(self, itinerary, guardrails):
        warnings = check_soft_rules(itinerary, guardrails)
        assert isinstance(warnings, list)

    def test_merge_report_structure(self, itinerary, guardrails):
        hard = check_hard_rules(itinerary, guardrails)
        soft = check_soft_rules(itinerary, guardrails)
        rule_report = {"hard_violations": hard, "soft_warnings": soft, "pass": len(hard) == 0}
        codex_report = {"source": "codex", "items": []}
        merged = merge_reports(rule_report, codex_report)
        assert "summary" in merged
        assert merged["summary"]["rejected"] == 0

    def test_notion_manifest_has_4_databases(self, itinerary, restaurants, hotels):
        review = {"items": [], "summary": {"total_items": 0, "accepted": 0, "flagged": 0, "rejected": 0}}
        manifest = build_manifest(itinerary, restaurants, hotels, review)
        assert set(manifest["databases"].keys()) == {"itinerary", "restaurants", "hotels", "notices"}

    def test_itinerary_entries_match_source(self, itinerary, restaurants, hotels):
        review = {"items": [], "summary": {"total_items": 0, "accepted": 0, "flagged": 0, "rejected": 0}}
        manifest = build_manifest(itinerary, restaurants, hotels, review)
        total_source_items = sum(len(d["items"]) for d in itinerary["days"])
        assert len(manifest["databases"]["itinerary"]["entries"]) == total_source_items

    def test_restaurant_entries_match_source(self, itinerary, restaurants, hotels):
        review = {"items": [], "summary": {"total_items": 0, "accepted": 0, "flagged": 0, "rejected": 0}}
        manifest = build_manifest(itinerary, restaurants, hotels, review)
        assert len(manifest["databases"]["restaurants"]["entries"]) == len(restaurants["recommendations"])

    def test_profile_loads_and_extends(self):
        if not PROTOTYPE_PROFILE.exists():
            pytest.skip("prototype profile not found")
        profile = load_profile(PROTOTYPE_PROFILE)
        extended = deep_merge(profile, {
            "travel_pace": {"pois_per_day": [3, 5]},
            "wishlist": [{"name_en": "Sequoia", "priority": "must_visit"}],
        })
        assert "travel_pace" in extended
        assert "identity" in extended
