import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from profile.schema import load_profile, validate_profile, deep_merge, save_profile
from profile.trip_prefs import create_trip_prefs, merge_with_profile


PROTOTYPE_PROFILE = Path(__file__).resolve().parent.parent / "prototype" / "userProfile" / "profile.yaml"


class TestLoadExistingProfile:
    def test_loads_prototype_profile(self):
        if not PROTOTYPE_PROFILE.exists():
            pytest.skip("prototype profile not found")
        data = load_profile(PROTOTYPE_PROFILE)
        assert "identity" in data
        assert "travel_interests" in data
        assert "travel_style" in data

    def test_missing_section_raises(self):
        with pytest.raises(ValueError, match="missing required sections"):
            validate_profile({"identity": {}, "travel_interests": {}})


class TestDeepMerge:
    def test_adds_new_keys(self):
        base = {"a": 1, "b": {"c": 2}}
        overlay = {"b": {"d": 3}, "e": 4}
        result = deep_merge(base, overlay)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}

    def test_no_field_loss(self):
        if not PROTOTYPE_PROFILE.exists():
            pytest.skip("prototype profile not found")
        data = load_profile(PROTOTYPE_PROFILE)
        original_keys = set(data.keys())
        overlay = {"travel_pace": {"pois_per_day": [3, 5]}}
        merged = deep_merge(data, overlay)
        assert original_keys.issubset(set(merged.keys()))
        assert "travel_pace" in merged

    def test_overlay_replaces_lists(self):
        base = {"items": [1, 2, 3]}
        overlay = {"items": [4, 5]}
        result = deep_merge(base, overlay)
        assert result["items"] == [4, 5]


class TestTripPrefs:
    def test_create_trip_prefs(self):
        prefs = create_trip_prefs("San Francisco", "2026-04-17", "2026-04-25")
        assert prefs["trip_id"] == "2026-04-san-francisco"
        assert prefs["dates"]["start"] == "2026-04-17"

    def test_merge_with_profile(self):
        profile = {
            "identity": {"role": "traveler"},
            "travel_interests": {"nature": {}},
            "travel_style": {"pacing": "balanced"},
            "travel_pace": {"pois_per_day": [3, 5]},
        }
        trip_prefs = {
            "trip_id": "test",
            "destination": "SF",
            "dates": {"start": "2026-04-17", "end": "2026-04-25"},
            "overrides": {"travel_pace": {"pois_per_day": [2, 3]}},
        }
        merged = merge_with_profile(profile, trip_prefs)
        assert merged["travel_pace"]["pois_per_day"] == [2, 3]
        assert merged["identity"]["role"] == "traveler"


class TestTripPrefsDateGuard:
    def test_invalid_start_date_raises(self):
        with pytest.raises(ValueError, match="start_date must be ISO format"):
            create_trip_prefs("Tokyo", "next week", "2026-05-10")

    def test_invalid_end_date_raises(self):
        with pytest.raises(ValueError, match="end_date must be ISO format"):
            create_trip_prefs("Tokyo", "2026-05-01", "sometime")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="start_date must be ISO format"):
            create_trip_prefs("Tokyo", "", "2026-05-10")


class TestDateValidation:
    def setup_method(self):
        from mcp_server.validation import validate_date_params
        self.validate = validate_date_params

    def test_valid_dates_pass(self):
        assert self.validate("2026-04-17", "2026-04-25") == []

    def test_single_day_trip(self):
        assert self.validate("2026-04-17", "2026-04-17") == []

    def test_invalid_format(self):
        v = self.validate("not-a-date", "2026-04-25")
        assert len(v) == 1
        assert v[0]["rule"] == "date_format"

    def test_both_invalid(self):
        v = self.validate("foo", "bar")
        assert len(v) == 2
        assert all(x["rule"] == "date_format" for x in v)

    def test_end_before_start(self):
        v = self.validate("2026-04-25", "2026-04-17")
        assert any(x["rule"] == "date_range" for x in v)

    def test_excessive_duration(self):
        v = self.validate("2026-01-01", "2026-12-31")
        assert any(x["rule"] == "date_duration" for x in v)

    def test_distant_past(self):
        v = self.validate("2020-01-01", "2020-01-10")
        assert any(x["rule"] == "date_past" for x in v)

    def test_empty_string(self):
        v = self.validate("", "2026-04-25")
        assert any(x["rule"] == "date_format" for x in v)


class TestValidation:
    def test_valid_wishlist(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "wishlist": [{"name_en": "Sequoia", "priority": "must_visit"}],
        }
        validate_profile(data)

    def test_invalid_priority_raises(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "wishlist": [{"name_en": "Test", "priority": "invalid"}],
        }
        with pytest.raises(ValueError, match="invalid priority"):
            validate_profile(data)

    def test_pois_per_day_range(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "travel_pace": {"pois_per_day": [5, 3]},
        }
        with pytest.raises(ValueError, match="min must be <= max"):
            validate_profile(data)

    def test_wishlist_dict_rejected(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "wishlist": {"must_visit": ["Bixby Bridge"], "skip": ["mall"]},
        }
        with pytest.raises(ValueError, match="wishlist must be a list"):
            validate_profile(data)

    def test_wishlist_list_of_strings_rejected(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "wishlist": ["Bixby Bridge", "McWay Falls"],
        }
        with pytest.raises(ValueError, match="must be a dict"):
            validate_profile(data)

    def test_pois_per_day_string_shows_value(self):
        data = {
            "identity": {}, "travel_interests": {}, "travel_style": {},
            "travel_pace": {"pois_per_day": "3-4"},
        }
        with pytest.raises(ValueError, match=r"Got.*3-4"):
            validate_profile(data)
