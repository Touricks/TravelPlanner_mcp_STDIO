-- ═══════════════════════════════════════════════════════════════
-- travel.db — Agent-first travel planner backend (v4)
-- Created: 2026-03-21     Updated: 2026-04-04
-- Reviewed by: Codex (GPT-5.4)
-- v4: session isolation + MCP artifact bridge (feat4)
-- ═══════════════════════════════════════════════════════════════
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Helper: UUID v4 generator expression (reused across tables)
-- Usage: DEFAULT (uuid4()) — but SQLite doesn't support custom functions in DDL,
-- so we inline the expression in each table.

-- ───────────────────────────────────────────────────────────────
-- Trips
-- ───────────────────────────────────────────────────────────────
CREATE TABLE trips (
  id              TEXT PRIMARY KEY,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  destination     TEXT NOT NULL,
  start_date      TEXT NOT NULL,
  end_date        TEXT NOT NULL,
  version         INTEGER DEFAULT 1,
  notion_page_id  TEXT,
  notion_synced_at TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Places — stable metadata about a location
-- A place exists once; it can appear in multiple itineraries.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE places (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  name_en         TEXT NOT NULL,
  name_cn         TEXT,
  style           TEXT NOT NULL CHECK(style IN
                    ('nature','tech','culture','food','landmark','coffee')),
  address         TEXT,
  city            TEXT,
  lat             REAL,
  lng             REAL,
  maps_url        TEXT,
  description     TEXT,
  source          TEXT DEFAULT 'agent'
                  CHECK(source IN ('teammate','tripmate','agent','user')),
  -- Notion sync
  notion_page_id  TEXT,
  notion_db_id    TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  deleted_at      TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Itinerary Items — a scheduled visit to a place
-- Same place can appear multiple times (Day 1 dinner + Day 9 revisit).
-- Each row maps to one Notion page in the Travel Itinerary DB.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE itinerary_items (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  session_id      TEXT REFERENCES sessions(id),               -- v4: MCP session provenance
  place_id        INTEGER NOT NULL REFERENCES places(id),
  date            TEXT NOT NULL,
  time_start      TEXT,
  time_end        TEXT,
  duration_minutes INTEGER,
  group_region    TEXT,
  notes           TEXT,
  decision        TEXT DEFAULT 'pending'
                  CHECK(decision IN ('pending','confirmed','rejected')),
  visited         INTEGER DEFAULT 0,
  sort_order      REAL,
  -- Scheduling metadata (Codex-reviewed, 2026-03-21)
  parent_item_id  INTEGER REFERENCES itinerary_items(id),  -- nested activity link
  preceding_travel_minutes INTEGER,                         -- drive time INTO this item
  arrival_buffer_minutes   INTEGER,                         -- parking/check-in buffer
  timing_type     TEXT DEFAULT 'flexible'
                  CHECK(timing_type IN ('fixed','flexible','windowed')),
  -- Notion sync
  notion_page_id  TEXT,
  notion_db_id    TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  deleted_at      TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Hotels — accommodation bookings
-- One row per stay (not per night). Three Rivers 2-night stay = 1 row.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE hotels (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  session_id      TEXT REFERENCES sessions(id),               -- v4: MCP session provenance
  city            TEXT NOT NULL,
  hotel_name      TEXT,
  address         TEXT,
  check_in        TEXT NOT NULL,
  check_out       TEXT NOT NULL,
  nights          INTEGER GENERATED ALWAYS AS
                    (CAST(julianday(check_out) - julianday(check_in) AS INTEGER)) STORED,
  booking_status  TEXT DEFAULT 'unbooked'
                  CHECK(booking_status IN ('unbooked','booked','confirmed','cancelled')),
  cost_per_night  REAL,
  total_cost      REAL,
  currency        TEXT DEFAULT 'USD',
  confirmation_number TEXT,
  booking_url     TEXT,
  notes           TEXT,
  -- Notion sync
  notion_page_id  TEXT,
  notion_db_id    TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  deleted_at      TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Risks — warnings with resolution tracking
-- ───────────────────────────────────────────────────────────────
CREATE TABLE risks (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  session_id      TEXT REFERENCES sessions(id),               -- v4: MCP session provenance
  category        TEXT NOT NULL CHECK(category IN
                    ('vehicle','road','tickets','weather','health','logistics','gear')),
  risk            TEXT NOT NULL,
  detail          TEXT,
  action_required TEXT,
  status          TEXT DEFAULT 'open'
                  CHECK(status IN ('open','mitigated','resolved')),
  resolved_at     TEXT,
  resolution      TEXT,
  source          TEXT,
  -- Notion sync
  notion_page_id  TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  deleted_at      TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Reservations — advance tickets & bookings linked to places
-- ───────────────────────────────────────────────────────────────
CREATE TABLE reservations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  place_id        INTEGER REFERENCES places(id),
  attraction      TEXT NOT NULL,
  booking_required INTEGER NOT NULL DEFAULT 1,
  cost_per_person REAL,
  currency        TEXT DEFAULT 'USD',
  cost_notes      TEXT,
  book_ahead      TEXT,
  booking_url     TEXT,
  booking_status  TEXT DEFAULT 'unbooked'
                  CHECK(booking_status IN ('unbooked','booked','confirmed','cancelled')),
  confirmation_number TEXT,
  notes           TEXT,
  -- Notion sync
  notion_page_id  TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Todos — actionable tasks
-- ───────────────────────────────────────────────────────────────
CREATE TABLE todos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid            TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(4)) || '-'
                    || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2)
                    || '-' || substr('89ab', abs(random()) % 4 + 1, 1)
                    || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))),
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  task            TEXT NOT NULL,
  completed       INTEGER DEFAULT 0,
  due_date        TEXT,
  priority        TEXT DEFAULT 'normal'
                  CHECK(priority IN ('low','normal','high','critical')),
  category        TEXT,
  source          TEXT DEFAULT 'md_export',
  itinerary_item_id INTEGER REFERENCES itinerary_items(id),
  -- Notion sync
  notion_page_id  TEXT,
  sync_status     TEXT DEFAULT 'pending'
                  CHECK(sync_status IN ('pending','synced','modified','error')),
  last_synced_at  TEXT,
  -- Lifecycle
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Audit Log — append-only change history
-- ───────────────────────────────────────────────────────────────
CREATE TABLE audit_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  trip_id         TEXT,
  session_id      TEXT,                                       -- v4: MCP session provenance
  action          TEXT NOT NULL,
  target_type     TEXT NOT NULL,
  target_uuid     TEXT,
  old_value       TEXT,
  new_value       TEXT,
  actor           TEXT DEFAULT 'agent',
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────────────────────────────────────────────
-- Sessions — MCP workflow session tracking (v4)
-- N:1 relationship to trips; multiple sessions can plan the same trip.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,                            -- 12-char hex from MCP
  trip_id         TEXT NOT NULL REFERENCES trips(id),
  status          TEXT DEFAULT 'active'
                  CHECK(status IN ('active','complete','cancelled')),
  source          TEXT DEFAULT 'mcp'
                  CHECK(source IN ('mcp','cli','migration')),
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  completed_at    TEXT
);

-- ───────────────────────────────────────────────────────────────
-- Session Places — provenance: which session discovered which place (v4)
-- Separates place identity (places table) from session membership.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE session_places (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT NOT NULL REFERENCES sessions(id),
  place_id        INTEGER NOT NULL REFERENCES places(id),
  candidate_id    TEXT NOT NULL,                               -- sha256(name_en|address)[:12]
  artifact_type   TEXT DEFAULT 'poi_search'
                  CHECK(artifact_type IN ('poi_search','restaurants')),
  source_rank     INTEGER,                                     -- position in artifact (informational)
  discovered_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(session_id, place_id, artifact_type)
);

-- ───────────────────────────────────────────────────────────────
-- Bridge Sync — tracks JSON artifact → SQLite sync state (v4)
-- SQLite is a materialized projection of JSON artifacts.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE bridge_sync (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT NOT NULL REFERENCES sessions(id),
  artifact_type   TEXT NOT NULL,                               -- poi_search, scheduling, etc.
  artifact_hash   TEXT,                                        -- SHA256[:16] for change detection
  sync_state      TEXT DEFAULT 'pending'
                  CHECK(sync_state IN ('pending','synced','failed','stale')),
  rows_imported   INTEGER DEFAULT 0,
  last_error      TEXT,
  synced_at       TEXT,
  created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(session_id, artifact_type)
);

-- ═══════════════════════════════════════════════════════════════
-- Indexes (v4: session isolation)
-- ═══════════════════════════════════════════════════════════════

CREATE INDEX idx_itinerary_session ON itinerary_items(session_id)
  WHERE session_id IS NOT NULL;
CREATE INDEX idx_hotels_session ON hotels(session_id)
  WHERE session_id IS NOT NULL;
CREATE INDEX idx_risks_session ON risks(session_id)
  WHERE session_id IS NOT NULL;
CREATE INDEX idx_session_places_candidate ON session_places(candidate_id);
CREATE INDEX idx_session_places_session ON session_places(session_id);

-- ═══════════════════════════════════════════════════════════════
-- Triggers
-- ═══════════════════════════════════════════════════════════════

-- Auto-update updated_at (with recursion guard)
CREATE TRIGGER places_updated AFTER UPDATE ON places
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE places SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

CREATE TRIGGER itinerary_updated AFTER UPDATE ON itinerary_items
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE itinerary_items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

CREATE TRIGGER hotels_updated AFTER UPDATE ON hotels
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE hotels SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

CREATE TRIGGER risks_updated AFTER UPDATE ON risks
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE risks SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

CREATE TRIGGER reservations_updated AFTER UPDATE ON reservations
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE reservations SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

CREATE TRIGGER todos_updated AFTER UPDATE ON todos
  WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE todos SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE id = NEW.id;
END;

-- Auto-dirty sync_status when synced content changes
CREATE TRIGGER places_sync_dirty AFTER UPDATE ON places
  WHEN OLD.sync_status = 'synced'
    AND (NEW.name_en IS NOT OLD.name_en OR NEW.name_cn IS NOT OLD.name_cn
         OR NEW.style IS NOT OLD.style OR NEW.address IS NOT OLD.address
         OR NEW.description IS NOT OLD.description)
BEGIN
  UPDATE places SET sync_status = 'modified' WHERE id = NEW.id;
END;

CREATE TRIGGER itinerary_sync_dirty AFTER UPDATE ON itinerary_items
  WHEN OLD.sync_status = 'synced'
    AND (NEW.date IS NOT OLD.date OR NEW.time_start IS NOT OLD.time_start
         OR NEW.decision IS NOT OLD.decision OR NEW.notes IS NOT OLD.notes
         OR NEW.duration_minutes IS NOT OLD.duration_minutes)
BEGIN
  UPDATE itinerary_items SET sync_status = 'modified' WHERE id = NEW.id;
END;

CREATE TRIGGER hotels_sync_dirty AFTER UPDATE ON hotels
  WHEN OLD.sync_status = 'synced'
    AND (NEW.hotel_name IS NOT OLD.hotel_name OR NEW.city IS NOT OLD.city
         OR NEW.check_in IS NOT OLD.check_in OR NEW.check_out IS NOT OLD.check_out
         OR NEW.booking_status IS NOT OLD.booking_status)
BEGIN
  UPDATE hotels SET sync_status = 'modified' WHERE id = NEW.id;
END;

-- ═══════════════════════════════════════════════════════════════
-- Views
-- ═══════════════════════════════════════════════════════════════

-- Full itinerary: everything joined with computed day numbers
CREATE VIEW v_full_itinerary AS
SELECT
  ii.id AS item_id,
  ii.uuid AS item_uuid,
  p.id AS place_id,
  p.uuid AS place_uuid,
  CAST(julianday(ii.date) - julianday(t.start_date) + 1 AS INTEGER) AS day_num,
  'Day ' || CAST(julianday(ii.date) - julianday(t.start_date) + 1 AS INTEGER) AS day_label,
  ii.date,
  ii.time_start,
  ii.time_end,
  p.name_en,
  p.name_cn,
  p.style,
  CASE WHEN p.style IN ('food','coffee') THEN 'Food' ELSE 'Attractions' END AS type,
  p.city,
  p.address,
  p.maps_url,
  ii.duration_minutes,
  ii.group_region,
  ii.decision,
  ii.visited,
  ii.notes AS visit_notes,
  p.description,
  p.source,
  ii.sort_order,
  ii.parent_item_id,
  ii.timing_type,
  ii.preceding_travel_minutes,
  ii.arrival_buffer_minutes,
  ii.sync_status,
  ii.notion_page_id,
  ii.trip_id,
  ii.session_id
FROM itinerary_items ii
JOIN places p ON ii.place_id = p.id
JOIN trips t ON ii.trip_id = t.id
WHERE ii.decision != 'rejected'
  AND ii.deleted_at IS NULL
  AND p.deleted_at IS NULL
ORDER BY ii.date, ii.time_start, ii.sort_order;

-- Food & coffee stops only
CREATE VIEW v_foods AS
SELECT * FROM v_full_itinerary
WHERE style IN ('food', 'coffee')
ORDER BY date, time_start;

-- Attractions only (non-food)
CREATE VIEW v_attractions AS
SELECT * FROM v_full_itinerary
WHERE style IN ('nature', 'tech', 'culture', 'landmark')
ORDER BY date, time_start;

-- Hotels with day numbers
CREATE VIEW v_hotels AS
SELECT
  h.id,
  h.uuid,
  h.city,
  h.hotel_name,
  h.address,
  h.check_in,
  h.check_out,
  h.nights,
  CAST(julianday(h.check_in) - julianday(t.start_date) + 1 AS INTEGER) AS day_num_in,
  CAST(julianday(h.check_out) - julianday(t.start_date) + 1 AS INTEGER) AS day_num_out,
  h.booking_status,
  h.cost_per_night,
  h.total_cost,
  h.confirmation_number,
  h.booking_url,
  h.notes,
  h.sync_status,
  h.trip_id,
  h.session_id
FROM hotels h
JOIN trips t ON h.trip_id = t.id
WHERE h.deleted_at IS NULL
ORDER BY h.check_in;

-- Per-day summary with stop counts and route
CREATE VIEW day_summary AS
SELECT
  CAST(julianday(ii.date) - julianday(t.start_date) + 1 AS INTEGER) AS day_num,
  ii.date,
  ii.group_region,
  COUNT(*) AS stop_count,
  SUM(CASE WHEN ii.decision = 'confirmed' THEN 1 ELSE 0 END) AS confirmed,
  SUM(CASE WHEN ii.decision = 'pending' THEN 1 ELSE 0 END) AS pending,
  SUM(ii.duration_minutes) AS total_minutes,
  GROUP_CONCAT(p.name_en, ' → ') AS route
FROM itinerary_items ii
JOIN places p ON ii.place_id = p.id
JOIN trips t ON ii.trip_id = t.id
WHERE ii.decision != 'rejected' AND ii.deleted_at IS NULL
GROUP BY ii.date
ORDER BY ii.date;

-- Open risks
CREATE VIEW open_risks AS
SELECT r.*, t.destination
FROM risks r
JOIN trips t ON r.trip_id = t.id
WHERE r.status = 'open' AND r.deleted_at IS NULL
ORDER BY r.category;

-- Incomplete todos ordered by priority
CREATE VIEW incomplete_todos AS
SELECT td.*, t.destination
FROM todos td
JOIN trips t ON td.trip_id = t.id
WHERE td.completed = 0
ORDER BY
  CASE td.priority
    WHEN 'critical' THEN 0 WHEN 'high' THEN 1
    WHEN 'normal' THEN 2 WHEN 'low' THEN 3
  END,
  td.due_date;

-- Places not currently scheduled
CREATE VIEW unscheduled_places AS
SELECT p.*
FROM places p
WHERE p.deleted_at IS NULL
  AND p.id NOT IN (
    SELECT place_id FROM itinerary_items
    WHERE deleted_at IS NULL AND decision != 'rejected'
  );

-- Items needing Notion push (all syncable entity types)
CREATE VIEW v_pending_sync AS
SELECT 'itinerary_item' AS entity_type, uuid, sync_status, last_synced_at
FROM itinerary_items WHERE sync_status IN ('pending', 'modified') AND deleted_at IS NULL
UNION ALL
SELECT 'hotel', uuid, sync_status, last_synced_at
FROM hotels WHERE sync_status IN ('pending', 'modified') AND deleted_at IS NULL
UNION ALL
SELECT 'risk', uuid, sync_status, last_synced_at
FROM risks WHERE sync_status IN ('pending', 'modified') AND deleted_at IS NULL
UNION ALL
SELECT 'place', uuid, sync_status, last_synced_at
FROM places WHERE sync_status IN ('pending', 'modified') AND deleted_at IS NULL
UNION ALL
SELECT 'todo', uuid, sync_status, last_synced_at
FROM todos WHERE sync_status IN ('pending', 'modified')
UNION ALL
SELECT 'reservation', uuid, sync_status, last_synced_at
FROM reservations WHERE sync_status IN ('pending', 'modified');

-- Reservations with linked place info
CREATE VIEW v_reservations AS
SELECT
  r.*,
  p.name_en AS place_name,
  p.city AS place_city,
  p.maps_url
FROM reservations r
LEFT JOIN places p ON r.place_id = p.id
ORDER BY r.booking_required DESC, r.attraction;
