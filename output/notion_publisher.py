#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from output.property_mapping import (
    ITINERARY_PROPERTIES,
    RESTAURANT_PROPERTIES,
    HOTEL_PROPERTIES,
    NOTICES_PROPERTIES,
    STYLE_TO_TYPE,
)


def build_manifest(
    itinerary: dict,
    restaurants: dict,
    hotels: dict,
    review_report: dict,
) -> dict:
    trip_id = itinerary.get("trip_id", "unknown")
    title = f"Travel Plan: {trip_id}"

    itinerary_entries = []
    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            itinerary_entries.append({
                "Name": item.get("name_en", ""),
                "Chinese Name": item.get("name_cn", ""),
                "Day": f"Day {day['day_num']}",
                "Time": f"{item.get('start_time', '')}-{item.get('end_time', '')}",
                "Duration": f"{item.get('duration_minutes', 0)}min",
                "Style": item.get("style", ""),
                "Type": STYLE_TO_TYPE.get(item.get("style", ""), "Other"),
                "Region": item.get("region", day.get("region", "")),
                "Address": item.get("address", ""),
            })

    restaurant_entries = []
    for rec in restaurants.get("recommendations", []):
        restaurant_entries.append({
            "Name": rec.get("name_en", ""),
            "Chinese Name": rec.get("name_cn", ""),
            "Day": f"Day {rec.get('day_num', '?')}",
            "Meal": rec.get("meal_type", ""),
            "Cuisine": rec.get("cuisine", ""),
            "Price Tier": rec.get("price_tier", ""),
            "Near POI": rec.get("near_poi", ""),
            "Address": rec.get("address", ""),
            "Reservation Required": rec.get("reservation_required", False),
        })

    hotel_entries = []
    for rec in hotels.get("recommendations", []):
        hotel_entries.append({
            "Name": rec.get("name", ""),
            "Check In": rec.get("check_in", ""),
            "Check Out": rec.get("check_out", ""),
            "Nights": rec.get("nights", 1),
            "City": rec.get("city", ""),
            "Near Region": rec.get("near_region", ""),
            "Price Tier": rec.get("price_tier", ""),
            "Booking URL": rec.get("booking_url", ""),
        })

    notice_entries = []
    for item in review_report.get("items", []):
        if item.get("verdict") in ("flag", "reject"):
            notice_entries.append({
                "Title": item.get("reason", "")[:80],
                "Source": item.get("source", "unknown"),
                "Severity": "high" if item["verdict"] == "reject" else "medium",
                "Message": item.get("reason", ""),
                "Related Item": item.get("ref", ""),
            })

    return {
        "trip_id": trip_id,
        "title": title,
        "databases": {
            "itinerary": {
                "name": "Travel Itinerary",
                "properties": ITINERARY_PROPERTIES,
                "view": "board",
                "group_by": "Day",
                "entries": itinerary_entries,
            },
            "restaurants": {
                "name": "Restaurant Recommendations",
                "properties": RESTAURANT_PROPERTIES,
                "view": "table",
                "entries": restaurant_entries,
            },
            "hotels": {
                "name": "Hotel Recommendations",
                "properties": HOTEL_PROPERTIES,
                "view": "table",
                "entries": hotel_entries,
            },
            "notices": {
                "name": "Notices & Warnings",
                "properties": NOTICES_PROPERTIES,
                "view": "table",
                "entries": notice_entries,
            },
        },
    }


def main():
    if len(sys.argv) < 5:
        print(
            "Usage: notion_publisher.py <itinerary.json> <restaurants.json> "
            "<hotels.json> <review-report.json>",
            file=sys.stderr,
        )
        sys.exit(2)

    itinerary = json.loads(Path(sys.argv[1]).read_text())
    restaurants = json.loads(Path(sys.argv[2]).read_text())
    hotels = json.loads(Path(sys.argv[3]).read_text())
    review_report = json.loads(Path(sys.argv[4]).read_text())

    manifest = build_manifest(itinerary, restaurants, hotels, review_report)
    json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
