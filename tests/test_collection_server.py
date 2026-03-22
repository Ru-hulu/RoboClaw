from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.orchestration.collection_server import CollectionDashboard


class _Writer:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_collection_dashboard_serves_state_and_updates() -> None:
    dashboard = CollectionDashboard()
    dashboard.update(status="collecting", current_episode=2, total_episodes=5, latest_joints={"joint": 1.5})
    dashboard.add_log("step complete")
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET /api/state HTTP/1.1\r\nHost: test\r\n\r\n")
    reader.feed_eof()
    writer = _Writer()
    await dashboard._handle_client(reader, writer)
    state = json.loads(bytes(writer.buffer).split(b"\r\n\r\n", 1)[1].decode("utf-8"))
    assert state["status"] == "collecting"
    assert state["current_episode"] == 2
    assert state["total_episodes"] == 5
    assert state["latest_joints"] == {"joint": 1.5}
    assert state["progress_log"][-1] == "step complete"


@pytest.mark.asyncio
async def test_collection_dashboard_start_and_stop() -> None:
    dashboard = CollectionDashboard(host="127.0.0.1", port=0)
    fake_server = SimpleNamespace(
        sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 4321))],
        close=lambda: None,
        wait_closed=lambda: asyncio.sleep(0),
    )
    original = asyncio.start_server

    async def fake_start_server(*args, **kwargs):
        return fake_server

    asyncio.start_server = fake_start_server
    try:
        await dashboard.start()
        assert dashboard.port == 4321
        await dashboard.stop()
    finally:
        asyncio.start_server = original
