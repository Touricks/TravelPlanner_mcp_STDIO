"""Integration tests for CSV import pipeline."""

import pytest

import import_csv
from import_csv import import_csv as run_import


@pytest.fixture
def csv_file(tmp_path):
    """Minimal 3-row CSV matching the expected Notion export format."""
    content = (
        "Name,Address,Chinese Name,City,Day,Description,Duration,Group,"
        "Notes,Status,Style,Time,Type,Visited,userDefined:URL\n"
        'Golden Gate Bridge,"Conzelman Rd, Sausalito, CA 94965",'
        "金门大桥,San Francisco,Day 1,Iconic bridge,1h,San Francisco,"
        "Great view,pending,nature,18:30-19:30,Attractions,No,"
        '"https://maps.google.com/?q=Conzelman+Rd"\n'
        'Blue Bottle Coffee,"1 Ferry Building, SF, CA 94111",'
        "蓝瓶咖啡,San Francisco,Day 1,Good coffee,30min,San Francisco,"
        ",pending,food,17:00-17:30,Food,No,"
        '"https://maps.google.com/?q=1+Ferry+Building"\n'
        'Stanford University,"450 Serra Mall, Stanford, CA 94305",'
        "斯坦福大学,Stanford,Day 2,Campus tour,1.5h,Highway 1 North,"
        ",pending,tech,12:00-13:30,Attractions,No,"
        '"https://maps.google.com/?q=450+Serra+Mall"\n'
    )
    p = tmp_path / "test.csv"
    p.write_text(content, encoding="utf-8-sig")
    return p


@pytest.fixture
def yaml_file(tmp_path):
    """Minimal pois.yaml for source attribution.

    The load_yaml_sources() parser looks for lines starting with 'name_en:'
    and 'source:' (after strip). The real file uses '    name_en:' indentation.
    """
    content = (
        "  - id: 1\n"
        "    name_en: Golden Gate Bridge\n"
        "    source: tripmate\n"
        "  - id: 2\n"
        "    name_en: Blue Bottle Coffee\n"
        "    source: teammate\n"
    )
    p = tmp_path / "pois.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def patched_import(empty_db, csv_file, yaml_file, monkeypatch):
    """Run import_csv with patched paths and return the connection."""
    monkeypatch.setattr(import_csv, "CSV_PATH", csv_file)
    monkeypatch.setattr(import_csv, "POIS_YAML_PATH", yaml_file)
    run_import(empty_db)
    return empty_db


class TestImportCSV:
    def test_row_counts(self, patched_import):
        conn = patched_import
        assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM places").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM itinerary_items").fetchone()[0] == 3

    def test_coffee_detection(self, patched_import):
        conn = patched_import
        style = conn.execute(
            "SELECT style FROM places WHERE name_en='Blue Bottle Coffee'"
        ).fetchone()[0]
        assert style == "coffee"

    def test_date_conversion(self, patched_import):
        conn = patched_import
        dates = dict(
            conn.execute(
                "SELECT p.name_en, ii.date "
                "FROM itinerary_items ii JOIN places p ON ii.place_id = p.id"
            ).fetchall()
        )
        assert dates["Golden Gate Bridge"] == "2026-04-17"
        assert dates["Stanford University"] == "2026-04-18"

    def test_time_parsing(self, patched_import):
        conn = patched_import
        row = conn.execute(
            "SELECT ii.time_start, ii.time_end "
            "FROM itinerary_items ii JOIN places p ON ii.place_id = p.id "
            "WHERE p.name_en = 'Golden Gate Bridge'"
        ).fetchone()
        assert row == ("18:30", "19:30")

    def test_duration_parsing(self, patched_import):
        conn = patched_import
        durations = dict(
            conn.execute(
                "SELECT p.name_en, ii.duration_minutes "
                "FROM itinerary_items ii JOIN places p ON ii.place_id = p.id"
            ).fetchall()
        )
        assert durations["Golden Gate Bridge"] == 60
        assert durations["Blue Bottle Coffee"] == 30
        assert durations["Stanford University"] == 90

    def test_source_attribution(self, patched_import):
        conn = patched_import
        sources = dict(
            conn.execute("SELECT name_en, source FROM places").fetchall()
        )
        assert sources["Golden Gate Bridge"] == "tripmate"
        assert sources["Blue Bottle Coffee"] == "teammate"
        assert sources["Stanford University"] == "agent"

    def test_sort_order_chronological(self, patched_import):
        conn = patched_import
        orders = conn.execute(
            "SELECT p.name_en, ii.sort_order "
            "FROM itinerary_items ii JOIN places p ON ii.place_id = p.id "
            "ORDER BY ii.sort_order"
        ).fetchall()
        names = [r[0] for r in orders]
        # Day 1 17:00 (Blue Bottle) < Day 1 18:30 (Golden Gate) < Day 2 12:00 (Stanford)
        assert names.index("Blue Bottle Coffee") < names.index("Golden Gate Bridge")
        assert names.index("Golden Gate Bridge") < names.index("Stanford University")
