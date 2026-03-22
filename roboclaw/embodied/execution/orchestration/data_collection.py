"""Minimal embodied data collection utilities."""

from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from roboclaw.embodied.execution.orchestration.collection_server import CollectionDashboard
from roboclaw.embodied.execution.orchestration.dataset import EpisodeDataset
from roboclaw.embodied.execution.orchestration.skills import SkillSpec

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


async def capture_sensors(
    adapter: Any, assembly: Any, output_dir: Path | None, episode_id: int, step_idx: int
) -> list[dict[str, Any]]:
    if not (sensors := getattr(assembly, "sensors", ()) or ()) or not hasattr(adapter, "capture_sensor"):
        return []
    captures = []
    for sensor in sensors:
        result = await adapter.capture_sensor(sensor.sensor_id)
        path_or_ref = result.payload_ref
        source = Path(result.payload_ref) if result.payload_ref else None
        if output_dir is not None and result.captured and source and source.is_file():
            ext = source.suffix or mimetypes.guess_extension(result.media_type or "") or ".bin"
            path = output_dir / "frames" / f"{episode_id}_{step_idx}_{sensor.sensor_id}{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, path)
            path_or_ref = str(path)
        captures.append({"sensor_id": result.sensor_id, "captured": result.captured, "media_type": result.media_type, "path_or_ref": path_or_ref})
    return captures


def _timestamp_to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0
    return 0.0

async def collect_episodes(
    executor: ProcedureExecutor,
    context: ExecutionContext,
    skill: SkillSpec,
    num_episodes: int,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    supervisor: EpisodeSupervisor | None = None,
) -> CollectionResult:
    from roboclaw.embodied.execution.orchestration.supervision import record_episode

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = EpisodeDataset(output_dir)
    staging_dir = output_dir / ".staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    completed = 0
    failed = 0
    dashboard: CollectionDashboard | None = CollectionDashboard()
    try:
        await dashboard.start()
        dashboard.update(status="collecting", total_episodes=num_episodes, skill_name=skill.name)
    except OSError:
        dashboard = None

    try:
        for episode_id in range(1, num_episodes + 1):
            async def progress(message: str) -> None:
                if dashboard is not None:
                    dashboard.update(current_episode=episode_id)
                    dashboard.add_log(message)
                if on_progress is not None:
                    await on_progress(message)

            if dashboard is not None:
                dashboard.update(status="collecting", current_episode=episode_id)
            dataset.begin_episode(episode_id)
            verdict = None
            if supervisor is None:
                reset_result = await executor.execute_reset(context)
                record_data = (
                    await record_episode(executor, context, skill, episode_id, output_dir=staging_dir, on_progress=progress)
                    if reset_result.ok
                    else {"episode_id": episode_id, "skill_name": skill.name, "steps": [], "ok": False}
                )
            else:
                retries = 0
                while True:
                    record_data, verdict = await supervisor.supervise_episode(
                        executor, context, skill, episode_id, output_dir=staging_dir, on_progress=progress
                    )
                    if not verdict.should_retry or retries >= 2:
                        break
                    retries += 1
                    await progress(f"Retrying episode {episode_id}/{num_episodes} ({retries}/2): {verdict.reason}.")

            record = EpisodeRecord(
                episode_id=record_data["episode_id"],
                skill_name=record_data["skill_name"],
                steps=tuple(record_data["steps"]),
                ok=bool(record_data["ok"]) if verdict is None else verdict.success,
            )
            for frame_index, step in enumerate(record.steps):
                images = {
                    str(sensor.get("sensor_id") or "image"): Path(path_or_ref)
                    for sensor in step.get("sensors") or ()
                    if sensor.get("captured")
                    and str(sensor.get("media_type") or "").startswith("image/")
                    and (path_or_ref := sensor.get("path_or_ref"))
                    and Path(path_or_ref).is_file()
                }
                dataset.add_frame(
                    episode_index=record.episode_id,
                    frame_index=frame_index,
                    timestamp=_timestamp_to_float(step.get("timestamp")),
                    state=dict(step.get("state_after") or {}),
                    action=dict(step.get("primitive") or {}),
                    images=images or None,
                )
            completed += int(record.ok)
            failed += int(not record.ok)
            if dashboard is not None:
                latest = record.steps[-1] if record.steps else {}
                state = dict(latest.get("state_after") or {})
                dashboard.update(
                    current_episode=episode_id,
                    latest_joints=dict(state.get("joint_positions") or state),
                    latest_sensors=list(latest.get("sensors") or ()),
                    status="ok" if record.ok else "failed",
                )
            await progress(f"Episode {episode_id}/{num_episodes} completed ({'ok' if record.ok else 'failed'}).")
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        if dashboard is not None:
            dashboard.update(status="completed" if failed == 0 else "completed_with_failures", current_episode=completed + failed)
            await dashboard.stop()

    dataset_path = dataset.save(name=skill.name)

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
