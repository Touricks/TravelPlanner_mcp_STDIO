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


class TestInitialProgress:
    def test_search_pois_emits_progress_zero(self, spy_ctx, monkeypatch):
        from mcp_server import server
        from mcp_server.workflow import WorkflowState

        fake_state = type("S", (), {
            "status": "active",
            "session_id": "test-session",
            "trip_id": "test-trip",
            "current_stage": "poi_search",
            "complete_stage": lambda self, s: None,
        })()

        monkeypatch.setattr(WorkflowState, "load", lambda sid: fake_state)
        monkeypatch.setattr(server, "_build_poi_search_prompt", lambda s, **kw: "prompt")
        monkeypatch.setattr(server, "_run_codex_search", AsyncMock(return_value="raw"))
        monkeypatch.setattr(server, "_run_claude_transform", AsyncMock(return_value={"candidates": []}))
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
