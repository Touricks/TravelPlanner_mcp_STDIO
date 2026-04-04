from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp_server.config import (
    MAX_ATTEMPTS_PER_STAGE,
    MAX_REGRESSIONS_PER_TRIP,
    SESSION_TTL_HOURS,
    SESSIONS_DIR,
    STAGES,
    atomic_write_json,
    session_dir,
)

log = logging.getLogger(__name__)


class WorkflowState:
    """Manages workflow state machine with atomic persistence."""

    def __init__(
        self,
        trip_id: str,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        workspace_tag: Optional[str] = None,
    ) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.trip_id = trip_id
        self.stages: list[str] = list(STAGES)
        self.current_stage: str = self.stages[0]
        self.completed_stages: list[str] = []
        self.attempt_counts: dict[str, int] = {}
        self.prior_errors: dict[str, list[dict]] = {}
        self.notion_urls: dict[str, str] = {}
        self.regression_count: int = 0
        self.status: str = "active"
        self.block_reason: Optional[str] = None
        self.workspace_id: Optional[str] = workspace_id
        self.workspace_tag: Optional[str] = workspace_tag
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at

    @property
    def state_path(self) -> Path:
        return session_dir(self.session_id) / "workflow-state.json"

    @property
    def published_databases(self) -> set[str]:
        return {k for k in self.notion_urls if k != "parent_page"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "trip_id": self.trip_id,
            "stages": self.stages,
            "current_stage": self.current_stage,
            "completed_stages": self.completed_stages,
            "attempt_counts": self.attempt_counts,
            "prior_errors": self.prior_errors,
            "notion_urls": self.notion_urls,
            "regression_count": self.regression_count,
            "status": self.status,
            "block_reason": self.block_reason,
            "workspace_id": self.workspace_id,
            "workspace_tag": self.workspace_tag,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        state = cls(data["trip_id"], data.get("session_id"))
        # Restore instance-level stages; fall back to default for legacy sessions
        state.stages = data.get("stages", list(STAGES))
        state.current_stage = data["current_stage"]
        state.completed_stages = data.get("completed_stages", [])
        state.attempt_counts = data.get("attempt_counts", {})
        state.prior_errors = data.get("prior_errors", {})
        state.notion_urls = data.get("notion_urls", {})
        state.regression_count = data.get("regression_count", 0)
        state.status = data.get("status", "active")
        state.block_reason = data.get("block_reason")
        state.workspace_id = data.get("workspace_id")
        state.workspace_tag = data.get("workspace_tag")
        state.created_at = data.get("created_at", "")
        state.updated_at = data.get("updated_at", "")

        # Normalization: ensure current_stage exists in stages
        if state.current_stage not in state.stages:
            original = state.current_stage
            state.current_stage = state.stages[0]
            log.warning(
                "Normalized current_stage for session %s: '%s' not in stages list, reset to '%s'",
                state.session_id, original, state.current_stage,
            )

        # Normalize completed_stages to only include known stages
        state.completed_stages = [s for s in state.completed_stages if s in state.stages]
        return state

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self.state_path, self.to_dict())

    @classmethod
    def load(cls, session_id: str) -> WorkflowState:
        """Load by session_id (primary) or trip_id (backward compat lookup)."""
        path = session_dir(session_id) / "workflow-state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except FileNotFoundError:
            pass

        resolved = _resolve_trip_id_to_session(session_id)
        if resolved:
            return cls.load(resolved)

        raise FileNotFoundError(f"No workflow state for session: {session_id}")

    def advance(self) -> Optional[str]:
        if self.current_stage not in self.stages:
            return None
        idx = self.stages.index(self.current_stage)
        if self.current_stage not in self.completed_stages:
            self.completed_stages.append(self.current_stage)
        if idx + 1 < len(self.stages):
            self.current_stage = self.stages[idx + 1]
            return self.current_stage
        self.status = "complete"
        return None

    def complete_stage(self, stage: str) -> None:
        self.current_stage = stage
        self.advance()
        self.save()

    def record_attempt(self, stage: str, errors: Optional[list[dict]] = None) -> int:
        count = self.attempt_counts.get(stage, 0) + 1
        self.attempt_counts[stage] = count
        if errors:
            self.prior_errors[stage] = errors
        return count

    def is_blocked(self, stage: str) -> bool:
        return self.attempt_counts.get(stage, 0) >= MAX_ATTEMPTS_PER_STAGE

    def regress_to(self, target_stage: str, violations: list[dict]) -> dict:
        if self.regression_count >= MAX_REGRESSIONS_PER_TRIP:
            self.block(f"Max regressions ({MAX_REGRESSIONS_PER_TRIP}) exceeded")
            return {"status": "blocked", "reason": self.block_reason}

        # profile_collection is never a regression target (no artifact)
        if target_stage == "profile_collection":
            target_stage = self.stages[self.stages.index("profile_collection") + 1] \
                if "profile_collection" in self.stages else self.stages[0]

        self.regression_count += 1
        target_idx = self.stages.index(target_stage)
        review_idx = self.stages.index("review")

        stale = self.stages[target_idx:review_idx]
        valid = [s for s in self.stages[:target_idx] if s in self.completed_stages]

        self.completed_stages = [s for s in self.completed_stages if s not in stale]
        self.attempt_counts[target_stage] = 0
        self.prior_errors[target_stage] = violations
        self.current_stage = target_stage
        self.save()

        return {
            "status": "regressed",
            "target_stage": target_stage,
            "violations": violations,
            "stale_artifacts": stale,
            "valid_artifacts": valid,
            "attempt_budget_reset": True,
            "remediation_hint": _build_remediation_hint(violations),
        }

    def block(self, reason: str) -> None:
        self.status = "blocked"
        self.block_reason = reason
        self.save()

    def unblock(self, action: str) -> None:
        if action == "retry":
            self.attempt_counts[self.current_stage] = 0
        elif action in ("skip", "override"):
            self.advance()
        self.status = "active"
        self.block_reason = None
        self.save()

    def cancel(self, reason: Optional[str] = None) -> None:
        self.status = "cancelled"
        self.block_reason = reason
        self.save()

    def record_notion_url(self, db_name: str, url: str) -> None:
        self.notion_urls[db_name] = url


def _resolve_trip_id_to_session(trip_id: str) -> Optional[str]:
    """Scan sessions/ to find a session with matching trip_id (backward compat)."""
    if not SESSIONS_DIR.exists():
        return None
    for d in SESSIONS_DIR.iterdir():
        state_file = d / "workflow-state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("trip_id") == trip_id:
                return data.get("session_id", d.name)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return None


def list_all_sessions() -> list[dict]:
    sessions = []
    try:
        entries = sorted(SESSIONS_DIR.iterdir())
    except FileNotFoundError:
        return sessions
    for d in entries:
        state_file = d / "workflow-state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            sessions.append({
                "session_id": data.get("session_id", d.name),
                "trip_id": data.get("trip_id"),
                "current_stage": data.get("current_stage"),
                "status": data.get("status", "unknown"),
                "workspace_id": data.get("workspace_id"),
                "workspace_tag": data.get("workspace_tag"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
            })
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return sessions


def cleanup_stale_sessions(max_age_hours: int = SESSION_TTL_HOURS) -> int:
    """Remove session directories older than max_age_hours that are not active/complete."""
    if not SESSIONS_DIR.exists():
        return 0
    now = datetime.now(timezone.utc)
    removed = 0
    for d in list(SESSIONS_DIR.iterdir()):
        state_file = d / "workflow-state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("status") in ("complete", "active"):
                continue
            updated = data.get("updated_at", "")
            if updated:
                age = now - datetime.fromisoformat(updated)
                if age.total_seconds() < max_age_hours * 3600:
                    continue
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        try:
            shutil.rmtree(d)
            removed += 1
            log.info("Cleaned up stale session: %s", d.name)
        except OSError:
            log.warning("Failed to clean up session: %s", d.name)
    return removed


def _build_remediation_hint(violations: list[dict]) -> str:
    if not violations:
        return "Review and fix the issues before resubmitting."
    rules = {v.get("rule", "unknown") for v in violations}
    items = [v.get("item", v.get("detail", ""))[:60] for v in violations[:3]]
    return (
        f"Fix {len(violations)} violation(s) ({', '.join(rules)}). "
        f"Affected: {'; '.join(items)}"
    )
