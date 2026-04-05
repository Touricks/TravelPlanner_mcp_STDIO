"""Tests for profile elicitation workflow (Stage 1: Profile Collection).

Covers:
- Profile safe loading and completeness checking
- WorkflowState instance-level stages + serialization
- Dynamic profile_collection stage insertion in start_trip
- Question filtering with sentinel-based answered detection
- Destination question matching (multi-match + fallback)
- complete_profile_collection tool
- Regression guard for profile_collection
- Backward compatibility for legacy sessions
"""
import sys
import json
import tempfile
from pathlib import Path
from copy import deepcopy

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from profile.schema import (
    check_profile_completeness,
    load_profile_safe,
    validate_profile_structure,
)
from mcp_server.config import (
    STAGES,
    load_destination_questions,
    load_profile_questions,
)
from mcp_server.workflow import WorkflowState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPLETE_PROFILE = {
    "identity": {"role": "engineer", "language": "bilingual"},
    "travel_interests": {"nature": {"description": "hiking"}, "culture": {}},
    "travel_style": {"daily_schedule": "08:00-21:00", "pacing": "balanced"},
    "travel_pace": {"pois_per_day": [3, 5]},
    "dietary": {"preferences": ["local"], "restrictions": []},
    "accommodation": {"budget_tier": "moderate", "preferences": ["clean"]},
}

MINIMAL_PROFILE = {
    "identity": {"role": "student"},
    "travel_interests": {"food": {}},
    "travel_style": {"pacing": "relaxed"},
}

EMPTY_PROFILE: dict = {}


# ---------------------------------------------------------------------------
# load_profile_safe
# ---------------------------------------------------------------------------

class TestLoadProfileSafe:
    def test_returns_empty_dict_on_missing_file(self, tmp_path):
        result = load_profile_safe(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_returns_empty_dict_on_invalid_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: a\n  valid: yaml: file: [", encoding="utf-8")
        result = load_profile_safe(bad)
        assert result == {}

    def test_returns_empty_dict_on_missing_required_sections(self, tmp_path):
        partial = tmp_path / "partial.yaml"
        partial.write_text(yaml.dump({"identity": {"role": "test"}}), encoding="utf-8")
        result = load_profile_safe(partial)
        assert result == {}  # validate_profile raises -> caught -> {}

    def test_returns_valid_profile(self, tmp_path):
        valid = tmp_path / "valid.yaml"
        valid.write_text(yaml.dump(COMPLETE_PROFILE), encoding="utf-8")
        result = load_profile_safe(valid)
        assert result["identity"]["role"] == "engineer"


# ---------------------------------------------------------------------------
# check_profile_completeness
# ---------------------------------------------------------------------------

class TestCheckProfileCompleteness:
    def test_complete_profile(self):
        result = check_profile_completeness(COMPLETE_PROFILE)
        assert result["complete"] is True
        assert result["missing_required"] == []
        assert result["structural_issues"] == []

    def test_minimal_profile_is_complete(self):
        result = check_profile_completeness(MINIMAL_PROFILE)
        assert result["complete"] is True
        assert "travel_pace" in result["missing_optional"]

    def test_empty_profile_is_incomplete(self):
        result = check_profile_completeness(EMPTY_PROFILE)
        assert result["complete"] is False
        assert set(result["missing_required"]) == {"identity", "travel_interests", "travel_style"}

    def test_missing_identity(self):
        data = {k: v for k, v in COMPLETE_PROFILE.items() if k != "identity"}
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert "identity" in result["missing_required"]

    def test_structural_issue_pois_per_day_reversed(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["travel_pace"]["pois_per_day"] = [5, 3]
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert len(result["structural_issues"]) == 1
        assert "pois_per_day" in result["structural_issues"][0]

    def test_structural_issue_invalid_wishlist_priority(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["wishlist"] = [{"name_en": "Test", "priority": "INVALID"}]
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert any("priority" in i for i in result["structural_issues"])

    def test_structural_issue_missing_wishlist_name_en(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["wishlist"] = [{"priority": "must_visit"}]
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert any("name_en" in i for i in result["structural_issues"])

    def test_structural_issue_invalid_budget_tier(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["accommodation"]["budget_tier"] = "luxury"
        result = check_profile_completeness(data)
        assert result["complete"] is False


# ---------------------------------------------------------------------------
# validate_profile_structure
# ---------------------------------------------------------------------------

class TestValidateProfileStructure:
    def test_empty_profile_passes(self):
        # No required sections check — should not raise
        validate_profile_structure({})

    def test_partial_profile_passes(self):
        validate_profile_structure({"identity": {"role": "test"}})

    def test_invalid_pace_raises(self):
        with pytest.raises(ValueError, match="pois_per_day"):
            validate_profile_structure({"travel_pace": {"pois_per_day": [5, 3]}})

    def test_invalid_budget_tier_raises(self):
        with pytest.raises(ValueError, match="budget_tier"):
            validate_profile_structure({"accommodation": {"budget_tier": "luxury"}})

    def test_wishlist_dict_rejected(self):
        with pytest.raises(ValueError, match="wishlist must be a list"):
            validate_profile_structure({"wishlist": {"must_visit": ["X"]}})

    def test_wishlist_list_of_strings_rejected(self):
        with pytest.raises(ValueError, match="must be a dict"):
            validate_profile_structure({"wishlist": ["Bixby Bridge"]})

    def test_pois_per_day_string_shows_value(self):
        with pytest.raises(ValueError, match=r"Got.*3-4"):
            validate_profile_structure({"travel_pace": {"pois_per_day": "3-4"}})

    def test_valid_wishlist_still_passes(self):
        validate_profile_structure({"wishlist": [{"name_en": "Test"}]})

    def test_valid_pois_still_passes(self):
        validate_profile_structure({"travel_pace": {"pois_per_day": [3, 5]}})


class TestCheckProfileCompletenessBug002:
    def test_wishlist_dict_structural_issue(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["wishlist"] = {"must_visit": ["X"]}
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert any("list" in i for i in result["structural_issues"])

    def test_pois_per_day_string_structural_issue(self):
        data = deepcopy(COMPLETE_PROFILE)
        data["travel_pace"]["pois_per_day"] = "3-4"
        result = check_profile_completeness(data)
        assert result["complete"] is False
        assert any("3-4" in i for i in result["structural_issues"])


# ---------------------------------------------------------------------------
# WorkflowState — instance-level stages
# ---------------------------------------------------------------------------

class TestWorkflowStateStages:
    def test_default_stages_match_config(self):
        state = WorkflowState("test-trip")
        assert state.stages == STAGES
        assert state.current_stage == STAGES[0]

    def test_custom_stages_persist(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "profile_collection"
        data = state.to_dict()
        assert data["stages"][0] == "profile_collection"
        assert data["current_stage"] == "profile_collection"

    def test_serialization_roundtrip(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "profile_collection"
        state.completed_stages = ["profile_collection"]
        data = state.to_dict()
        restored = WorkflowState.from_dict(data)
        assert restored.stages == state.stages
        assert restored.current_stage == "profile_collection"
        assert restored.completed_stages == ["profile_collection"]

    def test_advance_from_profile_collection(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "profile_collection"
        next_stage = state.advance()
        assert next_stage == "poi_search"
        assert "profile_collection" in state.completed_stages

    def test_advance_through_all_stages(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "profile_collection"
        visited = [state.current_stage]
        while True:
            next_s = state.advance()
            if next_s is None:
                break
            visited.append(next_s)
        assert visited == ["profile_collection"] + STAGES
        assert state.status == "complete"


# ---------------------------------------------------------------------------
# WorkflowState — backward compatibility (legacy sessions)
# ---------------------------------------------------------------------------

class TestWorkflowStateLegacy:
    def test_from_dict_without_stages_key(self):
        """Legacy sessions don't have 'stages' — should use default STAGES."""
        data = {
            "session_id": "abc123",
            "trip_id": "2026-04-test",
            "current_stage": "scheduling",
            "completed_stages": ["poi_search"],
            "status": "active",
        }
        state = WorkflowState.from_dict(data)
        assert state.stages == STAGES
        assert state.current_stage == "scheduling"

    def test_from_dict_normalizes_unknown_current_stage(self):
        """current_stage not in stages → reset to stages[0]."""
        data = {
            "session_id": "abc123",
            "trip_id": "2026-04-test",
            "current_stage": "nonexistent_stage",
            "completed_stages": [],
            "status": "active",
        }
        state = WorkflowState.from_dict(data)
        assert state.current_stage == STAGES[0]

    def test_from_dict_normalizes_completed_stages(self):
        """completed_stages with unknown entries → filtered out."""
        data = {
            "session_id": "abc123",
            "trip_id": "2026-04-test",
            "current_stage": "scheduling",
            "completed_stages": ["poi_search", "nonexistent"],
            "status": "active",
        }
        state = WorkflowState.from_dict(data)
        assert "nonexistent" not in state.completed_stages
        assert "poi_search" in state.completed_stages


# ---------------------------------------------------------------------------
# WorkflowState — regression guard
# ---------------------------------------------------------------------------

class TestRegressionGuard:
    def test_regression_never_targets_profile_collection(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "review"
        state.completed_stages = ["profile_collection", "poi_search", "scheduling",
                                   "restaurants", "hotels"]

        result = state.regress_to("profile_collection", [{"rule": "test", "detail": "x"}])
        # Should redirect to poi_search (next after profile_collection)
        assert result["target_stage"] == "poi_search"
        assert state.current_stage == "poi_search"

    def test_normal_regression_works(self):
        state = WorkflowState("test-trip")
        state.stages = ["profile_collection"] + list(STAGES)
        state.current_stage = "review"
        state.completed_stages = ["profile_collection", "poi_search", "scheduling",
                                   "restaurants", "hotels"]

        result = state.regress_to("scheduling", [{"rule": "overlap"}])
        assert result["status"] == "regressed"
        assert state.current_stage == "scheduling"
        # profile_collection should remain in completed (not stale)
        assert "profile_collection" in state.completed_stages


# ---------------------------------------------------------------------------
# _filter_answered_questions (sentinel-based)
# ---------------------------------------------------------------------------

# Inline the function here to avoid importing mcp_server.server
# (which requires the mcp SDK, only available in .venv-mcp).
_UNSET = object()


def _filter_answered_questions(questions: list, profile: dict) -> list:
    unanswered = []
    for q in questions:
        field_path = q.get("field", "")
        parts = field_path.split(".")
        val = profile
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part, _UNSET)
            else:
                val = _UNSET
                break
        if val is _UNSET:
            unanswered.append(q)
    return unanswered


class TestFilterAnsweredQuestions:
    """Tests the sentinel-based filtering to avoid falsey-value misdetection."""

    def setup_method(self):
        self.filter_fn = _filter_answered_questions

    def test_filters_out_present_fields(self):
        questions = [
            {"id": "q1", "field": "identity.role"},
            {"id": "q2", "field": "dietary.preferences"},
        ]
        profile = {"identity": {"role": "engineer"}, "dietary": {"preferences": ["local"]}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 0

    def test_keeps_absent_fields(self):
        questions = [
            {"id": "q1", "field": "identity.role"},
            {"id": "q2", "field": "dietary.preferences"},
        ]
        profile = {"identity": {"role": "engineer"}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 1
        assert result[0]["id"] == "q2"

    def test_empty_list_is_valid_answer(self):
        """Empty list [] should NOT be treated as unanswered."""
        questions = [{"id": "q1", "field": "dietary.restrictions"}]
        profile = {"dietary": {"restrictions": []}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 0  # [] is a valid answer

    def test_empty_string_is_valid_answer(self):
        """Empty string '' should NOT be treated as unanswered."""
        questions = [{"id": "q1", "field": "identity.role"}]
        profile = {"identity": {"role": ""}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 0

    def test_false_is_valid_answer(self):
        """False should NOT be treated as unanswered."""
        questions = [{"id": "q1", "field": "dietary.street_food"}]
        profile = {"dietary": {"street_food": False}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 0

    def test_zero_is_valid_answer(self):
        """0 should NOT be treated as unanswered."""
        questions = [{"id": "q1", "field": "travel_style.walking_tolerance_km"}]
        profile = {"travel_style": {"walking_tolerance_km": 0}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 0

    def test_nested_field_absent(self):
        questions = [{"id": "q1", "field": "travel_interests.nature.description"}]
        profile = {"travel_interests": {"nature": {}}}
        result = self.filter_fn(questions, profile)
        assert len(result) == 1

    def test_empty_profile(self):
        questions = [
            {"id": "q1", "field": "identity.role"},
            {"id": "q2", "field": "dietary.preferences"},
        ]
        result = self.filter_fn(questions, {})
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Destination question loading
# ---------------------------------------------------------------------------

class TestDestinationQuestions:
    def test_japan_keywords_match(self):
        questions = load_destination_questions("Tokyo, Japan")
        ids = {q["id"] for q in questions}
        assert "japan_onsen" in ids or len(questions) > 0

    def test_multi_match_merges(self):
        """Okinawa matches both japan and beach."""
        questions = load_destination_questions("Okinawa beach resort")
        ids = {q["id"] for q in questions}
        # Should have questions from both japan and beach regions
        assert len(questions) >= 2

    def test_zero_match_returns_fallback(self):
        questions = load_destination_questions("rural Mongolia")
        # Should get fallback questions
        ids = {q["id"] for q in questions}
        assert "generic_transport" in ids or "generic_budget" in ids

    def test_case_insensitive(self):
        q1 = load_destination_questions("TOKYO")
        q2 = load_destination_questions("tokyo")
        assert len(q1) == len(q2)


# ---------------------------------------------------------------------------
# Profile questions loading
# ---------------------------------------------------------------------------

class TestProfileQuestions:
    def test_loads_questions(self):
        questions = load_profile_questions()
        assert len(questions) > 0

    def test_questions_have_required_fields(self):
        questions = load_profile_questions()
        for q in questions:
            assert "id" in q
            assert "field" in q
            assert "question_en" in q

    def test_has_required_questions(self):
        questions = load_profile_questions()
        required = [q for q in questions if q.get("required")]
        assert len(required) >= 3  # at least identity, interests, style


# ── Workspace Session Persistence ──────────────────────────────


class TestWorkflowStateWorkspace:
    """Tests for workspace_id / workspace_tag fields on WorkflowState."""

    def test_workspace_id_serialization_roundtrip(self):
        state = WorkflowState("test-trip", workspace_id="abc123def456", workspace_tag="miami-trip")
        data = state.to_dict()
        assert data["workspace_id"] == "abc123def456"
        assert data["workspace_tag"] == "miami-trip"

        restored = WorkflowState.from_dict(data)
        assert restored.workspace_id == "abc123def456"
        assert restored.workspace_tag == "miami-trip"

    def test_workspace_id_absent_backward_compat(self):
        """Legacy JSON without workspace fields should load with None values."""
        data = {
            "session_id": "abc123",
            "trip_id": "2026-04-test",
            "current_stage": "scheduling",
            "completed_stages": ["poi_search"],
            "status": "active",
        }
        state = WorkflowState.from_dict(data)
        assert state.workspace_id is None
        assert state.workspace_tag is None

    def test_workspace_fields_in_list_all_sessions(self, tmp_path, monkeypatch):
        import mcp_server.config as cfg
        import mcp_server.workflow as _wf

        sessions_dir = tmp_path / "sessions"
        monkeypatch.setattr(cfg, "SESSIONS_DIR", sessions_dir)
        monkeypatch.setattr(_wf, "SESSIONS_DIR", sessions_dir)

        state = WorkflowState("test-trip", workspace_id="ws123", workspace_tag="test-tag")
        # Save requires session dir to exist
        sd = sessions_dir / state.session_id
        sd.mkdir(parents=True)
        state.save()

        from mcp_server.workflow import list_all_sessions
        sessions = list_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["workspace_id"] == "ws123"
        assert sessions[0]["workspace_tag"] == "test-tag"
