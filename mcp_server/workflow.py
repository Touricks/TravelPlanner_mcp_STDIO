from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp_server.config import (
    MAX_ATTEMPTS_PER_STAGE,
    MAX_REGRESSIONS_PER_TRIP,
    STAGES,
    atomic_write_json,
    trip_dir,
)

log = logging.getLogger(__name__)


class WorkflowState:
    """Manages workflow state machine with atomic persistence."""

    def __init__(self, trip_id: str) -> None:
        self.trip_id = trip_id
        self.current_stage: str = STAGES[0]
        self.completed_stages: list[str] = []
        self.attempt_counts: dict[str, int] = {}
        self.prior_errors: dict[str, list[dict]] = {}
        self.notion_urls: dict[str, str] = {}
        self.regression_count: int = 0
        self.status: str = "active"  # active | blocked | complete | cancelled
        self.block_reason: Optional[str] = None
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at

    @property
    def state_path(self) -> Path:
        return trip_dir(self.trip_id) / "workflow-state.json"

    @property
    def published_databases(self) -> set[str]:
        return {k for k in self.notion_urls if k != "parent_page"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "current_stage": self.current_stage,
            "completed_stages": self.completed_stages,
            "attempt_counts": self.attempt_counts,
            "prior_errors": self.prior_errors,
            "notion_urls": self.notion_urls,
            "regression_count": self.regression_count,
            "status": self.status,
            "block_reason": self.block_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        state = cls(data["trip_id"])
        state.current_stage = data["current_stage"]
        state.completed_stages = data.get("completed_stages", [])
        state.attempt_counts = data.get("attempt_counts", {})
        state.prior_errors = data.get("prior_errors", {})
        state.notion_urls = data.get("notion_urls", {})
        state.regression_count = data.get("regression_count", 0)
        state.status = data.get("status", "active")
        state.block_reason = data.get("block_reason")
        state.created_at = data.get("created_at", "")
        state.updated_at = data.get("updated_at", "")
        return state

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self.state_path, self.to_dict())

    @classmethod
    def load(cls, trip_id: str) -> WorkflowState:
        path = trip_dir(trip_id) / "workflow-state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(f"No workflow state for trip: {trip_id}")
        return cls.from_dict(data)

    def advance(self) -> Optional[str]:
        """Advance to next stage. Returns new stage or None if complete."""
        if self.current_stage not in STAGES:
            return None
        idx = STAGES.index(self.current_stage)
        if self.current_stage not in self.completed_stages:
            self.completed_stages.append(self.current_stage)
        if idx + 1 < len(STAGES):
            self.current_stage = STAGES[idx + 1]
            return self.current_stage
        self.status = "complete"
        return None

    def complete_stage(self, stage: str) -> None:
        """Mark a stage as complete and advance. Use this instead of
        directly manipulating current_stage/completed_stages."""
        self.current_stage = stage
        self.advance()
        self.save()

    def record_attempt(self, stage: str, errors: Optional[list[dict]] = None) -> int:
        """Record an attempt. Returns current attempt count."""
        count = self.attempt_counts.get(stage, 0) + 1
        self.attempt_counts[stage] = count
        if errors:
            self.prior_errors[stage] = errors
        return count

    def is_blocked(self, stage: str) -> bool:
        return self.attempt_counts.get(stage, 0) >= MAX_ATTEMPTS_PER_STAGE

    def regress_to(self, target_stage: str, violations: list[dict]) -> dict:
        """Regress from REVIEW to an earlier stage. Returns remediation payload."""
        if self.regression_count >= MAX_REGRESSIONS_PER_TRIP:
            self.block(f"Max regressions ({MAX_REGRESSIONS_PER_TRIP}) exceeded")
            return {
                "status": "blocked",
                "reason": self.block_reason,
            }

        self.regression_count += 1
        target_idx = STAGES.index(target_stage)
        review_idx = STAGES.index("review")

        stale = STAGES[target_idx:review_idx]
        valid = [s for s in STAGES[:target_idx] if s in self.completed_stages]

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
        """Unblock a trip. action: retry | skip | override."""
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


def list_all_trips() -> list[dict]:
    """Scan assets/data/ for workflow-state.json files."""
    from mcp_server.config import DATA_DIR

    trips = []
    try:
        entries = sorted(DATA_DIR.iterdir())
    except FileNotFoundError:
        return trips
    for d in entries:
        state_file = d / "workflow-state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            trips.append({
                "trip_id": data.get("trip_id", d.name),
                "current_stage": data.get("current_stage"),
                "status": data.get("status", "unknown"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
            })
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return trips


def _build_remediation_hint(violations: list[dict]) -> str:
    if not violations:
        return "Review and fix the issues before resubmitting."
    rules = {v.get("rule", "unknown") for v in violations}
    items = [v.get("item", v.get("detail", ""))[:60] for v in violations[:3]]
    return (
        f"Fix {len(violations)} violation(s) ({', '.join(rules)}). "
        f"Affected: {'; '.join(items)}"
    )
