# Travel Planner Database — Schema Reference

> Source: `assets/database/schema.sql` | DB: `assets/database/travel.db`
> Rebuild: `python3 assets/database/seed/import_all.py`

## Architecture

```
SQLite (canonical, writable)
  ├── places + itinerary_items ──push──→ Notion Travel Itinerary DB
  ├── hotels                   ──push──→ Notion Hotels DB (new)
  ├── risks / todos / reservations ───→ Notion parent page content
  └── audit_log (local only)
```

- **SQLite is the only writable store** — Notion is publish-only
- Reads: direct SQL against views
- Writes: validated CLI commands (`assets/database/cli/trip.py`)
- All entities have UUIDs for cross-system identity
- Soft delete via `deleted_at` (not hard DELETE)

## Tables

### trips
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | `"2026-04-san-francisco"` |
| uuid | TEXT UNIQUE | Auto-generated v4 UUID |
| destination | TEXT | `"San Francisco & California Coast"` |
| start_date | TEXT | ISO-8601 `"2026-04-17"` |
| end_date | TEXT | ISO-8601 `"2026-04-25"` |
| version | INTEGER | Schema version (currently 2) |
| notion_page_id | TEXT | `"32a9db12-bca8-818a-9681-c61552a64842"` |
| notion_synced_at | TEXT | Last push timestamp |

### places
Stable location metadata. A place exists once regardless of how many times it's visited.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| uuid | TEXT UNIQUE | Stable cross-system ID |
| name_en | TEXT NOT NULL | English name |
| name_cn | TEXT | Chinese name |
| style | TEXT | `nature\|tech\|culture\|food\|landmark\|coffee` |
| address | TEXT | Full street address |
| city | TEXT | City name |
| lat, lng | REAL | Coordinates (future use) |
| maps_url | TEXT | Google Maps link |
| description | TEXT | Bilingual description |
| source | TEXT | `teammate\|tripmate\|agent\|user` |
| notion_page_id | TEXT | Notion page UUID |
| notion_db_id | TEXT | Which Notion DB this belongs to |
| sync_status | TEXT | `pending\|synced\|modified\|error` |
| last_synced_at | TEXT | Last push timestamp |
| deleted_at | TEXT | Soft delete (NULL = active) |

### itinerary_items
A scheduled visit to a place. Same place can appear on multiple days.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| uuid | TEXT UNIQUE | Stable cross-system ID |
| trip_id | TEXT FK→trips | `"2026-04-san-francisco"` |
| place_id | INTEGER FK→places | Links to place metadata |
| date | TEXT | ISO-8601 date |
| time_start | TEXT | `"18:30"` |
| time_end | TEXT | `"19:30"` |
| duration_minutes | INTEGER | Minutes (60, 90, 150) for arithmetic |
| group_region | TEXT | `San Francisco\|Highway 1 North\|Big Sur & Coast\|Central Coast\|Los Angeles\|Sequoia` |
| notes | TEXT | Visit-specific notes |
| decision | TEXT | `pending\|confirmed\|rejected` |
| visited | INTEGER | 0/1 boolean |
| sort_order | REAL | Fractional ordering within a day |
| sync_status | TEXT | `pending\|synced\|modified\|error` |

### hotels
One row per stay (not per night). `nights` is auto-computed.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| trip_id | TEXT FK→trips | |
| city | TEXT NOT NULL | |
| hotel_name | TEXT | NULL until booked |
| check_in | TEXT | ISO-8601 date |
| check_out | TEXT | ISO-8601 date |
| nights | INTEGER | **GENERATED** from check_out - check_in |
| booking_status | TEXT | `unbooked\|booked\|confirmed\|cancelled` |
| cost_per_night | REAL | |
| total_cost | REAL | |
| confirmation_number | TEXT | |
| booking_url | TEXT | |
| sync_status | TEXT | `pending\|synced\|modified\|error` |

### risks
Warnings with resolution tracking.

| Column | Type | Notes |
|--------|------|-------|
| trip_id | TEXT FK→trips | |
| category | TEXT | `vehicle\|road\|tickets\|weather\|health\|logistics\|gear` |
| risk | TEXT | Short description |
| detail | TEXT | Full context |
| action_required | TEXT | What to do |
| status | TEXT | `open\|mitigated\|resolved` |
| resolved_at | TEXT | When resolved |
| resolution | TEXT | How it was resolved |

### reservations
Advance tickets & bookings linked to places.

| Column | Type | Notes |
|--------|------|-------|
| trip_id | TEXT FK→trips | |
| place_id | INTEGER FK→places | Nullable (e.g., Sequoia park entrance) |
| attraction | TEXT | Display name |
| booking_required | INTEGER | 0/1 |
| cost_per_person | REAL | In USD |
| cost_notes | TEXT | e.g., "$59.95/adult" |
| book_ahead | TEXT | e.g., "2-3 weeks ahead" |
| booking_status | TEXT | `unbooked\|booked\|confirmed\|cancelled` |

### todos
Actionable tasks with priority and category.

| Column | Type | Notes |
|--------|------|-------|
| trip_id | TEXT FK→trips | |
| task | TEXT | Task description |
| completed | INTEGER | 0/1 |
| priority | TEXT | `low\|normal\|high\|critical` |
| category | TEXT | `booking\|gear\|logistics` |
| itinerary_item_id | INTEGER FK→itinerary_items | Optional link |

### audit_log
Append-only change history (no sync, local only).

| Column | Type | Notes |
|--------|------|-------|
| action | TEXT | `add_place\|schedule_visit\|reschedule\|confirm\|drop` |
| target_type | TEXT | `place\|itinerary_item\|risk\|todo\|hotel` |
| target_uuid | TEXT | UUID of affected record |
| old_value | TEXT | JSON snapshot |
| new_value | TEXT | JSON snapshot |
| actor | TEXT | `agent\|user\|codex\|gemini` |

## Views

| View | Query shortcut | Rows |
|------|---------------|------|
| `v_full_itinerary` | Full schedule with computed day_num, type, joined place data | 46 |
| `v_foods` | `WHERE style IN ('food','coffee')` | 14 |
| `v_attractions` | `WHERE style IN ('nature','tech','culture','landmark')` | 32 |
| `v_hotels` | Hotels with day_num_in/day_num_out | 7 |
| `day_summary` | Per-day: stop_count, confirmed/pending, total_minutes, route | 9 |
| `open_risks` | `WHERE status = 'open'` | 7 |
| `incomplete_todos` | `WHERE completed = 0`, priority-sorted | 11 |
| `unscheduled_places` | Places not in any active itinerary | 0 |
| `v_pending_sync` | UNION of items needing Notion push | 60 |
| `v_reservations` | Reservations with linked place names | 5 |

## Triggers

| Trigger | Effect |
|---------|--------|
| `*_updated` (×6) | Auto-set `updated_at` on any UPDATE (recursion-guarded) |
| `*_sync_dirty` (×3) | Auto-mark `sync_status='modified'` when synced content changes |

## Common Agent Queries

```sql
-- Day schedule
SELECT name_en, name_cn, time_start, time_end, style, city
FROM v_full_itinerary WHERE day_num = 3;

-- Food stops
SELECT name_en, time_start, city FROM v_foods WHERE day_num = 5;

-- Day overview
SELECT day_num, date, stop_count, total_minutes, route FROM day_summary;

-- What needs booking?
SELECT * FROM incomplete_todos WHERE category = 'booking';

-- Unresolved risks
SELECT category, risk, action_required FROM open_risks;

-- Hotel status
SELECT city, check_in, nights, booking_status FROM v_hotels;

-- What hasn't been pushed to Notion?
SELECT entity_type, COUNT(*) FROM v_pending_sync GROUP BY entity_type;
```

## Style Distribution

| Style | Count | Maps to Notion Type |
|-------|-------|-------------------|
| nature | 15 | Attractions |
| culture | 11 | Attractions |
| food | 8 | Food |
| coffee | 6 | Food |
| tech | 5 | Attractions |
| landmark | 1 | Attractions |
