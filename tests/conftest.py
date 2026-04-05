from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"


@pytest.fixture(scope="session", autouse=True)
def cleanup_sessions_after_suite():
    """Remove test-created session directories after the full suite finishes."""
    before = set(SESSIONS_DIR.iterdir()) if SESSIONS_DIR.exists() else set()
    yield
    if not SESSIONS_DIR.exists():
        return
    for entry in SESSIONS_DIR.iterdir():
        if entry not in before:
            shutil.rmtree(entry, ignore_errors=True)
