"""Minimal embodied data collection utilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from roboclaw.embodied.execution.orchestration.skills import SkillSpec
from roboclaw.embodied.execution.orchestration.supervision import record_episode

if TYPE_CHECKING:
    from roboclaw.embodied.execution.orchestration.runtime.executor import ExecutionContext, ProcedureExecutor
    from roboclaw.embodied.execution.orchestration.supervision import EpisodeSupervisor

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: int
    skill_name: str
    steps: tuple[dict[str, Any], ...]
    ok: bool


@dataclass(frozen=True)
class CollectionResult:
    ok: bool
    dataset_path: str
    episodes_requested: int
    episodes_completed: int
    episodes_failed: int
    message: str

async def collect_episodes(
    executor: ProcedureExecutor,
    context: ExecutionContext,
    skill: SkillSpec,
    num_episodes: int,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    supervisor: EpisodeSupervisor | None = None,
) -> CollectionResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "dataset.jsonl"
    completed = 0
    failed = 0

    for episode_id in range(1, num_episodes + 1):
        verdict = None
        if supervisor is None:
            reset_result = await executor.execute_reset(context)
            record_data = (
                await record_episode(executor, context, skill, episode_id, on_progress=on_progress)
                if reset_result.ok
                else {"episode_id": episode_id, "skill_name": skill.name, "steps": [], "ok": False}
            )
        else:
            retries = 0
            while True:
                record_data, verdict = await supervisor.supervise_episode(
                    executor, context, skill, episode_id, on_progress=on_progress
                )
                if not verdict.should_retry or retries >= 2:
                    break
                retries += 1
                if on_progress is not None:
                    await on_progress(f"Retrying episode {episode_id}/{num_episodes} ({retries}/2): {verdict.reason}.")

        record = EpisodeRecord(
            episode_id=record_data["episode_id"],
            skill_name=record_data["skill_name"],
            steps=tuple(record_data["steps"]),
            ok=bool(record_data["ok"]) if verdict is None else verdict.success,
        )
        with dataset_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        completed += int(record.ok)
        failed += int(not record.ok)
        if on_progress is not None:
            await on_progress(f"Episode {episode_id}/{num_episodes} completed ({'ok' if record.ok else 'failed'}).")

    message = f"Collected {completed} episodes of {skill.name}. Dataset saved."
    if failed:
        message = f"Collected {completed} of {num_episodes} episodes of {skill.name}. Dataset saved."
    return CollectionResult(
        ok=failed == 0,
        dataset_path=str(dataset_path),
        episodes_requested=num_episodes,
        episodes_completed=completed,
        episodes_failed=failed,
        message=message,
    )
