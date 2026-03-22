from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.orchestration.data_collection import collect_episodes
from roboclaw.embodied.execution.orchestration.dataset import EpisodeDataset
from roboclaw.embodied.execution.orchestration.skills import SkillSpec, SkillStep


class FakeExecutor:
    def __init__(self, *, fail_episode: int | None = None) -> None:
        self.fail_episode = fail_episode
        self.episode = 0
        self.step = 0

    async def execute_reset(self, context):
        self.episode += 1
        self.step = 0
        return SimpleNamespace(ok=True, details={})

    async def execute_move(self, context, *, primitive_name, primitive_args=None, on_progress=None):
        self.step += 1
        ok = self.episode != self.fail_episode
        state_before = {"joint_positions": {"joint": self.step - 1}}
        state_after = {"joint_positions": {"joint": self.step if ok else self.step - 1}}
        return SimpleNamespace(ok=ok, details={"state_before": state_before, "state_after": state_after})


@pytest.mark.asyncio
async def test_collect_episodes_creates_structured_dataset(tmp_path: Path) -> None:
    result = await collect_episodes(
        FakeExecutor(),
        SimpleNamespace(setup_id="demo", assembly=SimpleNamespace(sensors=())),
        SkillSpec("pick_and_place", "Pick and place.", (SkillStep("gripper_open"), SkillStep("gripper_close"))),
        num_episodes=2,
        output_dir=tmp_path,
    )

    assert result.ok is True
    assert result.dataset_path == str(tmp_path)
    info = EpisodeDataset.load_info(tmp_path)
    assert info.num_episodes == 2
    assert info.num_frames == 4  # 2 episodes x 2 steps


@pytest.mark.asyncio
async def test_collect_episodes_counts_failed_episodes(tmp_path: Path) -> None:
    result = await collect_episodes(
        FakeExecutor(fail_episode=2),
        SimpleNamespace(setup_id="demo", assembly=SimpleNamespace(sensors=())),
        SkillSpec("pick_and_place", "Pick and place.", (SkillStep("gripper_open"),)),
        num_episodes=2,
        output_dir=tmp_path,
    )

    assert result.ok is False
    assert result.episodes_completed == 1
    assert result.episodes_failed == 1
    info = EpisodeDataset.load_info(tmp_path)
    assert info.num_episodes == 2
    assert info.num_frames == 2  # 2 episodes x 1 step each
