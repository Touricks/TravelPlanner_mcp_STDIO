"""Travel Planner CLI — manage trips in SQLite.

Thin click handlers that parse arguments, call service functions from utils.py,
and format output. All write logic lives in utils.py (service layer pattern).

Usage:
    python3 -m assets.database.cli.trip [--db PATH] COMMAND [ARGS]

Examples:
    trip status
    trip add-place "Ghirardelli Square" --style landmark --city "San Francisco"
    trip schedule 47 --day 9 --time 11:00 --duration 60
"""

from pathlib import Path

import click
from . import utils


@click.group()
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="Path to travel.db (default: auto-detect)",
)
@click.pass_context
def cli(ctx, db):
    """Travel Planner CLI — manage trips in SQLite."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = utils.get_db_path(db)


# ── trip status ─────────────────────────────────────────────


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show per-day breakdown")
@click.pass_context
def status(ctx, verbose):
    """Show trip dashboard: counts, sync state, alerts."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        data = utils.get_status(conn, trip)

        # Header
        click.echo(
            f"Trip: {trip['destination']} "
            f"({trip['start_date']} to {trip['end_date']})"
        )
        click.echo()

        # Table counts
        click.echo("  Tables:")
        for table, count in data["table_counts"].items():
            click.echo(f"    {table:<20s} {count:>4d}")
        click.echo()

        # Sync status
        click.echo("  Pending sync:")
        if data["sync_pending"]:
            for entity, count in data["sync_pending"].items():
                click.echo(f"    {entity:<20s} {count:>4d}")
        else:
            click.echo("    (all synced)")
        click.echo()

        # Alerts
        a = data["alerts"]
        parts = []
        if a["open_risks"]:
            parts.append(f"{a['open_risks']} open risks")
        if a["incomplete_todos"]:
            parts.append(f"{a['incomplete_todos']} incomplete todos")
        if a["unscheduled"]:
            parts.append(f"{a['unscheduled']} unscheduled places")
        click.echo(f"  Alerts: {', '.join(parts) if parts else 'none'}")

        # Per-day breakdown
        if verbose and data["days"]:
            click.echo()
            click.echo(
                "  Day  Date        Region                 "
                " Stops  Confirmed  Pending"
            )
            click.echo("  " + "-" * 68)
            for d in data["days"]:
                click.echo(
                    f"  {d['day_num']:>3d}  {d['date']}  "
                    f"{(d['group_region'] or ''):<22s} "
                    f"{d['stop_count']:>5d}  {d['confirmed']:>9d}  "
                    f"{d['pending']:>7d}"
                )
    finally:
        conn.close()


# ── trip add-place ──────────────────────────────────────────


@cli.command("add-place")
@click.argument("name_en")
@click.option("--cn", "name_cn", default=None, help="Chinese name")
@click.option(
    "--style",
    required=True,
    type=click.Choice(utils.VALID_STYLES, case_sensitive=False),
    help="Place style/category",
)
@click.option("--city", default=None, help="City name")
@click.option(
    "--address", default=None, help="Street address (auto-generates Maps URL)"
)
@click.option(
    "--source",
    default="user",
    type=click.Choice(utils.VALID_SOURCES, case_sensitive=False),
    help="Attribution source",
)
@click.option("--description", default=None, help="Description text")
@click.pass_context
def add_place(ctx, name_en, name_cn, style, city, address, source, description):
    """Add a new place to the database."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        place = utils.create_place(
            conn,
            trip["id"],
            name_en=name_en,
            name_cn=name_cn,
            style=style,
            city=city,
            address=address,
            source=source,
            description=description,
        )
        click.echo(
            f"Added place #{place['id']} (uuid: {place['uuid'][:12]}...) "
            f'"{name_en}" | style: {style}'
            + (f" | city: {city}" if city else "")
        )
        if place.get("maps_url"):
            click.echo(f"  Maps: {place['maps_url']}")
    finally:
        conn.close()


# ── trip schedule ───────────────────────────────────────────


@cli.command()
@click.argument("place_ref")
@click.option(
    "--day", "day_num", required=True, type=int, help="Day number (1-based)"
)
@click.option("--time", "time_start", default=None, help="Start time HH:MM")
@click.option(
    "--duration",
    "duration_minutes",
    default=None,
    type=int,
    help="Duration in minutes",
)
@click.option("--region", "group_region", default=None, help="Group/region label")
@click.option("--notes", default=None, help="Visit notes")
@click.option(
    "--timing",
    "timing_type",
    default="flexible",
    type=click.Choice(["fixed", "flexible", "windowed"], case_sensitive=False),
    help="Timing type (fixed=booked tour, flexible=casual stop)",
)
@click.option("--parent", "parent_item_id", default=None, type=int, help="Parent item ID for nested activities")
@click.option("--force", is_flag=True, help="Override fixed-event conflict warnings")
@click.pass_context
def schedule(ctx, place_ref, day_num, time_start, duration_minutes, group_region, notes, timing_type, parent_item_id, force):
    """Schedule a place visit on a specific day."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        place = utils.resolve_place(conn, place_ref)
        item = utils.schedule_visit(
            conn,
            trip["id"],
            place_id=place["id"],
            day_num=day_num,
            trip=trip,
            time_start=time_start,
            duration_minutes=duration_minutes,
            group_region=group_region,
            notes=notes,
            timing_type=timing_type,
            parent_item_id=parent_item_id,
            force=force,
        )
        iso_date = utils.day_num_to_date(trip, day_num)
        time_part = ""
        if time_start:
            time_part = f" | time: {time_start}"
            if item.get("time_end"):
                time_part = f" | time: {time_start}-{item['time_end']}"
        click.echo(
            f'Scheduled "{place["name_en"]}" on Day {day_num} ({iso_date})'
            f"{time_part} | item #{item['id']}"
        )
        # Display overlap warnings
        for w in item.get("_warnings", []):
            click.echo(w)
    finally:
        conn.close()


# ── Sprint 2: Mutation Commands ─────────────────────────────


@cli.command()
@click.argument("item_ref")
@click.pass_context
def confirm(ctx, item_ref):
    """Confirm a scheduled visit (set decision=confirmed)."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        item = utils.resolve_item(conn, item_ref)
        place = conn.execute(
            "SELECT name_en FROM places WHERE id=?", (item["place_id"],)
        ).fetchone()
        name = place["name_en"] if place else "Unknown"

        if item["decision"] == "confirmed":
            click.echo(f'Already confirmed: "{name}"')
            return

        was_rejected = item["decision"] == "rejected"
        utils.confirm_visit(conn, trip["id"], item)
        if was_rejected:
            click.echo(f'Warning: "{name}" was previously rejected. Now confirmed.')
        else:
            click.echo(
                f'Confirmed: "{name}" (Day {item["date"]}, {item["time_start"] or "no time"})'
            )
    finally:
        conn.close()


@cli.command()
@click.argument("item_ref")
@click.option("--reason", default=None, help="Reason for dropping")
@click.pass_context
def drop(ctx, item_ref, reason):
    """Drop a scheduled visit (set decision=rejected). Place stays."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        item = utils.resolve_item(conn, item_ref)
        place = conn.execute(
            "SELECT name_en FROM places WHERE id=?", (item["place_id"],)
        ).fetchone()
        name = place["name_en"] if place else "Unknown"

        utils.drop_visit(conn, trip["id"], item, reason=reason)
        click.echo(f'Dropped: "{name}" (Day {item["date"]})')
        if reason:
            click.echo(f"  Reason: {reason}")
        click.echo("  Place still available for rescheduling.")
    finally:
        conn.close()


@cli.command("update-place")
@click.argument("place_ref")
@click.option("--name", "name_en", default=None, help="English name")
@click.option("--cn", "name_cn", default=None, help="Chinese name")
@click.option(
    "--style",
    default=None,
    type=click.Choice(utils.VALID_STYLES, case_sensitive=False),
    help="Style/category",
)
@click.option("--city", default=None, help="City")
@click.option("--address", default=None, help="Address (recomputes Maps URL)")
@click.pass_context
def update_place(ctx, place_ref, name_en, name_cn, style, city, address):
    """Update place metadata (name, style, city, address)."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        place = utils.resolve_place(conn, place_ref)
        updated = utils.update_place_fields(
            conn, trip["id"], place,
            name_en=name_en, name_cn=name_cn, style=style,
            city=city, address=address,
        )
        click.echo(f'Updated place "{updated["name_en"]}" (#{updated["id"]})')
    finally:
        conn.close()


@cli.command()
@click.argument("item_ref")
@click.option("--day", "day_num", default=None, type=int, help="New day number")
@click.option("--time", "time_start", default=None, help="New start time HH:MM")
@click.option("--duration", "duration_minutes", default=None, type=int, help="New duration (minutes)")
@click.pass_context
def reschedule(ctx, item_ref, day_num, time_start, duration_minutes):
    """Reschedule a visit to a different day/time."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        item = utils.resolve_item(conn, item_ref)
        place = conn.execute(
            "SELECT name_en FROM places WHERE id=?", (item["place_id"],)
        ).fetchone()
        name = place["name_en"] if place else "Unknown"

        old_date = item["date"]
        old_time = item["time_start"] or "?"

        updated = utils.reschedule_visit(
            conn, trip["id"], item, trip,
            day_num=day_num, time_start=time_start,
            duration_minutes=duration_minutes,
        )

        new_date = updated["date"]
        new_time = updated["time_start"] or "?"
        click.echo(
            f'Rescheduled "{name}" (#{item["id"]}): '
            f"{old_date} {old_time} → {new_date} {new_time}"
        )
    finally:
        conn.close()


@cli.command("remove-place")
@click.argument("place_ref")
@click.option("--force", is_flag=True, help="Remove even with active visits")
@click.pass_context
def remove_place_cmd(ctx, place_ref, force):
    """Soft-delete a place and cascade to its visits."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        place = utils.resolve_place(conn, place_ref)
        _, cascade_count = utils.remove_place(conn, trip["id"], place, force=force)
        click.echo(
            f'Removed place "{place["name_en"]}" (#{place["id"]}) '
            f"and {cascade_count} scheduled visit(s)."
        )
    finally:
        conn.close()


# ── Sprint 3: Sync & Export Commands ────────────────────────


@cli.command("export-yaml")
@click.option("--output", "output_path", default=None, type=click.Path(), help="Output file")
@click.pass_context
def export_yaml(ctx, output_path):
    """Export itinerary to pois.yaml format."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        yaml_text = utils.export_yaml(conn, trip)

        if output_path:
            Path(output_path).write_text(yaml_text, encoding="utf-8")
            click.echo(f"Exported to {output_path}")
        else:
            # Default: trips/{trip_id}/pois.yaml
            root = utils.find_project_root()
            default_path = root / "trips" / trip["id"] / "pois_export.yaml"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text(yaml_text, encoding="utf-8")
            click.echo(f"Exported to {default_path}")
    finally:
        conn.close()


@cli.command("push-notion")
@click.option("--dry-run", is_flag=True, help="Show counts without generating manifest")
@click.pass_context
def push_notion(ctx, dry_run):
    """Show pending sync items (dry-run mode)."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        trip = utils.get_trip(conn)
        summary = utils.get_push_summary(conn)
        total = sum(summary.values())

        click.echo(f'Push summary for "{trip["destination"]}":')
        if summary:
            for entity, count in sorted(summary.items()):
                click.echo(f"  {entity:<20s} {count:>4d} pending")
            click.echo(f"  {'Total':<20s} {total:>4d}")
        else:
            click.echo("  All synced — nothing to push.")

        if not dry_run and total > 0:
            click.echo("\nManifest generation not yet implemented (Sprint 3 future).")
            click.echo("Use --dry-run to preview, or implement notion_manifest.py.")
    finally:
        conn.close()


@cli.command("mark-synced")
@click.argument("uuid")
@click.option("--notion-id", default=None, help="Notion page ID to store")
@click.pass_context
def mark_synced_cmd(ctx, uuid, notion_id):
    """Mark an entity as synced after successful Notion push."""
    conn = utils.get_connection(ctx.obj["db_path"])
    try:
        found = utils.mark_synced(conn, uuid, notion_page_id=notion_id)
        if found:
            click.echo(f"Marked {uuid[:12]}... as synced")
            if notion_id:
                click.echo(f"  notion_page_id: {notion_id}")
        else:
            raise click.ClickException(f"No entity found with UUID '{uuid}'")
    finally:
        conn.close()


# ── Entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    cli()
