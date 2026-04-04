from __future__ import annotations


def build_verification_prompt(notion_url: str, expected_databases: int = 4) -> str:
    return (
        f"Verify the Notion travel plan page at: {notion_url}\n\n"
        f"Expected: {expected_databases} databases (Itinerary, Restaurants, Hotels, Notices).\n\n"
        "Steps:\n"
        "1. Navigate to the Notion page URL\n"
        "2. Wait for the page to fully render\n"
        "3. Take a screenshot of the top section\n"
        "4. Scroll down and take screenshots of each database\n"
        "5. Count the visible entries in each database\n"
        "6. Report any issues: empty databases, broken layouts, missing sections\n\n"
        "Save all screenshots and provide a summary of what you found."
    )
