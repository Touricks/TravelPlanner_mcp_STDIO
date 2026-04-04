from __future__ import annotations

import json
import subprocess
from pathlib import Path


def enrich_candidates(candidates_path: Path) -> dict:
    data = json.loads(candidates_path.read_text())
    prompt = _build_enrichment_prompt(data)

    try:
        result = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            import re
            for match in reversed(re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', result.stdout)):
                try:
                    corrections = json.loads(match)
                    if isinstance(corrections, list):
                        return _apply_corrections(data, corrections)
                except json.JSONDecodeError:
                    continue
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return data


def _build_enrichment_prompt(data: dict) -> str:
    names = [c.get("name_en", "") for c in data.get("candidates", [])[:20]]
    return (
        f"Verify the following POIs for a trip to {data.get('destination', 'unknown')}. "
        f"For each, confirm: 1) hours are current 2) address is correct 3) any closures. "
        f"POIs: {', '.join(names)}. "
        f"Return JSON array of objects with name_en, corrected_hours, corrected_address, "
        f"closure_note (null if open). Only include POIs needing correction."
    )


def _apply_corrections(data: dict, corrections: list) -> dict:
    correction_map = {c["name_en"]: c for c in corrections if "name_en" in c}
    for candidate in data.get("candidates", []):
        fix = correction_map.get(candidate.get("name_en"))
        if not fix:
            continue
        if fix.get("corrected_hours"):
            candidate["hours"] = fix["corrected_hours"]
        if fix.get("corrected_address"):
            candidate["address"] = fix["corrected_address"]
        if fix.get("closure_note"):
            candidate["notes"] = fix["closure_note"]
    return data
