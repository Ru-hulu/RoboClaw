"""Regression tests for dashboard recording serial-control races."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboclaw.embodied.command.headless_patch import apply_record_loop_patch
from roboclaw.embodied.service import EmbodiedService


def _record_loop_module(callback):
    def record_loop(
        robot=None,
        events=None,
        fps: int = 30,
        teleop_action_processor=None,
        robot_action_processor=None,
        robot_observation_processor=None,
        dataset=None,
        **kwargs,
    ):
        return callback(events=events, dataset=dataset)

    return SimpleNamespace(record_loop=record_loop)


def test_stale_skip_event_is_cleared_before_next_episode() -> None:
    seen_events = []

    def capture(*args, **kwargs):
        seen_events.append(dict(kwargs["events"]))
        return "ok"

    module = _record_loop_module(capture)
    events = {"exit_early": True, "rerecord_episode": False, "stop_recording": False}
    apply_record_loop_patch(module)

    assert module.record_loop(events=events, dataset=object()) == "ok"
    assert events["exit_early"] is False
    assert seen_events == [{"exit_early": False, "rerecord_episode": False, "stop_recording": False}]


def test_rerecord_and_stop_events_are_not_cleared() -> None:
    seen_events = []

    def capture(*args, **kwargs):
        seen_events.append(dict(kwargs["events"]))
        return "ok"

    module = _record_loop_module(capture)
    apply_record_loop_patch(module)

    rerecord = {"exit_early": True, "rerecord_episode": True, "stop_recording": False}
    stop = {"exit_early": True, "rerecord_episode": False, "stop_recording": True}
    assert module.record_loop(events=rerecord, dataset=object()) == "ok"
    assert module.record_loop(events=stop, dataset=object()) == "ok"
    assert seen_events == [rerecord, stop]


def test_reset_loop_connection_error_after_skip_is_suppressed() -> None:
    def fail(*args, **kwargs):
        raise ConnectionError("Failed to sync read 'Present_Position'. There is no status packet!")

    module = _record_loop_module(fail)
    events = {"exit_early": True, "rerecord_episode": False, "stop_recording": False}
    apply_record_loop_patch(module)

    assert module.record_loop(events=events, dataset=None) is None
    assert events["exit_early"] is False


def test_reset_loop_connection_error_suppression_is_context_based() -> None:
    def fail(*args, **kwargs):
        raise ConnectionError("permission denied")

    module = _record_loop_module(fail)
    events = {"exit_early": True, "rerecord_episode": False, "stop_recording": False}
    apply_record_loop_patch(module)

    assert module.record_loop(events=events, dataset=None) is None
    assert events["exit_early"] is False


def test_episode_loop_connection_error_after_save_is_not_suppressed() -> None:
    def fail(*args, **kwargs):
        raise ConnectionError("Failed to sync read 'Present_Position'. There is no status packet!")

    module = _record_loop_module(fail)
    events = {"exit_early": True, "rerecord_episode": False, "stop_recording": False}
    apply_record_loop_patch(module)

    with pytest.raises(ConnectionError, match="no status packet"):
        module.record_loop(events=events, dataset=object())


def test_record_loop_patch_requires_keyword_events() -> None:
    def capture(*args, **kwargs):
        return "ok"

    module = SimpleNamespace(record_loop=capture)
    events = {"exit_early": True, "rerecord_episode": False, "stop_recording": False}
    apply_record_loop_patch(module)

    with pytest.raises(RuntimeError, match="keyword argument 'events'"):
        module.record_loop(object(), events, dataset=None)


def test_servo_positions_are_blocked_while_operation_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EmbodiedService()
    service._active_operation = SimpleNamespace(busy=True)

    def fail_if_called() -> bool:
        raise AssertionError("servo polling must not touch the hardware lock while busy")

    monkeypatch.setattr(service._file_lock, "try_shared", fail_if_called)

    assert service.read_servo_positions() == {"error": "busy", "arms": {}}


def test_servo_positions_hold_service_lock_while_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EmbodiedService()
    calls = []

    monkeypatch.setattr(service._file_lock, "try_shared", lambda: True)
    monkeypatch.setattr(service._file_lock, "release_shared", lambda: calls.append("release"))

    def fake_read_servo_positions(arms):
        assert service._lock.locked()
        calls.append("read")
        return {"error": None, "arms": {}}

    import roboclaw.embodied.embodiment.hardware.motors as motors

    monkeypatch.setattr(motors, "read_servo_positions", fake_read_servo_positions)

    assert service.read_servo_positions() == {"error": None, "arms": {}}
    assert calls == ["read", "release"]
