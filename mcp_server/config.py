from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

# Project root (PYTHONPATH must point here)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = PROJECT_ROOT / "assets"
CONFIGS_DIR = ASSETS_DIR / "configs"
CONTRACTS_DIR = CONFIGS_DIR / "contracts"
GUARDRAILS_PATH = CONFIGS_DIR / "guardrails.yaml"
DATA_DIR = ASSETS_DIR / "data"
PROMPTS_DIR = ASSETS_DIR / "prompts"
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"

# Standardized artifact names (agents must use these exact names)
ARTIFACT_NAMES = {
    "poi_search": "poi-candidates",
    "scheduling": "itinerary",
    "restaurants": "restaurants",
    "hotels": "hotels",
    "review": "review-report",
}

# Stage ordering
STAGES = [
    "poi_search",
    "scheduling",
    "restaurants",
    "hotels",
    "review",
    "notion",
    "verify",
]

# Stage → prompt template file mapping
STAGE_PROMPTS = {
    "poi_search": "stage-2-poi-search",
    "scheduling": "stage-3-scheduling",
    "restaurants": "stage-4a-restaurants",
    "hotels": "stage-4b-hotels",
    "notion": "stage-6-notion",
    "verify": "stage-7-verify",
}

MAX_ATTEMPTS_PER_STAGE = 3
MAX_REGRESSIONS_PER_TRIP = 2


def load_guardrails() -> dict:
    return yaml.safe_load(GUARDRAILS_PATH.read_text(encoding="utf-8"))


def load_contract(stage: str) -> dict:
    artifact_name = ARTIFACT_NAMES.get(stage, stage)
    path = CONTRACTS_DIR / f"{artifact_name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def trip_dir(trip_id: str) -> Path:
    return DATA_DIR / trip_id


# Stage → required input artifact names
STAGE_INPUT_ARTIFACTS: dict[str, list[str]] = {
    "scheduling": ["poi-candidates"],
    "restaurants": ["itinerary"],
    "hotels": ["itinerary"],
    "review": ["itinerary", "restaurants", "hotels"],
}


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON to path atomically via tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
