"""MCP artifact -> SQLite bridge.

Batch import functions that sync JSON artifacts into SQLite.
SQLite is a materialized projection of JSON artifacts (JSON is canonical).

Uses the same audit/transaction patterns as tripdb.cli.utils.
Actor = 'mcp_bridge' in all audit_log entries.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from typing import Any, Optional

from tripdb.cli.utils import (
    compute_sort_order,
    format_maps_url,
    log_audit,
)

ACTOR = "mcp_bridge"


# ── Helpers ────────────────────────────────────────────────


def candidate_id(name_en: str, address: str) -> str:
    """Deterministic hash for place identity. Best-effort dedup, MVP."""
    raw = f"{name_en}|{address or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _artifact_hash(data: Any) -> str:
    """SHA256[:16] of artifact JSON for change detection."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _day_num_to_date(start_date: str, day_num: int) -> str:
    """Convert 1-based day number to ISO date string."""
    start = date.fromisoformat(start_date)
    return (start + timedelta(days=day_num - 1)).isoformat()


def _check_sync(
    conn: sqlite3.Connection,
    session_id: str,
    artifact_type: str,
    data: Any,
) -> Optional[str]:
    """Check bridge_sync. Returns None if should proceed, 'skipped' if unchanged."""
    new_hash = _artifact_hash(data)
    row = conn.execute(
        "SELECT artifact_hash, sync_state FROM bridge_sync "
        "WHERE session_id = ? AND artifact_type = ?",
        (session_id, artifact_type),
    ).fetchone()
    if row and row[0] == new_hash and row[1] == "synced":
        return "skipped"
    return None


def _record_sync(
    conn: sqlite3.Connection,
    session_id: str,
    artifact_type: str,
    data: Any,
    rows_imported: int,
    error: Optional[str] = None,
) -> None:
    """Upsert bridge_sync record."""
    now = conn.execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    ).fetchone()[0]
    art_hash = _artifact_hash(data)
    state = "failed" if error else "synced"

    conn.execute(
        "INSERT INTO bridge_sync (session_id, artifact_type, artifact_hash, "
        "sync_state, rows_imported, last_error, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(session_id, artifact_type) DO UPDATE SET "
        "artifact_hash=excluded.artifact_hash, sync_state=excluded.sync_state, "
        "rows_imported=excluded.rows_imported, last_error=excluded.last_error, "
        "synced_at=excluded.synced_at",
        (session_id, artifact_type, art_hash, state, rows_imported, error, now),
    )


# ── Setup ──────────────────────────────────────────────────


def ensure_trip(
    conn: sqlite3.Connection,
    trip_id: str,
    destination: str,
    start_date: str,
    end_date: str,
) -> None:
    """INSERT OR IGNORE trip row."""
    conn.execute(
        "INSERT OR IGNORE INTO trips (id, destination, start_date, end_date) "
        "VALUES (?, ?, ?, ?)",
        (trip_id, destination, start_date, end_date),
    )
    conn.commit()


def register_session(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    workspace_id: Optional[str] = None,
    workspace_tag: Optional[str] = None,
) -> None:
    """INSERT OR IGNORE session row."""
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, trip_id, source, workspace_id, workspace_tag) "
        "VALUES (?, ?, 'mcp', ?, ?)",
        (session_id, trip_id, workspace_id, workspace_tag),
    )
    conn.commit()


def update_session_status(
    conn: sqlite3.Connection,
    session_id: str,
    status: str,
) -> None:
    """Update session status in SQLite. Best-effort sync from WorkflowState.

    Only accepts DB-valid statuses: active, complete, cancelled.
    Sets completed_at for terminal states.
    """
    if status not in ("active", "complete", "cancelled"):
        return
    conn.execute(
        "UPDATE sessions SET status = ?, completed_at = "
        "CASE WHEN ? IN ('complete', 'cancelled') "
        "THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END "
        "WHERE id = ?",
        (status, status, session_id),
    )
    conn.commit()


# ── Import Functions ───────────────────────────────────────


def import_pois(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    artifact: dict,
) -> dict:
    """Batch import POI candidates into places + session_places.

    Returns {status, rows_imported, candidate_map: {candidate_id: place_id}}.
    Idempotent: checks bridge_sync hash, dedup via candidate_id.
    """
    assert session_id, "session_id is required (not nullable for bridge writes)"

    skip = _check_sync(conn, session_id, "poi_search", artifact)
    if skip:
        return {"status": "skipped", "rows_imported": 0, "candidate_map": {}}

    candidates = artifact.get("candidates", [])
    cmap = {}  # candidate_id -> place_id
    created = 0

    try:
        for i, c in enumerate(candidates):
            name = c.get("name_en", "")
            addr = c.get("address", "")
            cid = c.get("candidate_id") or candidate_id(name, addr)

            # Check if already linked in this session
            existing = conn.execute(
                "SELECT place_id FROM session_places "
                "WHERE session_id = ? AND candidate_id = ?",
                (session_id, cid),
            ).fetchone()
            if existing:
                cmap[cid] = existing[0]
                continue

            # Dedup: find existing place by name + address
            place_row = conn.execute(
                "SELECT id FROM places "
                "WHERE name_en = ? AND address = ? AND deleted_at IS NULL",
                (name, addr),
            ).fetchone()

            if place_row:
                place_id = place_row[0]
            else:
                # Create new place
                maps_url = format_maps_url(addr) if addr else None
                conn.execute(
                    "INSERT INTO places (name_en, name_cn, style, address, city, "
                    "lat, lng, maps_url, description, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        c.get("name_cn"),
                        c.get("style", "landmark"),
                        addr,
                        c.get("city"),
                        c.get("lat"),
                        c.get("lng"),
                        maps_url,
                        c.get("description"),
                        "agent",
                    ),
                )
                place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                created += 1

            # Link in session_places
            conn.execute(
                "INSERT OR IGNORE INTO session_places "
                "(session_id, place_id, candidate_id, artifact_type, source_rank) "
                "VALUES (?, ?, ?, 'poi_search', ?)",
                (session_id, place_id, cid, i),
            )
            cmap[cid] = place_id

        log_audit(
            conn, trip_id, "batch_import_pois", "place", None,
            new_value={"count": len(candidates), "created": created,
                       "reused": len(candidates) - created},
            actor=ACTOR,
        )
        _record_sync(conn, session_id, "poi_search", artifact, len(candidates))
        conn.commit()

        return {
            "status": "synced",
            "rows_imported": len(candidates),
            "candidate_map": cmap,
        }

    except Exception as e:
        conn.rollback()
        _record_sync(conn, session_id, "poi_search", artifact, 0, str(e))
        conn.commit()
        return {"status": "failed", "rows_imported": 0, "error": str(e),
                "candidate_map": {}}


def import_itinerary(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    artifact: dict,
    candidate_map: Optional[dict] = None,
) -> dict:
    """Batch import itinerary items.

    candidate_map: {candidate_id: place_id} from import_pois.
    Falls back to session_places lookup, then name_en matching.
    """
    assert session_id, "session_id is required"

    skip = _check_sync(conn, session_id, "scheduling", artifact)
    if skip:
        return {"status": "skipped", "rows_imported": 0}

    cmap = candidate_map or {}
    start_date = artifact.get("start_date", "")
    days = artifact.get("days", [])
    imported = 0

    try:
        # Soft-delete previous session items (re-import safety)
        now = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        ).fetchone()[0]
        conn.execute(
            "UPDATE itinerary_items SET deleted_at = ? "
            "WHERE session_id = ? AND deleted_at IS NULL",
            (now, session_id),
        )

        for day in days:
            day_num = day.get("day_num", 1)
            iso_date = day.get("date") or _day_num_to_date(start_date, day_num)
            region = day.get("region")
            day_item_ids = []  # track for parent_item_index resolution

            for item in day.get("items", []):
                # Resolve place_id
                place_id = None
                cid = item.get("candidate_id")
                if cid and cid in cmap:
                    place_id = cmap[cid]
                elif cid:
                    # Fallback: session_places lookup
                    row = conn.execute(
                        "SELECT place_id FROM session_places "
                        "WHERE session_id = ? AND candidate_id = ?",
                        (session_id, cid),
                    ).fetchone()
                    if row:
                        place_id = row[0]

                if place_id is None:
                    # Fallback: match by name_en
                    name = item.get("name_en", "")
                    row = conn.execute(
                        "SELECT id FROM places WHERE name_en = ? AND deleted_at IS NULL",
                        (name,),
                    ).fetchone()
                    if row:
                        place_id = row[0]

                if place_id is None:
                    # Last resort: create place from item data
                    addr = item.get("address", "")
                    maps_url = format_maps_url(addr) if addr else None
                    conn.execute(
                        "INSERT INTO places (name_en, style, address, maps_url, source) "
                        "VALUES (?, ?, ?, ?, 'agent')",
                        (item.get("name_en", "Unknown"), item.get("style", "landmark"),
                         addr, maps_url),
                    )
                    place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                time_start = item.get("start_time")
                time_end = item.get("end_time")
                duration = item.get("duration_minutes")
                sort_order = compute_sort_order(day_num, time_start)

                # Resolve parent_item_index to parent_item_id
                parent_item_id = None
                parent_idx = item.get("parent_item_index")
                if parent_idx is not None and 0 <= parent_idx < len(day_item_ids):
                    parent_item_id = day_item_ids[parent_idx]

                conn.execute(
                    "INSERT INTO itinerary_items "
                    "(trip_id, session_id, place_id, date, time_start, time_end, "
                    "duration_minutes, group_region, sort_order, timing_type, "
                    "parent_item_id, preceding_travel_minutes, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trip_id, session_id, place_id, iso_date,
                        time_start, time_end, duration, region,
                        sort_order,
                        item.get("timing_type", "flexible"),
                        parent_item_id,
                        item.get("preceding_travel_minutes"),
                        item.get("notes"),
                    ),
                )
                item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                day_item_ids.append(item_id)
                imported += 1

        log_audit(
            conn, trip_id, "batch_import_itinerary", "itinerary_item", None,
            new_value={"days": len(days), "items": imported},
            actor=ACTOR,
        )
        _record_sync(conn, session_id, "scheduling", artifact, imported)
        conn.commit()

        return {"status": "synced", "rows_imported": imported}

    except Exception as e:
        conn.rollback()
        _record_sync(conn, session_id, "scheduling", artifact, 0, str(e))
        conn.commit()
        return {"status": "failed", "rows_imported": 0, "error": str(e)}


def import_restaurants(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    artifact: dict,
    trip_start: str,
) -> dict:
    """Batch import restaurant recommendations as places + itinerary_items."""
    assert session_id, "session_id is required"

    skip = _check_sync(conn, session_id, "restaurants", artifact)
    if skip:
        return {"status": "skipped", "rows_imported": 0}

    recs = artifact.get("recommendations", [])
    imported = 0

    # Default meal times
    meal_defaults = {
        "lunch": ("12:00", "13:00", 60),
        "dinner": ("18:30", "20:00", 90),
    }

    try:
        for rec in recs:
            name = rec.get("name_en", "")
            addr = rec.get("address", "")
            cid = candidate_id(name, addr)

            # Dedup place
            place_row = conn.execute(
                "SELECT id FROM places "
                "WHERE name_en = ? AND address = ? AND deleted_at IS NULL",
                (name, addr),
            ).fetchone()

            if place_row:
                place_id = place_row[0]
            else:
                maps_url = format_maps_url(addr) if addr else None
                conn.execute(
                    "INSERT INTO places (name_en, name_cn, style, address, "
                    "maps_url, description, source) "
                    "VALUES (?, ?, 'food', ?, ?, ?, 'agent')",
                    (name, rec.get("name_cn"), addr, maps_url,
                     rec.get("cuisine")),
                )
                place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Link in session_places
            conn.execute(
                "INSERT OR IGNORE INTO session_places "
                "(session_id, place_id, candidate_id, artifact_type) "
                "VALUES (?, ?, ?, 'restaurants')",
                (session_id, place_id, cid),
            )

            # Create itinerary item
            day_num = rec.get("day_num", 1)
            iso_date = _day_num_to_date(trip_start, day_num)
            meal = rec.get("meal_type", "dinner")
            time_start, time_end, duration = meal_defaults.get(
                meal, ("18:30", "20:00", 90)
            )
            sort_order = compute_sort_order(day_num, time_start)

            conn.execute(
                "INSERT INTO itinerary_items "
                "(trip_id, session_id, place_id, date, time_start, time_end, "
                "duration_minutes, sort_order, timing_type, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'flexible', ?)",
                (trip_id, session_id, place_id, iso_date,
                 time_start, time_end, duration, sort_order,
                 rec.get("notes")),
            )
            imported += 1

        log_audit(
            conn, trip_id, "batch_import_restaurants", "place", None,
            new_value={"count": len(recs)},
            actor=ACTOR,
        )
        _record_sync(conn, session_id, "restaurants", artifact, imported)
        conn.commit()

        return {"status": "synced", "rows_imported": imported}

    except Exception as e:
        conn.rollback()
        _record_sync(conn, session_id, "restaurants", artifact, 0, str(e))
        conn.commit()
        return {"status": "failed", "rows_imported": 0, "error": str(e)}


def import_hotels(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    artifact: dict,
) -> dict:
    """Batch import hotel recommendations."""
    assert session_id, "session_id is required"

    skip = _check_sync(conn, session_id, "hotels", artifact)
    if skip:
        return {"status": "skipped", "rows_imported": 0}

    recs = artifact.get("recommendations", [])
    imported = 0

    try:
        # Soft-delete previous session hotels
        now = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        ).fetchone()[0]
        conn.execute(
            "UPDATE hotels SET deleted_at = ? "
            "WHERE session_id = ? AND deleted_at IS NULL",
            (now, session_id),
        )

        for rec in recs:
            conn.execute(
                "INSERT INTO hotels "
                "(trip_id, session_id, city, hotel_name, address, "
                "check_in, check_out, booking_url, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trip_id, session_id,
                    rec.get("city", ""),
                    rec.get("name", ""),
                    rec.get("address", ""),
                    rec["check_in"],
                    rec["check_out"],
                    rec.get("booking_url"),
                    rec.get("notes"),
                ),
            )
            imported += 1

        log_audit(
            conn, trip_id, "batch_import_hotels", "hotel", None,
            new_value={"count": imported},
            actor=ACTOR,
        )
        _record_sync(conn, session_id, "hotels", artifact, imported)
        conn.commit()

        return {"status": "synced", "rows_imported": imported}

    except Exception as e:
        conn.rollback()
        _record_sync(conn, session_id, "hotels", artifact, 0, str(e))
        conn.commit()
        return {"status": "failed", "rows_imported": 0, "error": str(e)}


# Rule-id to risk category mapping
_RULE_CATEGORY = {
    "time_overlap": "logistics",
    "nature_sunset": "logistics",
    "staffed_closing": "logistics",
    "travel_time": "road",
    "daily_pace": "logistics",
    "region_cluster": "logistics",
    "meal_coverage": "logistics",
}


def import_review_risks(
    conn: sqlite3.Connection,
    session_id: str,
    trip_id: str,
    artifact: dict,
) -> dict:
    """Import review items with verdict 'reject' or 'flag' as risks."""
    assert session_id, "session_id is required"

    skip = _check_sync(conn, session_id, "review", artifact)
    if skip:
        return {"status": "skipped", "rows_imported": 0}

    items = artifact.get("items", [])
    imported = 0

    try:
        # Soft-delete previous session risks from review
        now = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        ).fetchone()[0]
        conn.execute(
            "UPDATE risks SET deleted_at = ? "
            "WHERE session_id = ? AND source = 'review' AND deleted_at IS NULL",
            (now, session_id),
        )

        for item in items:
            verdict = item.get("verdict", "accept")
            if verdict == "accept":
                continue

            rule_id = item.get("rule_id", "")
            category = _RULE_CATEGORY.get(rule_id, "logistics")

            conn.execute(
                "INSERT INTO risks "
                "(trip_id, session_id, category, risk, detail, "
                "action_required, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'review')",
                (
                    trip_id, session_id, category,
                    f"[{item.get('source', 'rule')}] {rule_id}",
                    item.get("reason", ""),
                    item.get("suggestion"),
                ),
            )
            imported += 1

        log_audit(
            conn, trip_id, "batch_import_review", "risk", None,
            new_value={"total_items": len(items), "risks_created": imported},
            actor=ACTOR,
        )
        _record_sync(conn, session_id, "review", artifact, imported)
        conn.commit()

        return {"status": "synced", "rows_imported": imported}

    except Exception as e:
        conn.rollback()
        _record_sync(conn, session_id, "review", artifact, 0, str(e))
        conn.commit()
        return {"status": "failed", "rows_imported": 0, "error": str(e)}


def rebuild_session(
    conn: sqlite3.Connection,
    session_id: str,
    artifacts: dict,
    trip_start: Optional[str] = None,
) -> dict:
    """Re-sync all artifacts for a session. Idempotent full rebuild.

    artifacts: {artifact_type: artifact_data}
    """
    results = {}

    row = conn.execute(
        "SELECT trip_id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        return {"status": "failed", "error": f"Session {session_id} not found"}
    trip_id = row[0]

    # Mark all existing sync records as stale
    conn.execute(
        "UPDATE bridge_sync SET sync_state = 'stale' WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()

    if "poi_search" in artifacts or "poi-candidates" in artifacts:
        data = artifacts.get("poi_search") or artifacts.get("poi-candidates")
        results["poi_search"] = import_pois(conn, session_id, trip_id, data)

    cmap = results.get("poi_search", {}).get("candidate_map", {})

    if "scheduling" in artifacts or "itinerary" in artifacts:
        data = artifacts.get("scheduling") or artifacts.get("itinerary")
        results["scheduling"] = import_itinerary(
            conn, session_id, trip_id, data, cmap
        )

    if "restaurants" in artifacts:
        results["restaurants"] = import_restaurants(
            conn, session_id, trip_id, artifacts["restaurants"],
            trip_start or "",
        )

    if "hotels" in artifacts:
        results["hotels"] = import_hotels(
            conn, session_id, trip_id, artifacts["hotels"]
        )

    if "review" in artifacts or "review-report" in artifacts:
        data = artifacts.get("review") or artifacts.get("review-report")
        results["review"] = import_review_risks(
            conn, session_id, trip_id, data
        )

    return {"status": "rebuilt", "stages": results}
