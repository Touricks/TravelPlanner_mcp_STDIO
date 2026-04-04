#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.prompt_loader import load_prompt


def _extract_last_json_array(text: str) -> list[dict]:
    """codex exec duplicates output with metadata — grab the last valid JSON array."""
    for match in reversed(re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', text)):
        try:
            parsed = json.loads(match)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            continue
    return []


def run_codex_review(itinerary: dict, restaurants: dict, hotels: dict) -> list[dict]:
    prompt = load_prompt("codex-review", {
        "itinerary": json.dumps(itinerary, indent=2, ensure_ascii=False),
        "restaurants": json.dumps(restaurants, indent=2, ensure_ascii=False),
        "hotels": json.dumps(hotels, indent=2, ensure_ascii=False),
    })
    try:
        result = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", prompt],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _extract_last_json_array(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return []


def main():
    if len(sys.argv) < 4:
        print("Usage: codex_review.py <itinerary.json> <restaurants.json> <hotels.json>", file=sys.stderr)
        sys.exit(2)

    itinerary = json.loads(Path(sys.argv[1]).read_text())
    restaurants = json.loads(Path(sys.argv[2]).read_text())
    hotels = json.loads(Path(sys.argv[3]).read_text())

    items = run_codex_review(itinerary, restaurants, hotels)

    report = {
        "source": "codex",
        "items": [
            {
                "ref": it.get("ref", "unknown"),
                "source": "codex",
                "verdict": it.get("verdict", "flag"),
                "reason": it.get("reason", ""),
                "suggestion": it.get("suggestion", ""),
            }
            for it in items
        ],
    }
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
