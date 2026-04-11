"""Low-level HuggingFace Hub upload / download wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, snapshot_download
from loguru import logger


def _token(raw: str) -> str | None:
    """Convert empty/whitespace token to None (triggers HF's built-in resolution)."""
    return raw.strip() or None


def push_folder(
    local_path: Path,
    repo_id: str,
    repo_type: str,
    token: str = "",
    private: bool = False,
    ignore_patterns: list[str] | None = None,
) -> str:
    """Upload a local folder to HuggingFace Hub.

    Returns the commit URL.
    """
    api = HfApi(token=_token(token))

    api.create_repo(
        repo_id=repo_id,
        repo_type=repo_type,
        private=private,
        exist_ok=True,
    )

    logger.info("Pushing {} → {} (type={})", local_path, repo_id, repo_type)
    commit = api.upload_folder(
        repo_id=repo_id,
        folder_path=str(local_path),
        repo_type=repo_type,
        ignore_patterns=ignore_patterns or [],
    )
    logger.info("Push complete: {}", commit.commit_url)
    return commit.commit_url


def pull_repo(
    repo_id: str,
    repo_type: str,
    local_dir: Path,
    token: str = "",
    tqdm_class: Any = None,
) -> Path:
    """Download a repo from HuggingFace Hub to *local_dir*.

    Returns the local directory path.
    """
    local_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Pulling {} (type={}) → {}", repo_id, repo_type, local_dir)
    kwargs: dict[str, Any] = {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "local_dir": str(local_dir),
        "token": _token(token),
    }
    if tqdm_class is not None:
        kwargs["tqdm_class"] = tqdm_class

    result = snapshot_download(**kwargs)
    logger.info("Pull complete: {}", result)
    return Path(result)
