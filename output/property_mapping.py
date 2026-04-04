ITINERARY_PROPERTIES = {
    "Name": {"title": {}},
    "Chinese Name": {"rich_text": {}},
    "Day": {"select": {}},
    "Time": {"rich_text": {}},
    "Duration": {"rich_text": {}},
    "Style": {"select": {}},
    "Type": {"select": {}},
    "City": {"rich_text": {}},
    "Region": {"rich_text": {}},
    "Decision": {"select": {}},
    "Description": {"rich_text": {}},
}

RESTAURANT_PROPERTIES = {
    "Name": {"title": {}},
    "Chinese Name": {"rich_text": {}},
    "Day": {"select": {}},
    "Meal": {"select": {}},
    "Cuisine": {"rich_text": {}},
    "Price Tier": {"select": {}},
    "Near POI": {"rich_text": {}},
    "Address": {"rich_text": {}},
    "Reservation Required": {"checkbox": {}},
}

HOTEL_PROPERTIES = {
    "Name": {"title": {}},
    "Check In": {"rich_text": {}},
    "Check Out": {"rich_text": {}},
    "Nights": {"number": {}},
    "City": {"rich_text": {}},
    "Near Region": {"rich_text": {}},
    "Price Tier": {"select": {}},
    "Booking URL": {"url": {}},
}

NOTICES_PROPERTIES = {
    "Title": {"title": {}},
    "Source": {"select": {}},
    "Severity": {"select": {}},
    "Message": {"rich_text": {}},
    "Related Item": {"rich_text": {}},
}

STYLE_TO_TYPE = {
    "nature": "Attractions",
    "tech": "Attractions",
    "culture": "Attractions",
    "landmark": "Attractions",
    "food": "Food",
    "coffee": "Food",
}
