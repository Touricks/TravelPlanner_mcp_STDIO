from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Project root (PYTHONPATH must point here)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = PROJECT_ROOT / "assets"
CONFIGS_DIR = ASSETS_DIR / "configs"
CONTRACTS_DIR = CONFIGS_DIR / "contracts"
GUARDRAILS_PATH = CONFIGS_DIR / "guardrails.yaml"
DATA_DIR = ASSETS_DIR / "data"
PROMPTS_DIR = ASSETS_DIR / "prompts"
SESSIONS_DIR = PROJECT_ROOT / "sessions"
DB_PATH = PROJECT_ROOT / "tripdb" / "travel.db"
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
PROFILE_QUESTIONS_PATH = CONFIGS_DIR / "profile-questions.yaml"
DESTINATION_QUESTIONS_PATH = CONFIGS_DIR / "destination-questions.yaml"

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

# Stages that use server-side WebSearch (agent does NOT search)
SEARCH_STAGES = {"poi_search", "restaurants", "hotels"}

# Stage → prompt template file mapping
STAGE_PROMPTS = {
    "profile_collection": "stage-1-profile-collection",
    "poi_search": "stage-2-poi-search",
    "scheduling": "stage-3-scheduling",
    "restaurants": "stage-4a-restaurants",
    "hotels": "stage-4b-hotels",
    "notion": "stage-6-notion",
    "verify": "stage-7-verify",
}

# Stage → required input artifact names
STAGE_INPUT_ARTIFACTS: dict[str, list[str]] = {
    "scheduling": ["poi-candidates"],
    "restaurants": ["itinerary"],
    "hotels": ["itinerary"],
    "review": ["itinerary", "restaurants", "hotels"],
}

MAX_ATTEMPTS_PER_STAGE = 3
MAX_REGRESSIONS_PER_TRIP = 2
CODEX_SEARCH_TIMEOUT_SECONDS = 300
TRANSFORM_TIMEOUT_SECONDS = 60
SEARCH_TIMEOUT_SECONDS = 600  # deprecated alias — remove after callers migrate
SESSION_TTL_HOURS = 24


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
    """Legacy: assets/data/{trip_id}/ for pipeline/run.sh artifacts."""
    return DATA_DIR / trip_id


def session_dir(session_id: str) -> Path:
    """Session-scoped storage: sessions/{session_id}/"""
    return SESSIONS_DIR / session_id


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


# ---------------------------------------------------------------------------
# Profile question loaders
# ---------------------------------------------------------------------------


def load_profile_questions() -> list[dict]:
    """Load Layer 2 structured profile questions."""
    try:
        data = yaml.safe_load(PROFILE_QUESTIONS_PATH.read_text(encoding="utf-8"))
        return data.get("questions", [])
    except FileNotFoundError:
        return []


def load_destination_questions(destination: str) -> list[dict]:
    """Load Layer 3 destination-aware questions by keyword matching.

    Multi-match: if destination matches multiple regions, questions are merged
    (deduplicated by id). Zero matches: returns _fallback questions.
    """
    try:
        data = yaml.safe_load(DESTINATION_QUESTIONS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []

    dest_lower = destination.lower()
    matched: list[dict] = []
    seen_ids: set[str] = set()

    for region_id, region in data.get("regions", {}).items():
        keywords = region.get("keywords", [])
        if any(kw in dest_lower for kw in keywords):
            for q in region.get("questions", []):
                qid = q.get("id", "")
                if qid not in seen_ids:
                    matched.append(q)
                    seen_ids.add(qid)

    # Zero matches → use fallback
    if not matched:
        fallback = data.get("_fallback", {})
        matched = fallback.get("questions", [])

    return matched


# ---------------------------------------------------------------------------
# Claude CLI auto-detection
# ---------------------------------------------------------------------------

_claude_cli_path: str | None = None

CLAUDE_CLI_SEARCH_PATHS = [
    Path.home() / ".local" / "bin" / "claude",
    Path("/usr/local/bin/claude"),
    Path("/opt/homebrew/bin/claude"),
]


def find_claude_cli() -> str:
    """Auto-detect claude CLI binary. Cached after first call."""
    global _claude_cli_path
    if _claude_cli_path is not None:
        return _claude_cli_path

    # 1. Check PATH
    found = shutil.which("claude")
    if found:
        _claude_cli_path = found
        log.info("Found claude CLI on PATH: %s", found)
        return found

    # 2. Check common locations
    for p in CLAUDE_CLI_SEARCH_PATHS:
        if p.exists() and p.is_file():
            _claude_cli_path = str(p)
            log.info("Found claude CLI at: %s", p)
            return _claude_cli_path

    raise FileNotFoundError(
        "claude CLI not found. Checked PATH and: "
        + ", ".join(str(p) for p in CLAUDE_CLI_SEARCH_PATHS)
    )
