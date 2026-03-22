from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.orchestration.procedures.model import ProcedureKind
from roboclaw.embodied.execution.orchestration.skills import SkillSpec, SkillStep, execute_skill


def test_skill_spec_creation() -> None:
    skill = SkillSpec("reset_arm", "Reset arm.", (SkillStep("go_named_pose", {"name": "home"}),), ("pose",))
    assert skill.name == "reset_arm"
    assert skill.steps[0].primitive_name == "go_named_pose"
    assert skill.parameters == ("pose",)


@pytest.mark.asyncio
async def test_execute_skill_runs_all_steps() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def execute_move(context, *, primitive_name, primitive_args=None, on_progress=None):
        calls.append((primitive_name, primitive_args or {}))
        return SimpleNamespace(procedure=ProcedureKind.MOVE, ok=True, message=f"{primitive_name} ok", details={})

    result = await execute_skill(
        SimpleNamespace(execute_move=execute_move),
        SimpleNamespace(setup_id="demo"),
        SkillSpec("reset_arm", "Reset arm.", (SkillStep("go_named_pose", {"name": "home"}), SkillStep("gripper_open"))),
        {},
        None,
    )

    assert result.ok is True
    assert calls == [("go_named_pose", {"name": "home"}), ("gripper_open", {})]
    assert len(result.details["completed_steps"]) == 2


@pytest.mark.asyncio
async def test_execute_skill_stops_on_first_failure() -> None:
    calls: list[str] = []

    async def execute_move(context, *, primitive_name, primitive_args=None, on_progress=None):
        calls.append(primitive_name)
        return SimpleNamespace(procedure=ProcedureKind.MOVE, ok=False, message=primitive_name, details={})

    result = await execute_skill(
        SimpleNamespace(execute_move=execute_move),
        SimpleNamespace(setup_id="demo"),
        SkillSpec("reset_arm", "Reset arm.", (SkillStep("go_named_pose"), SkillStep("gripper_open"))),
        {},
        None,
    )

    assert result.ok is False
    assert calls == ["go_named_pose"]


@pytest.mark.asyncio
async def test_execute_skill_reports_step_state_feedback() -> None:
    progress: list[str] = []

    async def on_progress(message: str) -> None:
        progress.append(message)

    async def execute_move(context, *, primitive_name, primitive_args=None, on_progress=None):
        assert on_progress is not None
        return SimpleNamespace(
            procedure=ProcedureKind.MOVE,
            ok=True,
            message=f"{primitive_name} ok",
            details={"state_changed": primitive_name == "go_named_pose", "joints_moved": ["shoulder_pan"]},
        )

    await execute_skill(
        SimpleNamespace(execute_move=execute_move),
        SimpleNamespace(setup_id="demo"),
        SkillSpec("reset_arm", "Reset arm.", (SkillStep("go_named_pose"), SkillStep("gripper_open"))),
        {},
        on_progress,
    )

    assert progress == [
        "Running skill `reset_arm` step 1/2: `go_named_pose`.",
        "Completed skill `reset_arm` step 1/2: `go_named_pose` (state changed: yes).",
        "Running skill `reset_arm` step 2/2: `gripper_open`.",
        "Completed skill `reset_arm` step 2/2: `gripper_open` (state changed: no).",
    ]
