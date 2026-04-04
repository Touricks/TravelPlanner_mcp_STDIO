"""Unit tests for pure parser functions — zero DB dependency."""

from import_csv import (
    parse_duration,
    day_label_to_date,
    parse_time_range,
    detect_style,
    compute_sort_order,
)
from import_md import parse_md_table, find_table_after, parse_cost


# ── parse_duration ──────────────────────────────────────────


class TestParseDuration:
    def test_whole_hours(self):
        assert parse_duration("2h") == 120

    def test_fractional_hours(self):
        assert parse_duration("1.5h") == 90

    def test_minutes(self):
        assert parse_duration("30min") == 30

    def test_45_minutes(self):
        assert parse_duration("45min") == 45

    def test_none_returns_none(self):
        assert parse_duration(None) is None

    def test_empty_returns_none(self):
        assert parse_duration("") is None

    def test_whitespace_stripped(self):
        assert parse_duration("  1.5h  ") == 90

    def test_unrecognized_unit_returns_none(self):
        """Documents: only 'h' and 'min' suffixes are supported."""
        assert parse_duration("45s") is None
        assert parse_duration("2 hours") is None


# ── day_label_to_date ───────────────────────────────────────


class TestDayLabelToDate:
    def test_day_1(self):
        assert day_label_to_date("Day 1") == "2026-04-17"

    def test_day_2(self):
        assert day_label_to_date("Day 2") == "2026-04-18"

    def test_day_9(self):
        assert day_label_to_date("Day 9") == "2026-04-25"


# ── parse_time_range ────────────────────────────────────────


class TestParseTimeRange:
    def test_normal(self):
        assert parse_time_range("18:30-19:30") == ("18:30", "19:30")

    def test_with_spaces(self):
        assert parse_time_range(" 09:00 - 10:00 ") == ("09:00", "10:00")

    def test_empty_returns_none_tuple(self):
        assert parse_time_range("") == (None, None)

    def test_none_returns_none_tuple(self):
        assert parse_time_range(None) == (None, None)

    def test_no_dash_returns_none_tuple(self):
        assert parse_time_range("18:30") == (None, None)


# ── detect_style ────────────────────────────────────────────


class TestDetectStyle:
    def test_coffee_keyword(self):
        assert detect_style("Blue Bottle Coffee (SF)", "food") == "coffee"

    def test_bakery_coffee(self):
        assert detect_style("Big Sur Bakery & Coffee", "food") == "coffee"

    def test_verve(self):
        assert detect_style("Verve Coffee (Santa Cruz)", "food") == "coffee"

    def test_passthrough_nature(self):
        assert detect_style("Golden Gate Bridge", "nature") == "nature"

    def test_passthrough_tech(self):
        assert detect_style("Stanford University", "tech") == "tech"

    def test_case_insensitive(self):
        assert detect_style("BLUE BOTTLE something", "food") == "coffee"

    def test_non_coffee_food(self):
        """Regular restaurant stays as 'food'."""
        assert detect_style("Z & Y Restaurant", "food") == "food"


# ── compute_sort_order ──────────────────────────────────────


class TestComputeSortOrder:
    def test_with_time(self):
        # Day 1 at 18:30 → 1000 + 18*60 + 30 = 2110.0
        assert compute_sort_order(1, "18:30") == 2110.0

    def test_no_time(self):
        assert compute_sort_order(3, None) == 3000.0

    def test_earlier_sorts_first_within_day(self):
        assert compute_sort_order(1, "09:00") < compute_sort_order(1, "18:30")

    def test_cross_day_ordering(self):
        assert compute_sort_order(1, "23:00") < compute_sort_order(2, "08:00")


# ── parse_cost ──────────────────────────────────────────────


class TestParseCost:
    def test_dollar_amount(self):
        assert parse_cost("$59.95/adult") == 59.95

    def test_free(self):
        assert parse_cost("Free") == 0.0

    def test_free_case_insensitive(self):
        assert parse_cost("free") == 0.0
        assert parse_cost("FREE") == 0.0

    def test_vehicle_cost(self):
        assert parse_cost("$35/vehicle") == 35.0

    def test_none(self):
        assert parse_cost(None) == 0.0

    def test_empty(self):
        assert parse_cost("") == 0.0

    def test_no_match_returns_none(self):
        assert parse_cost("TBD") is None

    def test_free_with_parking_note(self):
        assert parse_cost("Free (parking $10/hr)") == 0.0


# ── parse_md_table ──────────────────────────────────────────


class TestParseMdTable:
    def test_normal_table(self):
        lines = [
            "| **Risk** | **Detail** |",
            "| --- | --- |",
            "| Tire chains | Required in winter |",
            "| Vehicle size | Max 22ft |",
        ]
        result = parse_md_table(lines)
        assert len(result) == 2
        assert result[0]["Risk"] == "Tire chains"
        assert result[1]["Detail"] == "Max 22ft"

    def test_strips_bold_headers(self):
        lines = [
            "| **Name** | **Cost** |",
            "| --- | --- |",
            "| Aquarium | $59.95 |",
        ]
        result = parse_md_table(lines)
        assert "Name" in result[0]

    def test_too_few_lines(self):
        assert parse_md_table(["| A |", "| --- |"]) == []

    def test_stops_at_non_pipe(self):
        lines = [
            "| **A** |",
            "| --- |",
            "| val1 |",
            "Some other text",
            "| val2 |",
        ]
        result = parse_md_table(lines)
        assert len(result) == 1

    def test_column_mismatch_skipped(self):
        lines = [
            "| **A** | **B** |",
            "| --- | --- |",
            "| only_one |",
            "| x | y |",
        ]
        result = parse_md_table(lines)
        assert len(result) == 1
        assert result[0]["A"] == "x"


# ── find_table_after ────────────────────────────────────────


class TestFindTableAfter:
    def test_basic(self):
        content = (
            "### Sequoia National Park\n"
            "| **Risk** | **Detail** |\n"
            "| --- | --- |\n"
            "| Tire chains | Required |\n"
        )
        result = find_table_after(content, "Sequoia National Park")
        assert len(result) == 1
        assert result[0]["Risk"] == "Tire chains"

    def test_with_gap_between_heading_and_table(self):
        content = (
            "### My Section\n"
            "Some intro text here.\n"
            "| **A** |\n"
            "| --- |\n"
            "| val |\n"
        )
        result = find_table_after(content, "My Section")
        assert len(result) == 1

    def test_stops_at_next_heading(self):
        content = (
            "### Section A\n"
            "No table here.\n"
            "### Section B\n"
            "| **A** |\n"
            "| --- |\n"
            "| val |\n"
        )
        result = find_table_after(content, "Section A")
        assert result == []

    def test_heading_not_found(self):
        assert find_table_after("no headings here", "Missing") == []

    def test_only_matches_heading_lines(self):
        """Regression test: body text containing heading keywords should not match."""
        content = (
            "- Highway 1 Big Sur has landslide history\n"
            "### Sequoia National Park\n"
            "| **Risk** | **Detail** |\n"
            "| --- | --- |\n"
            "| Chains | Required |\n"
            "### Highway 1 Big Sur -- Road Status\n"
            "| **Risk** | **Detail** |\n"
            "| --- | --- |\n"
            "| Landslide | Check Caltrans |\n"
        )
        # "Highway 1 Big Sur" appears in body text first, but should only match heading
        result = find_table_after(content, "Highway 1 Big Sur")
        assert len(result) == 1
        assert result[0]["Risk"] == "Landslide"
