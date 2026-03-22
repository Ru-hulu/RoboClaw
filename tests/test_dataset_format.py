from __future__ import annotations

import builtins
import json
from pathlib import Path

from roboclaw.embodied.execution.orchestration.dataset import EpisodeDataset


def test_episode_dataset_saves_info_frames_and_images(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"png-source")
    dataset = EpisodeDataset(tmp_path / "dataset")

    dataset.begin_episode(1)
    dataset.add_frame(
        episode_index=1,
        frame_index=0,
        timestamp=1.25,
        state={"joint": 1},
        action={"name": "close"},
        images={"cam0": b"png-bytes", "cam1": source},
    )
    dataset.begin_episode(2)
    dataset.add_frame(episode_index=2, frame_index=0, timestamp=2.5, state={"joint": 2}, action={"name": "open"})
    root = dataset.save(name="pick", fps=15.0)

    assert root == tmp_path / "dataset"
    assert (root / "images" / "cam0" / "000001" / "000000.png").read_bytes() == b"png-bytes"
    assert (root / "images" / "cam1" / "000001" / "000000.png").read_bytes() == b"png-source"
    assert (root / "data" / "episodes.parquet").exists() or (root / "data" / "episodes.jsonl").exists()
    info = EpisodeDataset.load_info(root)
    assert info == dataset.load_info(root)
    assert info.name == "pick"
    assert info.num_episodes == 2
    assert info.num_frames == 2
    assert info.image_keys == ("cam0", "cam1")


def test_episode_dataset_falls_back_to_jsonl_without_pyarrow(tmp_path: Path, monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    dataset = EpisodeDataset(tmp_path / "dataset")
    dataset.add_frame(episode_index=1, frame_index=0, timestamp=0.0, state={"x": 1}, action={"y": 2})
    root = dataset.save()

    rows = [json.loads(line) for line in (root / "data" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (root / "data" / "episodes.parquet").exists() is False
    assert rows[0]["episode_index"] == 1
    assert rows[0]["state"] == json.dumps({"x": 1})
