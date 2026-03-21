from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.orchestration.skills import SkillSpec, SkillStep
from roboclaw.embodied.execution.orchestration.supervision import EpisodeSupervisor

@pytest.mark.parametrize(
    ("supervisor", "episode", "success", "reason"),
    [
        (EpisodeSupervisor(), {"ok": False, "steps": [{"state_changed": True, "joints_moved": ["joint"]}]}, False, "Skill execution failed"),
        (EpisodeSupervisor(), {"ok": True, "steps": [{"state_changed": False, "joints_moved": []}]}, False, "No state change observed"),
        (
            EpisodeSupervisor(require_state_change=False, min_joints_moved=2),
            {"ok": True, "steps": [{"state_changed": False, "joints_moved": ["joint"]}]},
            False,
            "Insufficient joint movement",
        ),
        (EpisodeSupervisor(), {"ok": True, "steps": [{"state_changed": True, "joints_moved": ["joint"]}]}, True, "Episode completed with observed state changes"),
    ],
)
def test_episode_supervisor_judge(supervisor, episode, success, reason) -> None:
    verdict = supervisor.judge(episode)
    assert verdict.success is success
    assert verdict.reason == reason
    assert verdict.should_retry is (not success)

@pytest.mark.asyncio
async def test_supervise_episode_resets_executes_and_reports_verdict() -> None:
    progress: list[str] = []
    class FakeExecutor:
        def __init__(self) -> None:
            self.reset_calls = 0
            self.move_calls = 0

        async def execute_reset(self, context):
            self.reset_calls += 1
            return SimpleNamespace(ok=True)

        async def execute_move(self, context, *, primitive_name, primitive_args=None, on_progress=None):
            self.move_calls += 1
            return SimpleNamespace(
                ok=True,
                details={
                    "state_before": {"joint_positions": {"joint": 0}},
                    "state_after": {"joint_positions": {"joint": 1}},
                    "state_changed": True,
                    "joints_moved": ["joint"],
                },
            )
    async def on_progress(message: str) -> None:
        progress.append(message)
    executor = FakeExecutor()

    record, verdict = await EpisodeSupervisor().supervise_episode(
        executor,
        SimpleNamespace(setup_id="demo"),
        SkillSpec("pick", "Pick.", (SkillStep("go_named_pose"),)),
        3,
        on_progress,
    )

    assert executor.reset_calls == 1
    assert executor.move_calls == 1
    assert record["episode_id"] == 3
    assert record["ok"] is True
    assert record["steps"][0]["state_changed"] is True
    assert verdict.success is True
    assert progress[-1] == "Episode 3 judged success: Episode completed with observed state changes."
