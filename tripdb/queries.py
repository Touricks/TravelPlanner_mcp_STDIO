"""Session-scoped read queries for tripdb.

MCP server and bridge code use these functions for session-filtered reads.
CLI continues to use existing views directly (no session concept needed).

All functions return lists of dicts. Empty list if no data.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def _rows_to_dicts(cursor: sqlite3.Cursor) -> list:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def session_itinerary(conn: sqlite3.Connection, session_id: str) -> list:
    """Full itinerary for a session (via v_full_itinerary + session filter)."""
    cur = conn.execute(
        "SELECT * FROM v_full_itinerary WHERE session_id = ? "
        "ORDER BY date, time_start, sort_order",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def session_hotels(conn: sqlite3.Connection, session_id: str) -> list:
    """Hotels for a session."""
    cur = conn.execute(
        "SELECT * FROM v_hotels WHERE session_id = ? ORDER BY check_in",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def session_places(conn: sqlite3.Connection, session_id: str) -> list:
    """Places discovered in a session (via session_places join)."""
    cur = conn.execute(
        "SELECT p.*, sp.candidate_id, sp.artifact_type, sp.source_rank "
        "FROM places p "
        "JOIN session_places sp ON p.id = sp.place_id "
        "WHERE sp.session_id = ? AND p.deleted_at IS NULL "
        "ORDER BY sp.source_rank",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def session_risks(conn: sqlite3.Connection, session_id: str) -> list:
    """Risks from a session's review."""
    cur = conn.execute(
        "SELECT r.*, t.destination FROM risks r "
        "JOIN trips t ON r.trip_id = t.id "
        "WHERE r.session_id = ? AND r.deleted_at IS NULL "
        "ORDER BY r.category",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def session_sync_status(conn: sqlite3.Connection, session_id: str) -> list:
    """Bridge sync state for all artifacts in a session."""
    cur = conn.execute(
        "SELECT * FROM bridge_sync WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def session_day_summary(conn: sqlite3.Connection, session_id: str) -> list:
    """Per-day summary filtered to a session's itinerary items."""
    cur = conn.execute(
        "SELECT "
        "  CAST(julianday(ii.date) - julianday(t.start_date) + 1 AS INTEGER) AS day_num, "
        "  ii.date, "
        "  ii.group_region, "
        "  COUNT(*) AS stop_count, "
        "  SUM(CASE WHEN ii.decision = 'confirmed' THEN 1 ELSE 0 END) AS confirmed, "
        "  SUM(CASE WHEN ii.decision = 'pending' THEN 1 ELSE 0 END) AS pending, "
        "  SUM(ii.duration_minutes) AS total_minutes, "
        "  GROUP_CONCAT(p.name_en, ' -> ') AS route "
        "FROM itinerary_items ii "
        "JOIN places p ON ii.place_id = p.id "
        "JOIN trips t ON ii.trip_id = t.id "
        "WHERE ii.session_id = ? AND ii.decision != 'rejected' AND ii.deleted_at IS NULL "
        "GROUP BY ii.date "
        "ORDER BY ii.date",
        (session_id,),
    )
    return _rows_to_dicts(cur)


def resolve_candidate(
    conn: sqlite3.Connection,
    session_id: str,
    candidate_id: str,
) -> Optional[int]:
    """Resolve a candidate_id to a place_id via session_places."""
    row = conn.execute(
        "SELECT place_id FROM session_places "
        "WHERE session_id = ? AND candidate_id = ?",
        (session_id, candidate_id),
    ).fetchone()
    return row[0] if row else None


def find_active_session_by_workspace(
    conn: sqlite3.Connection,
    workspace_id: str,
) -> Optional[dict]:
    """Find the most recent active session for a workspace_id."""
    cur = conn.execute(
        "SELECT s.*, t.destination, t.start_date, t.end_date "
        "FROM sessions s "
        "JOIN trips t ON s.trip_id = t.id "
        "WHERE s.workspace_id = ? AND s.status = 'active' "
        "ORDER BY s.created_at DESC LIMIT 1",
        (workspace_id,),
    )
    rows = _rows_to_dicts(cur)
    return rows[0] if rows else None


def find_sessions_by_tag(
    conn: sqlite3.Connection,
    workspace_tag: str,
) -> list:
    """Search sessions by human-readable tag (substring match)."""
    cur = conn.execute(
        "SELECT s.*, t.destination, t.start_date, t.end_date "
        "FROM sessions s "
        "JOIN trips t ON s.trip_id = t.id "
        "WHERE s.workspace_tag LIKE ? "
        "ORDER BY s.created_at DESC",
        (f"%{workspace_tag}%",),
    )
    return _rows_to_dicts(cur)


def find_latest_active_session(conn: sqlite3.Connection) -> Optional[dict]:
    """Find the most recently created active session."""
    cur = conn.execute(
        "SELECT s.*, t.destination, t.start_date, t.end_date "
        "FROM sessions s "
        "JOIN trips t ON s.trip_id = t.id "
        "WHERE s.status = 'active' "
        "ORDER BY s.created_at DESC LIMIT 1",
    )
    rows = _rows_to_dicts(cur)
    return rows[0] if rows else None


def find_all_active_sessions(conn: sqlite3.Connection) -> list:
    """Find all active sessions, ordered by most recent first."""
    cur = conn.execute(
        "SELECT s.*, t.destination, t.start_date, t.end_date "
        "FROM sessions s "
        "JOIN trips t ON s.trip_id = t.id "
        "WHERE s.status = 'active' "
        "ORDER BY s.created_at DESC",
    )
    return _rows_to_dicts(cur)
