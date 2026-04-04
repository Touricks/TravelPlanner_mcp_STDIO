When implementing or modifying the CLI write layer (trip.py):

- CLI write layer lives in `tripdb/cli/trip.py` with service functions in `tripdb/cli/utils.py`
- Follow the command signatures and behavior exactly as specified
- All writes go through service functions in `utils.py` that wrap INSERT/UPDATE + audit_log in one transaction
- Push to Notion uses manifest pattern: CLI generates JSON with manifest_id → agent calls MCP → CLI marks synced via manifest_id
- Write commands accept UUID or integer ID only (no name prefix) — deterministic targeting for agent safety
- Read/status commands may additionally accept name prefix with hard-fail on ambiguity
- sort_order uses REAL values (schema: `sort_order REAL`) for fractional insertion between items
- Click handlers are thin wrappers: parse args → call service function → format output

## Available Commands (all 11 implemented)

Sprint 1 (foundation): `trip status`, `trip add-place`, `trip schedule`
Sprint 2 (mutations): `trip confirm`, `trip drop`, `trip reschedule`, `trip update-place`, `trip remove-place`
Sprint 3 (sync/export): `trip export-yaml`, `trip push-notion`, `trip mark-synced`

## Quick Reference

```bash
# Read-only
trip status [--verbose]
trip push-notion --dry-run

# Write (create)
trip add-place "Name" --style food [--cn "中文"] [--city "SF"] [--address "..."]
trip schedule <id_or_uuid> --day 3 [--time 14:00] [--duration 90] [--region "SF"]

# Write (mutate)
trip confirm <item_id_or_uuid>
trip drop <item_id_or_uuid> [--reason "text"]
trip reschedule <item_id_or_uuid> [--day 5] [--time 10:00] [--duration 120]
trip update-place <place_id_or_uuid> [--name "New"] [--address "New Addr"]
trip remove-place <place_id_or_uuid> [--force]

# Sync
trip mark-synced <uuid> [--notion-id <notion_page_id>]
trip export-yaml [--output path/to/file.yaml]
```

## Rebuild database
```bash
python3 -m tripdb.seed.import_all
```

## Run tests
```bash
python -m pytest tests/data/ -v --tb=short
```
