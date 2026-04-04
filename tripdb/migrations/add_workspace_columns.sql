-- Migration: add workspace_id and workspace_tag to sessions table
-- Run against existing travel.db databases.
-- workspace_id: server-generated 12-char hex, used for cross-conversation resume
-- workspace_tag: optional human-readable label (e.g., "miami-trip")

ALTER TABLE sessions ADD COLUMN workspace_id TEXT;
ALTER TABLE sessions ADD COLUMN workspace_tag TEXT;
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)
  WHERE workspace_id IS NOT NULL;
