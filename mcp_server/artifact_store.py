from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mcp_server.config import ARTIFACT_NAMES, atomic_write_json, session_dir


def artifact_path(session_id: str, name: str) -> Path:
    return session_dir(session_id) / f"{name}.json"


def save_artifact(session_id: str, stage: str, data: Any) -> Path:
    name = ARTIFACT_NAMES.get(stage, stage)
    path = artifact_path(session_id, name)
    atomic_write_json(path, data)
    return path


def load_artifact(session_id: str, name: str) -> Optional[dict]:
    path = artifact_path(session_id, name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def list_artifacts(session_id: str) -> list[str]:
    d = session_dir(session_id)
    try:
        return [
            p.stem
            for p in sorted(d.glob("*.json"))
            if p.stem != "workflow-state"
        ]
    except FileNotFoundError:
        return []
