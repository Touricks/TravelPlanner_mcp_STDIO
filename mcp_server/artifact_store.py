from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mcp_server.config import ARTIFACT_NAMES, atomic_write_json, trip_dir


def artifact_path(trip_id: str, name: str) -> Path:
    return trip_dir(trip_id) / f"{name}.json"


def save_artifact(trip_id: str, stage: str, data: Any) -> Path:
    name = ARTIFACT_NAMES.get(stage, stage)
    path = artifact_path(trip_id, name)
    atomic_write_json(path, data)
    return path


def load_artifact(trip_id: str, name: str) -> Optional[dict]:
    path = artifact_path(trip_id, name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def list_artifacts(trip_id: str) -> list[str]:
    d = trip_dir(trip_id)
    try:
        return [
            p.stem
            for p in sorted(d.glob("*.json"))
            if p.stem != "workflow-state"
        ]
    except FileNotFoundError:
        return []
