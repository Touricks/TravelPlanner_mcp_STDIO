"""Canned JSON artifacts for MCP E2E tests.

All fixtures pass their respective JSON Schema contracts.
"""
from __future__ import annotations

import json
from pathlib import Path

from tripdb.bridge import candidate_id

_DIR = Path(__file__).resolve().parent

# ── Miami fixtures (loaded from JSON) ────────────────────

MIAMI_POI_CANDIDATES = json.loads((_DIR / "miami_poi_candidates.json").read_text())
MIAMI_ITINERARY = json.loads((_DIR / "miami_itinerary.json").read_text())
MIAMI_RESTAURANTS = json.loads((_DIR / "miami_restaurants.json").read_text())
MIAMI_HOTELS = json.loads((_DIR / "miami_hotels.json").read_text())

# ── POI Candidates (5 POIs) ───────────────────────────────

SAMPLE_POI_CANDIDATES = {
    "destination": "San Francisco",
    "candidates": [
        {
            "candidate_id": candidate_id("Golden Gate Bridge", "Golden Gate Bridge, SF, CA"),
            "name_en": "Golden Gate Bridge",
            "name_cn": "金门大桥",
            "style": "landmark",
            "address": "Golden Gate Bridge, SF, CA",
            "city": "San Francisco",
            "duration_minutes": 60,
            "description": "Iconic suspension bridge",
        },
        {
            "candidate_id": candidate_id("Fisherman's Wharf", "Pier 39, SF, CA"),
            "name_en": "Fisherman's Wharf",
            "name_cn": "渔人码头",
            "style": "landmark",
            "address": "Pier 39, SF, CA",
            "city": "San Francisco",
            "duration_minutes": 90,
            "description": "Waterfront district",
        },
        {
            "candidate_id": candidate_id("Chinatown", "Grant Ave, SF, CA"),
            "name_en": "Chinatown",
            "name_cn": "唐人街",
            "style": "culture",
            "address": "Grant Ave, SF, CA",
            "city": "San Francisco",
            "duration_minutes": 120,
            "description": "Historic neighborhood",
        },
        {
            "candidate_id": candidate_id("Muir Woods", "1 Muir Woods Rd, Mill Valley, CA"),
            "name_en": "Muir Woods",
            "name_cn": "缪尔森林",
            "style": "nature",
            "address": "1 Muir Woods Rd, Mill Valley, CA",
            "city": "Mill Valley",
            "duration_minutes": 150,
            "description": "Old-growth redwood forest",
        },
        {
            "candidate_id": candidate_id("Tartine Bakery", "600 Guerrero St, SF, CA"),
            "name_en": "Tartine Bakery",
            "name_cn": "塔丁面包店",
            "style": "food",
            "address": "600 Guerrero St, SF, CA",
            "city": "San Francisco",
            "duration_minutes": 45,
            "description": "Famous bakery and cafe",
        },
    ],
}

# ── Itinerary (2 days, 5 items) ──────────────────────────

_ggb_cid = candidate_id("Golden Gate Bridge", "Golden Gate Bridge, SF, CA")
_fw_cid = candidate_id("Fisherman's Wharf", "Pier 39, SF, CA")
_ct_cid = candidate_id("Chinatown", "Grant Ave, SF, CA")
_mw_cid = candidate_id("Muir Woods", "1 Muir Woods Rd, Mill Valley, CA")
_tb_cid = candidate_id("Tartine Bakery", "600 Guerrero St, SF, CA")

SAMPLE_ITINERARY = {
    "trip_id": "2026-04-san-francisco",
    "start_date": "2026-04-17",
    "end_date": "2026-04-25",
    "days": [
        {
            "day_num": 1,
            "date": "2026-04-17",
            "region": "San Francisco",
            "items": [
                {
                    "candidate_id": _ggb_cid,
                    "name_en": "Golden Gate Bridge",
                    "style": "landmark",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "duration_minutes": 60,
                },
                {
                    "candidate_id": _fw_cid,
                    "name_en": "Fisherman's Wharf",
                    "style": "landmark",
                    "start_time": "11:00",
                    "end_time": "12:30",
                    "duration_minutes": 90,
                },
                {
                    "candidate_id": _ct_cid,
                    "name_en": "Chinatown",
                    "style": "culture",
                    "start_time": "14:00",
                    "end_time": "15:30",
                    "duration_minutes": 90,
                },
            ],
        },
        {
            "day_num": 2,
            "date": "2026-04-18",
            "region": "Marin County",
            "items": [
                {
                    "candidate_id": _mw_cid,
                    "name_en": "Muir Woods",
                    "style": "nature",
                    "start_time": "08:00",
                    "end_time": "10:30",
                    "duration_minutes": 150,
                },
                {
                    "candidate_id": _tb_cid,
                    "name_en": "Tartine Bakery",
                    "style": "food",
                    "start_time": "12:00",
                    "end_time": "12:45",
                    "duration_minutes": 45,
                },
            ],
        },
    ],
}

# ── Restaurants (4 meals: lunch + dinner x 2 days) ───────

SAMPLE_RESTAURANTS = {
    "trip_id": "2026-04-san-francisco",
    "recommendations": [
        {
            "day_num": 1,
            "meal_type": "lunch",
            "name_en": "Hog Island Oyster Co",
            "cuisine": "Seafood",
            "address": "1 Ferry Building, SF, CA",
            "near_poi": "Fisherman's Wharf",
        },
        {
            "day_num": 1,
            "meal_type": "dinner",
            "name_en": "China Live",
            "cuisine": "Chinese",
            "address": "644 Broadway, SF, CA",
            "near_poi": "Chinatown",
        },
        {
            "day_num": 2,
            "meal_type": "lunch",
            "name_en": "Sol Food",
            "cuisine": "Puerto Rican",
            "address": "901 Lincoln Ave, San Rafael, CA",
            "near_poi": "Muir Woods",
        },
        {
            "day_num": 2,
            "meal_type": "dinner",
            "name_en": "Burma Superstar",
            "cuisine": "Burmese",
            "address": "309 Clement St, SF, CA",
            "near_poi": "Muir Woods",
        },
    ],
}

# ── Hotels (2 stays) ─────────────────────────────────────

SAMPLE_HOTELS = {
    "trip_id": "2026-04-san-francisco",
    "recommendations": [
        {
            "name": "Hotel Vitale",
            "address": "8 Mission St, SF, CA",
            "city": "San Francisco",
            "check_in": "2026-04-17",
            "check_out": "2026-04-19",
        },
        {
            "name": "Cavallo Point Lodge",
            "address": "601 Murray Circle, Sausalito, CA",
            "city": "Sausalito",
            "check_in": "2026-04-19",
            "check_out": "2026-04-20",
        },
    ],
}

# ── Complete profile (passes completeness check) ─────────

COMPLETE_PROFILE_YAML = """\
identity:
  name: Test User
  languages:
    - English
    - Chinese
travel_interests:
  styles:
    - nature
    - culture
    - food
travel_style:
  pace: moderate
  budget_tier: moderate
travel_pace:
  pois_per_day: [3, 5]
"""
