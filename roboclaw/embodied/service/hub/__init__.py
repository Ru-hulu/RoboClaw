"""HubService — upload/download datasets and policies to/from HuggingFace Hub."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from roboclaw.embodied.board.channels import CH_HUB
from roboclaw.embodied.command.helpers import dataset_path, policy_path
from roboclaw.embodied.service.hub.progress import make_tqdm_class
from roboclaw.embodied.service.hub.transfer import pull_repo, push_folder

if TYPE_CHECKING:
    from roboclaw.embodied.embodiment.manifest import Manifest
    from roboclaw.embodied.service import EmbodiedService


class HubService:
    """Upload/download datasets and policies to/from HuggingFace Hub.

    NOT a Session subclass — pure Python API via huggingface_hub,
    no subprocess, no hardware interaction.
    """

    def __init__(self, parent: EmbodiedService) -> None:
        self._parent = parent

    # ── Datasets ─────────────────────────────────────────────────────

    async def push_dataset(
        self, manifest: Manifest, kwargs: dict[str, Any], tty_handoff: Any,
    ) -> str:
        repo_id = kwargs["repo_id"]
        name = kwargs["name"]
        token = kwargs.get("token", "")
        private = kwargs.get("private", False)

        local = dataset_path(manifest, name)
        if not local.is_dir():
            raise ValueError(f"Dataset '{name}' not found")

        url = await asyncio.to_thread(
            push_folder,
            local_path=local,
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            private=private,
            ignore_patterns=["images/"],
        )
        return f"Dataset '{name}' pushed to {repo_id}\n{url}"

    async def pull_dataset(
        self, manifest: Manifest, kwargs: dict[str, Any], tty_handoff: Any,
    ) -> str:
        repo_id = kwargs["repo_id"]
        name = kwargs.get("name", "") or repo_id.rsplit("/", 1)[-1]
        token = kwargs.get("token", "")

        local = dataset_path(manifest, name)
        tqdm_cls = make_tqdm_class(self._parent.board, f"pull_dataset:{name}")

        await asyncio.to_thread(
            pull_repo,
            repo_id=repo_id,
            repo_type="dataset",
            local_dir=local,
            token=token,
            tqdm_class=tqdm_cls,
        )
        self._emit_done(f"pull_dataset:{name}")
        return f"Dataset '{name}' downloaded from {repo_id}"

    # ── Policies ─────────────────────────────────────────────────────

    async def push_policy(
        self, manifest: Manifest, kwargs: dict[str, Any], tty_handoff: Any,
    ) -> str:
        repo_id = kwargs["repo_id"]
        name = kwargs["name"]
        token = kwargs.get("token", "")
        private = kwargs.get("private", False)

        local = policy_path(manifest, name)
        if not local.is_dir():
            raise ValueError(f"Policy '{name}' not found")

        url = await asyncio.to_thread(
            push_folder,
            local_path=local,
            repo_id=repo_id,
            repo_type="model",
            token=token,
            private=private,
        )
        return f"Policy '{name}' pushed to {repo_id}\n{url}"

    async def pull_policy(
        self, manifest: Manifest, kwargs: dict[str, Any], tty_handoff: Any,
    ) -> str:
        repo_id = kwargs["repo_id"]
        name = kwargs.get("name", "") or repo_id.rsplit("/", 1)[-1]
        token = kwargs.get("token", "")

        local = policy_path(manifest, name)
        tqdm_cls = make_tqdm_class(self._parent.board, f"pull_policy:{name}")

        await asyncio.to_thread(
            pull_repo,
            repo_id=repo_id,
            repo_type="model",
            local_dir=local,
            token=token,
            tqdm_class=tqdm_cls,
        )
        self._emit_done(f"pull_policy:{name}")
        return f"Policy '{name}' downloaded from {repo_id}"

    # ── Helpers ──────────────────────────────────────────────────────

    def _emit_done(self, operation: str) -> None:
        self._parent.board.emit_sync(CH_HUB, {
            "operation": operation,
            "progress_percent": 100.0,
            "done": True,
        })
