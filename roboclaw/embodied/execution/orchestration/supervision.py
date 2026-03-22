"""Minimal rule-based supervision for embodied episode execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from roboclaw.embodied.execution.orchestration.data_collection import capture_sensors
from roboclaw.embodied.execution.orchestration.skills import execute_skill

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_episode(
    executor: Any,
    context: Any,
    skill: Any,
    episode_num: int,
    on_progress: Any = None,
    output_dir: Any = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    class RecordingExecutor:
        async def execute_move(
            self,
            step_context: Any,
            *,
            primitive_name: str,
            primitive_args: dict[str, Any] | None = None,
            on_progress: Any = None,
        ) -> Any:
            result = await executor.execute_move(
                step_context,
                primitive_name=primitive_name,
                primitive_args=primitive_args,
                on_progress=on_progress,
            )
            details = result.details
            adapter = executor._adapter(step_context) if hasattr(executor, "_adapter") else executor
            sensors = await capture_sensors(adapter, getattr(step_context, "assembly", None), output_dir, episode_num, len(steps) + 1)
            steps.append(
                {
                    "timestamp": _now(),
                    "state_before": dict(details.get("state_before") or {}),
                    "state_after": dict(details.get("state_after") or {}),
                    "state_changed": bool(details.get("state_changed")),
                    "joints_moved": list(details.get("joints_moved") or ()),
                    "sensors": sensors,
                    "primitive": {"name": primitive_name, "args": dict(primitive_args or {})},
                    "ok": result.ok,
                }
            )
            return result

    result = await execute_skill(RecordingExecutor(), context, skill, on_progress=on_progress)
    return {"episode_id": episode_num, "skill_name": skill.name, "steps": steps, "ok": bool(result.ok)}


@dataclass(frozen=True)
class EpisodeVerdict:
    success: bool
    reason: str
    should_retry: bool = False
    should_reset: bool = True


class EpisodeSupervisor:
    """Judge episode outcomes based on state changes."""

    def __init__(self, *, min_joints_moved: int = 1, require_state_change: bool = True):
        self.min_joints_moved = min_joints_moved
        self.require_state_change = require_state_change

    def judge(self, episode_result: dict[str, Any]) -> EpisodeVerdict:
        if not episode_result.get("ok"):
            return EpisodeVerdict(False, "Skill execution failed", should_retry=True)
        steps = episode_result.get("steps") or ()
        if self.require_state_change and not any(step.get("state_changed") for step in steps):
            return EpisodeVerdict(False, "No state change observed", should_retry=True)
        joints_moved = sum(len(step.get("joints_moved") or ()) for step in steps)
        if joints_moved < self.min_joints_moved:
            return EpisodeVerdict(False, "Insufficient joint movement", should_retry=True)
        return EpisodeVerdict(True, "Episode completed with observed state changes")

    async def supervise_episode(
        self,
        executor: Any,
        context: Any,
        skill: Any,
        episode_num: int,
        on_progress: Any = None,
        output_dir: Any = None,
    ) -> tuple[dict[str, Any], EpisodeVerdict]:
        reset_result = await executor.execute_reset(context)
        episode = (
            await record_episode(executor, context, skill, episode_num, output_dir=output_dir, on_progress=on_progress)
            if reset_result.ok
            else {"episode_id": episode_num, "skill_name": skill.name, "steps": [], "ok": False}
        )
        verdict = self.judge(episode)
        if on_progress is not None:
            state = "success" if verdict.success else "failed"
            await on_progress(f"Episode {episode_num} judged {state}: {verdict.reason}.")
        return episode, verdict
