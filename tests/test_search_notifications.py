"""Diagnostic tests for search heartbeat and progress notifications (BUG-007)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class SpyContext:
    def __init__(self):
        self.info = AsyncMock()
        self.error = AsyncMock()
        self.report_progress = AsyncMock()


@pytest.fixture
def spy_ctx():
    return SpyContext()


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch):
    from mcp_server import config
    monkeypatch.setattr(config, "CODEX_SEARCH_TIMEOUT_SECONDS", 5)


def _patch_subprocess(monkeypatch, delay: float, stdout: bytes = b"fake output"):
    class FakeProc:
        returncode = 0
        async def communicate(self):
            await asyncio.sleep(delay)
            return stdout, b""
        def kill(self):
            pass
        async def wait(self):
            pass

    async def factory(*a, **kw):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", factory)


class TestHeartbeatFires:
    def test_heartbeat_sends_info_and_progress(self, spy_ctx, monkeypatch):
        from mcp_server import server

        heartbeat_interval = 0.02
        proc_delay = 0.10

        _patch_subprocess(monkeypatch, delay=proc_delay)
        original_sleep = asyncio.sleep

        async def fast_sleep(n):
            if n >= 10:
                await original_sleep(heartbeat_interval)
            else:
                await original_sleep(n)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        result = _run_async(server._run_codex_search("test prompt", ctx=spy_ctx))
        assert result == "fake output"
        assert spy_ctx.info.call_count >= 1
        assert spy_ctx.report_progress.call_count >= 1

    def test_heartbeat_exception_does_not_kill_loop(self, monkeypatch):
        from mcp_server import server

        ctx = SpyContext()
        call_count = 0

        async def flaky_info(msg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transport error")

        ctx.info = flaky_info
        heartbeat_interval = 0.02
        proc_delay = 0.10

        _patch_subprocess(monkeypatch, delay=proc_delay)
        original_sleep = asyncio.sleep

        async def fast_sleep(n):
            if n >= 10:
                await original_sleep(heartbeat_interval)
            else:
                await original_sleep(n)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        result = _run_async(server._run_codex_search("test prompt", ctx=ctx))
        assert result == "fake output"
        assert call_count >= 2

    def test_timeout_cancels_heartbeat_cleanly(self, spy_ctx, monkeypatch):
        from mcp_server import config, server

        monkeypatch.setattr(config, "CODEX_SEARCH_TIMEOUT_SECONDS", 0.1)

        class HangingProc:
            returncode = 1
            async def communicate(self):
                await asyncio.sleep(999)
                return b"", b""
            def kill(self):
                pass
            async def wait(self):
                pass

        async def factory(*a, **kw):
            return HangingProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", factory)

        with pytest.raises(server.SearchError, match="timed out"):
            _run_async(server._run_codex_search("test prompt", ctx=spy_ctx))


def _patch_parallel_config(monkeypatch, tmp_path):
    """Shared setup for parallel search tests."""
    from mcp_server import config
    session_dir = tmp_path / "test-session"
    session_dir.mkdir()
    monkeypatch.setattr(config, "session_dir", lambda sid: session_dir)
    monkeypatch.setattr(config, "CODEX_PARALLEL_LIMIT", 5)
    monkeypatch.setattr(config, "CODEX_PER_POI_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(config, "CODEX_SECONDS_PER_POI_SCALING", 1)
    monkeypatch.setattr(config, "CODEX_SEARCH_MAX_RETRIES", 0)
    monkeypatch.setattr(config, "TRANSFORM_PARALLEL_LIMIT", 3)
    monkeypatch.setattr(config, "TRANSFORM_PER_POI_TIMEOUT_SECONDS", 5)
    return session_dir


def _make_fake_state():
    return type("S", (), {
        "status": "active",
        "session_id": "test-session",
        "trip_id": "test-trip",
    })()


class TestInitialProgress:
    def test_search_pois_emits_progress_zero(self, spy_ctx, monkeypatch, tmp_path):
        import json

        from mcp_server import config, server
        from mcp_server.workflow import WorkflowState

        session_dir = tmp_path / "test-session"
        session_dir.mkdir()
        (session_dir / "poi-names.json").write_text(json.dumps({
            "destination": "Test",
            "poi_names": [{"name_en": "Test POI", "priority": "must_visit"}],
        }))
        monkeypatch.setattr(config, "session_dir", lambda sid: session_dir)

        fake_state = type("S", (), {
            "status": "active",
            "session_id": "test-session",
            "trip_id": "test-trip",
            "current_stage": "poi_search",
            "complete_stage": lambda self, s: None,
        })()

        monkeypatch.setattr(WorkflowState, "load", lambda sid: fake_state)
        monkeypatch.setattr(server, "_search_pois_parallel", AsyncMock(
            return_value=({"destination": "Test", "candidates": []}, [])
        ))
        monkeypatch.setattr(server, "validation", type("V", (), {
            "validate_schema": staticmethod(lambda *a: [])
        })())
        monkeypatch.setattr(server, "artifact_store", type("A", (), {
            "save_artifact": staticmethod(lambda *a: None),
            "load_artifact": staticmethod(lambda *a: None),
        })())
        monkeypatch.setattr(server, "_bridge_call", lambda *a: None)
        monkeypatch.setattr(server, "_build_action", lambda s: {})

        result = _run_async(server.search_pois(session_id="test-session", ctx=spy_ctx))

        progress_calls = spy_ctx.report_progress.call_args_list
        assert len(progress_calls) >= 1
        first = progress_calls[0]
        assert first.kwargs.get("progress", first.args[0] if first.args else None) == 0
        assert first.kwargs.get("total", first.args[1] if len(first.args) > 1 else None) == 4


class TestParallelPOISearch:
    def test_partial_failure_continues(self, monkeypatch, tmp_path):
        from mcp_server import server

        session_dir = _patch_parallel_config(monkeypatch, tmp_path)

        call_count = 0

        async def fake_codex(prompt, ctx=None, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise server.SearchError("timeout")
            return f"raw data for POI {call_count}"

        async def fake_transform(prompt, schema_path, timeout=None):
            return {
                "name_en": "Test",
                "style": "landmark",
                "address": "123 Test St",
                "duration_minutes": 60,
                "description": "A test POI",
            }

        monkeypatch.setattr(server, "_run_codex_search", fake_codex)
        monkeypatch.setattr(server, "_run_claude_transform", fake_transform)
        monkeypatch.setattr(server, "_load_trip_prefs", lambda tid: {
            "destination": "Test City",
        })
        monkeypatch.setattr(server, "_load_merged_profile_from_prefs", lambda tid, prefs: {})

        fake_state = _make_fake_state()
        poi_list = [{"name_en": f"POI {i}"} for i in range(5)]
        result, failures = _run_async(
            server._search_pois_parallel(fake_state, poi_list)
        )

        search_failures = [f for f in failures if "timeout" in f.get("error", "")]
        assert len(search_failures) == 2
        assert len(result["candidates"]) == 3

    def test_majority_failure_raises(self, monkeypatch, tmp_path):
        from mcp_server import server

        _patch_parallel_config(monkeypatch, tmp_path)

        call_count = 0

        async def fake_codex(prompt, ctx=None, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                raise server.SearchError("timeout")
            return "raw data"

        monkeypatch.setattr(server, "_run_codex_search", fake_codex)
        monkeypatch.setattr(server, "_load_trip_prefs", lambda tid: {
            "destination": "Test City",
        })
        monkeypatch.setattr(server, "_load_merged_profile_from_prefs", lambda tid, prefs: {})

        fake_state = _make_fake_state()
        poi_list = [{"name_en": f"POI {i}"} for i in range(5)]
        with pytest.raises(server.SearchError, match="Majority"):
            _run_async(server._search_pois_parallel(fake_state, poi_list))

    def test_progress_file_updated(self, monkeypatch, tmp_path):
        import json

        from mcp_server import server

        session_dir = _patch_parallel_config(monkeypatch, tmp_path)

        async def fake_codex(prompt, ctx=None, timeout=None):
            return "raw data"

        async def fake_transform(prompt, schema_path, timeout=None):
            return {
                "name_en": "Test",
                "style": "landmark",
                "address": "123 Test St",
                "duration_minutes": 60,
                "description": "A test POI",
            }

        monkeypatch.setattr(server, "_run_codex_search", fake_codex)
        monkeypatch.setattr(server, "_run_claude_transform", fake_transform)
        monkeypatch.setattr(server, "_load_trip_prefs", lambda tid: {
            "destination": "Test City",
        })
        monkeypatch.setattr(server, "_load_merged_profile_from_prefs", lambda tid, prefs: {})

        fake_state = _make_fake_state()
        poi_list = [{"name_en": f"POI {i}"} for i in range(3)]
        _run_async(server._search_pois_parallel(fake_state, poi_list))

        progress_path = session_dir / "poi-search-progress.json"
        assert progress_path.exists()
        progress = json.loads(progress_path.read_text())
        assert progress["phase"] == "transforming"
        assert progress["total"] == 3


class TestSanitizePoiFilename:
    def test_basic_name(self):
        from mcp_server.server import _sanitize_poi_filename
        result = _sanitize_poi_filename("Bixby Bridge")
        assert result.startswith("bixby-bridge-")
        assert len(result) <= 87

    def test_unicode_name(self):
        from mcp_server.server import _sanitize_poi_filename
        result = _sanitize_poi_filename("金门大桥")
        assert len(result) == 6

    def test_long_name_truncated(self):
        from mcp_server.server import _sanitize_poi_filename
        long_name = "a" * 200
        result = _sanitize_poi_filename(long_name)
        assert len(result) <= 87


class TestMergePoiTransforms:
    def test_merge_filters_failures(self):
        from mcp_server.server import _merge_poi_transforms
        results = [
            {"name_en": "A", "status": "complete", "candidate": {"name_en": "A", "style": "food", "address": "1 St", "duration_minutes": 30, "description": "Good"}},
            {"name_en": "B", "status": "failed", "error": "timeout"},
            {"name_en": "C", "status": "complete", "candidate": {"name_en": "C", "style": "nature", "address": "2 St", "duration_minutes": 60, "description": "Nice"}},
        ]
        merged = _merge_poi_transforms("Test City", results)
        assert merged["destination"] == "Test City"
        assert len(merged["candidates"]) == 2

    def test_merge_empty(self):
        from mcp_server.server import _merge_poi_transforms
        merged = _merge_poi_transforms("Test", [])
        assert merged["candidates"] == []
