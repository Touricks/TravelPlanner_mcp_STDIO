# BUG-007: Search Heartbeat Notifications Invisible to Client

## Symptom

After BUG-003 fix (commit 42409ba), `search_pois` still runs 300s with zero user-visible feedback before returning a timeout error. Client sees nothing between tool invocation and result.

## Root Cause

Two independent failures combine:

### 1. `ctx.report_progress()` is a silent no-op

FastMCP's `report_progress` requires the client to send a `progressToken` in the tool call's `_meta`. Claude Code does not send one. The implementation (`mcp/server/fastmcp/server.py:1170-1173`):

```python
progress_token = self.request_context.meta.progressToken if self.request_context.meta else None
if progress_token is None:
    return  # silent no-op
```

All `report_progress()` calls in the search tools silently do nothing.

### 2. `ctx.info()` heartbeat is not surfaced by the client

The heartbeat sends `ctx.info()` every 30s, which emits `notifications/message` (logging) via JSON-RPC. The stdio transport flushes correctly. However, Claude Code does not display `notifications/message` log notifications inline during tool execution — they go to internal logs only.

### 3. No structured progress during the longest phase

Even if `report_progress` worked, the first call was at line 623 — AFTER the codex subprocess completes. The entire 300s codex phase had zero structured progress events.

## Fix (this commit)

1. **Heartbeat emits `report_progress` alongside `ctx.info()`** — currently still a no-op, but will activate when clients support `progressToken`
2. **Heartbeat is exception-safe** — `ctx.info()` failures no longer silently kill the heartbeat loop
3. **Heartbeat cancellation is properly awaited** — prevents orphaned `ctx.info()` calls
4. **Initial `report_progress(0, 4)` before codex launch** — all three search tools emit structured progress immediately
5. **Server-side `log.info()` per heartbeat** — diagnostic visibility independent of client behavior

## Files Changed

| File | Change |
|------|--------|
| `mcp_server/server.py` | Heartbeat rewrite + initial progress in all 3 search tools |
| `tests/test_search_notifications.py` | Diagnostic tests confirming heartbeat + progress behavior |
