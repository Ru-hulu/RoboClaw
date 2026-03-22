from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.integration.adapters.model import AdapterStateSnapshot, PrimitiveExecutionResult
from roboclaw.embodied.execution.orchestration.inference import InferenceSession, start_inference, stop_inference
from roboclaw.embodied.execution.orchestration.runtime.model import RuntimeStatus


class _Adapter:
    def __init__(self, session: InferenceSession, stop_after: int | None = None) -> None:
        self.session = session
        self.stop_after = stop_after
        self.actions: list[dict[str, float]] = []

    async def get_state(self) -> AdapterStateSnapshot:
        return AdapterStateSnapshot(values={"joint": 1.0})

    async def execute_primitive(self, name: str, args: dict[str, float] | None = None) -> PrimitiveExecutionResult:
        self.actions.append(args or {})
        if self.stop_after is not None and len(self.actions) >= self.stop_after and self.session.stop_event is not None:
            self.session.stop_event.set()
        return PrimitiveExecutionResult(primitive_name=name, accepted=True, completed=True)


class _Executor:
    def __init__(self, adapter: _Adapter) -> None:
        self.adapter = adapter

    async def execute_connect(self, context, on_progress=None):
        context.runtime.status = RuntimeStatus.READY
        return SimpleNamespace(ok=True, message="connected", details={})

    def _adapter(self, context):
        return self.adapter


class _FakePolicy:
    def predict(self, values):
        return {key: 0.0 for key, value in values.items() if isinstance(value, (int, float))}


def _mock_load_policy(monkeypatch):
    monkeypatch.setattr("roboclaw.embodied.execution.orchestration.inference._load_policy", lambda _path: _FakePolicy())


@pytest.mark.asyncio
async def test_start_inference_executes_policy_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    original_sleep = asyncio.sleep
    monkeypatch.setattr("roboclaw.embodied.execution.orchestration.inference.asyncio.sleep", lambda _: original_sleep(0))
    _mock_load_policy(monkeypatch)
    session = InferenceSession(checkpoint_path="policy.ckpt", setup_id="demo")
    adapter = _Adapter(session, stop_after=3)
    result = await start_inference(session, _Executor(adapter), SimpleNamespace(runtime=SimpleNamespace(status=RuntimeStatus.READY, last_error=None)))
    assert result.ok is True
    assert result.steps_completed == 3
    assert adapter.actions == [{"joint": 0.0}] * 3


@pytest.mark.asyncio
async def test_start_inference_fails_on_bad_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy load errors should propagate, not silently fall back to zero actions."""
    session = InferenceSession(checkpoint_path="nonexistent.ckpt", setup_id="demo")
    adapter = _Adapter(session)
    result = await start_inference(session, _Executor(adapter), SimpleNamespace(runtime=SimpleNamespace(status=RuntimeStatus.READY, last_error=None)))
    assert result.ok is False
    assert "Failed to load policy" in result.message


@pytest.mark.asyncio
async def test_stop_inference_stops_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    original_sleep = asyncio.sleep
    monkeypatch.setattr("roboclaw.embodied.execution.orchestration.inference.asyncio.sleep", lambda _: original_sleep(0))
    _mock_load_policy(monkeypatch)
    session = InferenceSession(checkpoint_path="policy.ckpt", setup_id="demo")
    task = asyncio.create_task(start_inference(session, _Executor(_Adapter(session)), SimpleNamespace(runtime=SimpleNamespace(status=RuntimeStatus.READY, last_error=None))))
    while session.steps_completed < 2:
        await asyncio.sleep(0)
    stop = stop_inference(session)
    result = await task
    assert stop.steps_completed >= 2
    assert result.steps_completed >= stop.steps_completed
    assert session.running is False
