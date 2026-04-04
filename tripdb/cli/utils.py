"""Service layer for the trip CLI.

All database writes and shared logic live here. Click handlers in trip.py
are thin wrappers that call these functions.

Design decisions (from cli-write-layer-spec.md, Codex-reviewed):
- Service functions wrap INSERT + audit_log in one transaction
- Resolver: UUID/ID only for writes (no name prefix — agent safety)
- sort_order: day_num * 1000 + hour * 60 + minute
- maps_url: computed before INSERT, not by trigger
- audit_log: application-level INSERT (not SQL triggers)
"""

import json
import os
import re
import sqlite3
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import click

# ── Constants ───────────────────────────────────────────────

DEFAULT_DB_REL = "tripdb/travel.db"
VALID_STYLES = ("nature", "tech", "culture", "food", "landmark", "coffee")
VALID_SOURCES = ("teammate", "tripmate", "agent", "user")
UUID_PREFIX_RE = re.compile(r"^[0-9a-f]{4,}")

# Centralized entity table sets (prevents hard-coded list drift — Codex review)
SYNCABLE_TABLES = ("itinerary_items", "hotels", "risks", "places", "todos", "reservations")
SOFT_DELETE_TABLES = {"places", "itinerary_items", "hotels", "risks"}


# ── Infrastructure ──────────────────────────────────────────


def find_project_root() -> Path:
    """Walk up from this file to find the directory containing CLAUDE.md."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "CLAUDE.md").exists():
            return current
        current = current.parent
    raise FileNotFoundError("Could not find project root (no CLAUDE.md found)")


def get_db_path(db_flag: str | None) -> Path:
    """Resolve database path. Precedence: flag > env > default."""
    if db_flag:
        p = Path(db_flag)
    elif os.environ.get("TRAVEL_DB"):
        p = Path(os.environ["TRAVEL_DB"])
    else:
        p = find_project_root() / DEFAULT_DB_REL
    if not p.exists():
        raise click.ClickException(f"Database not found: {p}")
    return p


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open SQLite connection with row_factory and foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_trip(conn: sqlite3.Connection) -> dict:
    """Fetch the single trip. Errors if 0 or >1 trips exist."""
    rows = conn.execute("SELECT * FROM trips").fetchall()
    if len(rows) == 0:
        raise click.ClickException("No trips found in database")
    if len(rows) > 1:
        ids = ", ".join(dict(r)["id"] for r in rows)
        raise click.ClickException(
            f"Multiple trips found ({len(rows)}): {ids}. Use --trip to specify."
        )
    return dict(rows[0])


# ── Pure Helpers ────────────────────────────────────────────


def compute_sort_order(day_num: int, time_start: str | None) -> float:
    """Compute sort_order for chronological ordering within days.

    Formula: day_num * 1000 + hour * 60 + minute.
    Matches the pattern in import_csv.py for consistency with existing data.
    """
    base = day_num * 1000.0
    if time_start:
        parts = time_start.split(":")
        base += int(parts[0]) * 60 + int(parts[1])
    return base


def format_maps_url(address: str) -> str:
    """Build Google Maps URL from address."""
    return f"https://maps.google.com/?q={urllib.parse.quote_plus(address)}"


def day_num_to_date(trip: dict, day_num: int) -> str:
    """Convert 1-based day number to ISO date, validated against trip range."""
    start = date.fromisoformat(trip["start_date"])
    end = date.fromisoformat(trip["end_date"])
    total_days = (end - start).days + 1
    if day_num < 1 or day_num > total_days:
        raise click.ClickException(
            f"Day {day_num} is out of range (trip has days 1-{total_days})"
        )
    return (start + timedelta(days=day_num - 1)).isoformat()


# ── Resolver ────────────────────────────────────────────────


def _resolve_by_ref(conn: sqlite3.Connection, ref: str, table: str, id_col: str = "id") -> dict:
    """Generic resolver: try int ID, then UUID prefix. Returns dict or raises."""
    # Try integer ID
    try:
        row_id = int(ref)
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {id_col} = ? AND deleted_at IS NULL",
            (row_id,),
        ).fetchone()
        if row is None:
            raise click.ClickException(f"{table} #{row_id} not found (or deleted)")
        return dict(row)
    except ValueError:
        pass

    # Try UUID prefix
    if UUID_PREFIX_RE.match(ref):
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE uuid LIKE ? AND deleted_at IS NULL",
            (ref + "%",),
        ).fetchall()
        if len(rows) == 0:
            raise click.ClickException(f"No {table} with UUID prefix '{ref}'")
        if len(rows) > 1:
            matches = ", ".join(f"#{dict(r)[id_col]}" for r in rows)
            raise click.ClickException(
                f"Ambiguous UUID prefix '{ref}' matches {len(rows)} rows: {matches}"
            )
        return dict(rows[0])

    raise click.ClickException(
        f"Invalid reference '{ref}'. Use integer ID or UUID."
    )


def resolve_place(conn: sqlite3.Connection, ref: str) -> dict:
    """Resolve place by integer ID or UUID prefix. No name matching for writes."""
    return _resolve_by_ref(conn, ref, "places")


def resolve_item(conn: sqlite3.Connection, ref: str) -> dict:
    """Resolve itinerary_item by integer ID or UUID prefix."""
    return _resolve_by_ref(conn, ref, "itinerary_items")


# ── Audit ───────────────────────────────────────────────────


def log_audit(
    conn: sqlite3.Connection,
    trip_id: str,
    action: str,
    target_type: str,
    target_uuid: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    actor: str = "cli",
):
    """Insert audit_log entry. Does NOT commit — caller manages transaction."""
    conn.execute(
        "INSERT INTO audit_log (trip_id, action, target_type, target_uuid, "
        "old_value, new_value, actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            trip_id,
            action,
            target_type,
            target_uuid,
            json.dumps(old_value) if old_value else None,
            json.dumps(new_value) if new_value else None,
            actor,
        ),
    )


# ── Service Functions ───────────────────────────────────────


def create_place(
    conn: sqlite3.Connection,
    trip_id: str,
    *,
    name_en: str,
    style: str,
    name_cn: str | None = None,
    city: str | None = None,
    address: str | None = None,
    description: str | None = None,
    source: str = "user",
) -> dict:
    """Insert a place and log to audit_log. Returns the new place as a dict."""
    maps_url = format_maps_url(address) if address else None

    conn.execute(
        "INSERT INTO places (name_en, name_cn, style, address, city, maps_url, "
        "description, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name_en, name_cn, style, address, city, maps_url, description, source),
    )
    place_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    place = dict(row)

    log_audit(
        conn,
        trip_id,
        "add_place",
        "place",
        place["uuid"],
        new_value={
            "name_en": name_en,
            "name_cn": name_cn,
            "style": style,
            "city": city,
            "address": address,
            "maps_url": maps_url,
            "source": source,
        },
    )
    conn.commit()
    return place


def check_overlaps(
    conn: sqlite3.Connection,
    iso_date: str,
    time_start: str | None,
    time_end: str | None,
    exclude_item_id: int | None = None,
) -> list[dict]:
    """Check for time overlaps on a given date. Returns list of conflicting items.

    Suppresses parent-child overlaps (parent_item_id linked).
    """
    if not time_start or not time_end:
        return []

    query = """
        SELECT ii.id, p.name_en, ii.time_start, ii.time_end, ii.timing_type,
               ii.parent_item_id
        FROM itinerary_items ii
        JOIN places p ON ii.place_id = p.id
        WHERE ii.date = ? AND ii.deleted_at IS NULL AND ii.decision != 'rejected'
          AND ii.time_start IS NOT NULL AND ii.time_end IS NOT NULL
          AND ii.time_start < ? AND ii.time_end > ?
    """
    params = [iso_date, time_end, time_start]

    if exclude_item_id:
        query += " AND ii.id != ?"
        params.append(exclude_item_id)

    rows = conn.execute(query, params).fetchall()
    # Filter out parent-child relationships (nested activities are intentional)
    conflicts = []
    for r in rows:
        row = dict(r)
        # Only suppress if this row is explicitly a child of the item being checked
        if exclude_item_id is not None and row.get("parent_item_id") == exclude_item_id:
            continue
        conflicts.append(row)
    return conflicts


def schedule_visit(
    conn: sqlite3.Connection,
    trip_id: str,
    *,
    place_id: int,
    day_num: int,
    trip: dict,
    time_start: str | None = None,
    duration_minutes: int | None = None,
    group_region: str | None = None,
    notes: str | None = None,
    timing_type: str = "flexible",
    parent_item_id: int | None = None,
    preceding_travel_minutes: int | None = None,
    arrival_buffer_minutes: int | None = None,
    force: bool = False,
) -> dict:
    """Insert an itinerary item. Returns the new item as a dict.

    Checks for overlaps before inserting. Warns but proceeds unless
    the conflict is with a 'fixed' timing_type item (use force=True to override).
    """
    iso_date = day_num_to_date(trip, day_num)
    sort_order = compute_sort_order(day_num, time_start)

    # Compute time_end if both time_start and duration are provided
    time_end = None
    if time_start and duration_minutes:
        parts = time_start.split(":")
        total_min = int(parts[0]) * 60 + int(parts[1]) + duration_minutes
        time_end = f"{total_min // 60:02d}:{total_min % 60:02d}"

    # Check for overlaps (warn, don't block unless fixed conflict + no --force)
    warnings = []
    if time_start and time_end:
        conflicts = check_overlaps(conn, iso_date, time_start, time_end)
        for c in conflicts:
            label = f"{c['name_en']} ({c['time_start']}-{c['time_end']})"
            if c["timing_type"] == "fixed" and not force:
                raise click.ClickException(
                    f"Conflicts with FIXED event: {label}. Use --force to override."
                )
            warnings.append(f"  Warning: overlaps with {label}")

    conn.execute(
        "INSERT INTO itinerary_items (trip_id, place_id, date, time_start, time_end, "
        "duration_minutes, group_region, notes, sort_order, timing_type, "
        "parent_item_id, preceding_travel_minutes, arrival_buffer_minutes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trip_id,
            place_id,
            iso_date,
            time_start,
            time_end,
            duration_minutes,
            group_region,
            notes,
            sort_order,
            timing_type,
            parent_item_id,
            preceding_travel_minutes,
            arrival_buffer_minutes,
        ),
    )
    item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(
        "SELECT * FROM itinerary_items WHERE id = ?", (item_id,)
    ).fetchone()
    item = dict(row)

    # Fetch place name for audit context
    place_row = conn.execute(
        "SELECT name_en FROM places WHERE id = ?", (place_id,)
    ).fetchone()

    log_audit(
        conn,
        trip_id,
        "schedule_visit",
        "itinerary_item",
        item["uuid"],
        new_value={
            "place_id": place_id,
            "place_name": place_row["name_en"] if place_row else None,
            "date": iso_date,
            "day_num": day_num,
            "time_start": time_start,
            "time_end": time_end,
            "duration_minutes": duration_minutes,
            "group_region": group_region,
            "sort_order": sort_order,
        },
    )
    conn.commit()
    item["_warnings"] = warnings  # attach for CLI display
    return item


def get_status(conn: sqlite3.Connection, trip: dict) -> dict:
    """Query database views to build a trip status dashboard.

    Returns a dict with keys:
        'trip': the trip dict
        'table_counts': {table_name: count} for 6 data tables
        'sync_pending': {entity_type: count} from v_pending_sync
        'alerts': {'open_risks': int, 'incomplete_todos': int, 'unscheduled': int}
        'days': list of dicts from day_summary view
    """
    table_counts = {}
    for table in (
        "places",
        "itinerary_items",
        "hotels",
        "risks",
        "todos",
        "reservations",
    ):
        if table in SOFT_DELETE_TABLES:
            table_counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NULL"
            ).fetchone()[0]
        else:
            table_counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

    sync_rows = conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM v_pending_sync GROUP BY entity_type"
    ).fetchall()
    sync_pending = {row[0]: row[1] for row in sync_rows}

    alerts = {
        "open_risks": conn.execute(
            "SELECT COUNT(*) FROM open_risks"
        ).fetchone()[0],
        "incomplete_todos": conn.execute(
            "SELECT COUNT(*) FROM incomplete_todos"
        ).fetchone()[0],
        "unscheduled": conn.execute(
            "SELECT COUNT(*) FROM unscheduled_places"
        ).fetchone()[0],
    }

    days = [dict(row) for row in conn.execute("SELECT * FROM day_summary").fetchall()]

    return {
        "trip": trip,
        "table_counts": table_counts,
        "sync_pending": sync_pending,
        "alerts": alerts,
        "days": days,
    }


# ── Sprint 2: Mutation Service Functions ────────────────────


def confirm_visit(conn: sqlite3.Connection, trip_id: str, item: dict) -> dict:
    """Set decision='confirmed'. No-op if already confirmed."""
    if item["decision"] == "confirmed":
        return item  # no-op

    old_decision = item["decision"]
    conn.execute(
        "UPDATE itinerary_items SET decision='confirmed' WHERE id=?", (item["id"],)
    )
    log_audit(
        conn, trip_id, "confirm", "itinerary_item", item["uuid"],
        old_value={"decision": old_decision},
        new_value={"decision": "confirmed"},
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
    ).fetchone()
    return dict(row)


def drop_visit(
    conn: sqlite3.Connection, trip_id: str, item: dict, reason: str | None = None
) -> dict:
    """Set decision='rejected'. Optionally append reason to notes."""
    old_decision = item["decision"]
    old_notes = item.get("notes") or ""

    new_notes = old_notes
    if reason:
        new_notes = f"{old_notes}\n[Dropped] {reason}".strip() if old_notes else f"[Dropped] {reason}"

    conn.execute(
        "UPDATE itinerary_items SET decision='rejected', notes=? WHERE id=?",
        (new_notes, item["id"]),
    )
    log_audit(
        conn, trip_id, "drop", "itinerary_item", item["uuid"],
        old_value={"decision": old_decision, "notes": old_notes},
        new_value={"decision": "rejected", "notes": new_notes},
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
    ).fetchone()
    return dict(row)


def update_place_fields(
    conn: sqlite3.Connection, trip_id: str, place: dict, **changes
) -> dict:
    """Update place metadata. Only provided fields are changed."""
    # Filter to non-None changes
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        raise click.ClickException("No changes provided. Use at least one option.")

    # Snapshot old values
    old_snapshot = {k: place.get(k) for k in changes}

    # If address changed, recompute maps_url
    if "address" in changes:
        changes["maps_url"] = format_maps_url(changes["address"])

    # Build dynamic SET clause
    set_parts = [f"{col}=?" for col in changes]
    values = list(changes.values()) + [place["id"]]
    conn.execute(
        f"UPDATE places SET {', '.join(set_parts)} WHERE id=?", values
    )

    log_audit(
        conn, trip_id, "update_place", "place", place["uuid"],
        old_value=old_snapshot,
        new_value=changes,
    )
    conn.commit()
    row = conn.execute("SELECT * FROM places WHERE id=?", (place["id"],)).fetchone()
    return dict(row)


def reschedule_visit(
    conn: sqlite3.Connection,
    trip_id: str,
    item: dict,
    trip: dict,
    *,
    day_num: int | None = None,
    time_start: str | None = None,
    duration_minutes: int | None = None,
) -> dict:
    """Update scheduling of an existing visit."""
    if day_num is None and time_start is None and duration_minutes is None:
        raise click.ClickException(
            "Specify at least one of --day, --time, or --duration."
        )

    # Snapshot old values
    old_snapshot = {
        "date": item["date"],
        "time_start": item["time_start"],
        "time_end": item["time_end"],
        "duration_minutes": item["duration_minutes"],
        "sort_order": item["sort_order"],
    }

    # Merge: use new value if provided, else keep current
    new_date = item["date"]
    effective_day = day_num
    if day_num is not None:
        new_date = day_num_to_date(trip, day_num)
    else:
        # Compute current day_num from existing date
        start = date.fromisoformat(trip["start_date"])
        current = date.fromisoformat(item["date"])
        effective_day = (current - start).days + 1

    new_time = time_start if time_start is not None else item["time_start"]
    new_duration = duration_minutes if duration_minutes is not None else item["duration_minutes"]

    # Recompute time_end
    if new_time is not None and new_duration is not None:
        parts = new_time.split(":")
        total_min = int(parts[0]) * 60 + int(parts[1]) + new_duration
        new_time_end = f"{total_min // 60:02d}:{total_min % 60:02d}"
    elif time_start is not None:
        # time_start changed but no duration to recompute — clear stale time_end
        new_time_end = None
    else:
        new_time_end = item["time_end"]  # neither changed, keep original

    new_sort = compute_sort_order(effective_day, new_time)

    conn.execute(
        "UPDATE itinerary_items SET date=?, time_start=?, time_end=?, "
        "duration_minutes=?, sort_order=? WHERE id=?",
        (new_date, new_time, new_time_end, new_duration, new_sort, item["id"]),
    )

    new_snapshot = {
        "date": new_date,
        "time_start": new_time,
        "time_end": new_time_end,
        "duration_minutes": new_duration,
        "sort_order": new_sort,
    }
    log_audit(
        conn, trip_id, "reschedule", "itinerary_item", item["uuid"],
        old_value=old_snapshot, new_value=new_snapshot,
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM itinerary_items WHERE id=?", (item["id"],)
    ).fetchone()
    return dict(row)


def remove_place(
    conn: sqlite3.Connection, trip_id: str, place: dict, force: bool = False
) -> tuple[dict, int]:
    """Soft-delete a place and cascade to its itinerary items."""
    active_count = conn.execute(
        "SELECT COUNT(*) FROM itinerary_items "
        "WHERE place_id=? AND deleted_at IS NULL AND decision != 'rejected'",
        (place["id"],),
    ).fetchone()[0]

    if active_count > 0 and not force:
        raise click.ClickException(
            f'Place "{place["name_en"]}" has {active_count} active visit(s). '
            f"Use --force to remove."
        )

    now = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]

    # Soft-delete place
    conn.execute(
        "UPDATE places SET deleted_at=? WHERE id=?", (now, place["id"])
    )
    # Cascade to items
    cascade = conn.execute(
        "UPDATE itinerary_items SET deleted_at=? "
        "WHERE place_id=? AND deleted_at IS NULL",
        (now, place["id"]),
    ).rowcount

    log_audit(
        conn, trip_id, "remove_place", "place", place["uuid"],
        old_value={"name_en": place["name_en"], "style": place["style"]},
        new_value={"deleted_at": now, "cascade_count": cascade},
    )
    conn.commit()
    return place, cascade


# ── Sprint 3: Sync & Export Service Functions ───────────────


def minutes_to_duration_text(minutes: int | None) -> str:
    """Convert integer minutes to human-readable text. 90→'1.5h', 60→'1h', 30→'30min'.

    Delegates to _dur_text (the canonical implementation).
    """
    return _dur_text(minutes)


def _dur_text(minutes: int | None) -> str:
    """Convert minutes to compact duration. 90→'1.5h', 60→'1h', 30→'30min'."""
    if not minutes:
        return ""
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    if minutes >= 60:
        hours = minutes / 60
        return f"{hours:g}h"
    return f"{minutes}min"


def export_yaml(conn: sqlite3.Connection, trip: dict) -> str:
    """Export current itinerary to pois.yaml format string."""
    rows = conn.execute(
        "SELECT ii.*, p.name_en, p.name_cn, p.style, p.address, p.description, p.source "
        "FROM itinerary_items ii "
        "JOIN places p ON ii.place_id = p.id "
        "WHERE ii.deleted_at IS NULL AND ii.decision != 'rejected' "
        "AND p.deleted_at IS NULL "
        "ORDER BY ii.date, ii.sort_order"
    ).fetchall()

    lines = [
        f"# Trip POI List (exported from SQLite)",
        f"",
        f"trip:",
        f"  destination: {trip['destination']}",
        f"  dates: {trip['start_date']} to {trip['end_date']}",
        f"  version: {trip.get('version', 1)}",
        f"",
        f"pois:",
    ]

    current_date = None
    poi_id = 0
    for row in rows:
        r = dict(row)
        if r["date"] != current_date:
            current_date = r["date"]
            lines.append(f"")
            lines.append(f"  # ── {current_date} ──")

        poi_id += 1
        time_str = ""
        if r["time_start"] and r["time_end"]:
            time_str = f"{r['time_start']}-{r['time_end']}"
        elif r["time_start"]:
            time_str = r["time_start"]

        lines.append(f"")
        lines.append(f"  - id: {poi_id}")
        lines.append(f'    name_en: {r["name_en"]}')
        if r.get("name_cn"):
            lines.append(f'    name_cn: {r["name_cn"]}')
        lines.append(f'    date: "{r["date"]}"')
        if time_str:
            lines.append(f'    time: "{time_str}"')
        if r.get("duration_minutes"):
            lines.append(f"    duration: {_dur_text(r['duration_minutes'])}")
        lines.append(f'    style: {r["style"]}')
        if r.get("description"):
            lines.append(f'    reason: "{r["description"]}"')
        if r.get("address"):
            lines.append(f'    address: "{r["address"]}"')
        if r.get("source"):
            lines.append(f"    source: {r['source']}")
        lines.append(f"    decision: {r['decision']}")
        if r.get("notes"):
            lines.append(f'    note: "{r["notes"]}"')

    return "\n".join(lines) + "\n"


def get_push_summary(conn: sqlite3.Connection) -> dict:
    """Get counts of entities needing Notion push."""
    rows = conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM v_pending_sync GROUP BY entity_type"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def mark_synced(
    conn: sqlite3.Connection,
    uuid: str,
    notion_page_id: str | None = None,
) -> bool:
    """Mark an entity as synced across all syncable tables."""
    now = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]

    for table in SYNCABLE_TABLES:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE uuid=?", (uuid,)
        ).fetchone()
        if row:
            if notion_page_id is not None:
                conn.execute(
                    f"UPDATE {table} SET sync_status=?, last_synced_at=?, notion_page_id=? WHERE uuid=?",
                    ("synced", now, notion_page_id, uuid),
                )
            else:
                conn.execute(
                    f"UPDATE {table} SET sync_status=?, last_synced_at=? WHERE uuid=?",
                    ("synced", now, uuid),
                )
            conn.commit()
            return True

    return False
