When working with travel plan data:

- The canonical data store is SQLite at `assets/database/travel.db` — not pois.yaml, not Notion
- Schema reference: `design/core/db/schema-reference.md` — read this before writing any SQL
- Rebuild DB: `python3 assets/database/seed/import_all.py`
- Use views for reads: `v_full_itinerary`, `v_foods`, `v_attractions`, `v_hotels`, `day_summary`, `open_risks`, `incomplete_todos`
- Day numbers are computed in views via `julianday(date) - julianday(trip.start_date) + 1` — never stored
- `duration_minutes` is INTEGER (90, not "1.5h") — use arithmetic directly
- `sort_order` is REAL for fractional insertion between items
- `hotels.nights` is a GENERATED column — never set it manually
- Sync flow: SQLite → Notion (publish-only). Never pull from Notion to overwrite SQLite
- `sync_status`: pending (never pushed) → synced (pushed) → modified (changed after push)
- Soft delete only: set `deleted_at`, never use DELETE FROM
- All tables have auto-generated UUIDs — use `uuid` column for cross-system references, not integer `id`
- `parent_item_id` links nested activities to their parent (e.g., dim sum → Chinatown visit). Overlap checker suppresses these.
- `timing_type`: `fixed` (booked tour/boat), `flexible` (walk/casual), `windowed` (must happen in range)
- `preceding_travel_minutes` + `arrival_buffer_minutes` model drive time and check-in buffers for items
- CLI `schedule` command auto-checks overlaps: blocks on fixed-event conflicts, warns on flexible overlaps. Use `--force` to override.
