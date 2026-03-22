"""Structured on-disk dataset format for recorded episodes."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    fps: float
    num_episodes: int
    num_frames: int
    features: dict[str, str]
    image_keys: tuple[str, ...]


class EpisodeDataset:
    """Manages a structured episode dataset on disk."""

    def __init__(self, root: Path):
        self.root = root
        self._frames: list[dict[str, Any]] = []
        self._info: DatasetInfo | None = None
        self._current_episode: int | None = None

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def meta_dir(self) -> Path:
        return self.root / "meta"

    def begin_episode(self, episode_index: int) -> None:
        self._current_episode = episode_index

    def add_frame(
        self,
        *,
        episode_index: int,
        frame_index: int,
        timestamp: float,
        state: dict[str, Any],
        action: dict[str, Any],
        images: dict[str, bytes | Path] | None = None,
    ) -> None:
        row = {
            "episode_index": episode_index,
            "frame_index": frame_index,
            "timestamp": timestamp,
            "state": json.dumps(state),
            "action": json.dumps(action),
        }
        for camera_key, img_data in (images or {}).items():
            rel_path = Path("images") / camera_key / f"{episode_index:06d}" / f"{frame_index:06d}.png"
            img_path = self.root / rel_path
            img_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(img_data, (bytes, bytearray)):
                img_path.write_bytes(bytes(img_data))
            elif isinstance(img_data, Path) and img_data.is_file():
                shutil.copyfile(img_data, img_path)
            else:
                continue
            row[camera_key] = str(rel_path)
        self._frames.append(row)

    def save(self, *, fps: float = 30.0, name: str = "dataset") -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        data_path = self.data_dir / "episodes.parquet"
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist(self._frames) if self._frames else pa.table({})
            pq.write_table(table, data_path)
        except ImportError:
            data_path = self.data_dir / "episodes.jsonl"
            with data_path.open("w", encoding="utf-8") as handle:
                for row in self._frames:
                    handle.write(json.dumps(row) + "\n")
        image_keys = tuple(sorted(p.name for p in self.images_dir.iterdir() if p.is_dir())) if self.images_dir.exists() else ()
        info = DatasetInfo(
            name=name,
            fps=fps,
            num_episodes=len({row["episode_index"] for row in self._frames}),
            num_frames=len(self._frames),
            features={"timestamp": "float", "state": "dict", "action": "dict", **{key: "image" for key in image_keys}},
            image_keys=image_keys,
        )
        (self.meta_dir / "info.json").write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")
        self._info = info
        return self.root

    @classmethod
    def load_info(cls, root: Path) -> DatasetInfo:
        data = json.loads((root / "meta" / "info.json").read_text(encoding="utf-8"))
        data["image_keys"] = tuple(data.get("image_keys") or ())
        return DatasetInfo(**data)
