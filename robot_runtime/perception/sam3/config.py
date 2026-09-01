"""Environment-backed configuration for the isolated SAM3 worker."""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import Sam3ErrorCode, Sam3RuntimeError


PINNED_SOURCE_REVISION = "6dbb02bd38288df755dfa1378000a861e65b84f6"
EXPECTED_CHECKPOINT_SIZE = 3_450_062_241
EXPECTED_CHECKPOINT_SHA256 = (
    "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
)


@dataclass(frozen=True)
class Sam3RuntimeConfig:
    """Resolved configuration shared by the SAM3 engine and worker."""

    source_path: Path
    checkpoint_path: Path
    output_root: Path
    input_roots: tuple[Path, ...]
    python_executable: str
    device: str = "cuda"
    request_timeout_sec: float = 120.0
    source_revision: str = PINNED_SOURCE_REVISION
    checkpoint_sha256: str = EXPECTED_CHECKPOINT_SHA256

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> Sam3RuntimeConfig:
        """Load configuration without leaking the surrounding environment."""

        values = os.environ if env is None else env
        root = (
            repository_root
            if repository_root is not None
            else Path(__file__).resolve().parents[3]
        ).resolve()

        source_value = values.get("ROBOCLAW_SAM3_SOURCE", "").strip()
        if not source_value:
            raise _configuration_error("SAM3 source directory is not configured.")
        source_path = _resolve_path(source_value, root)
        if not source_path.is_dir():
            raise _configuration_error(
                f"SAM3 source directory does not exist: {source_path}"
            )

        checkpoint_value = values.get("ROBOCLAW_SAM3_CHECKPOINT", "").strip()
        if not checkpoint_value:
            raise _configuration_error("SAM3 checkpoint is not configured.")
        checkpoint_path = _resolve_path(checkpoint_value, root)
        if not checkpoint_path.is_file():
            raise _configuration_error(
                f"SAM3 checkpoint does not exist: {checkpoint_path}"
            )

        roots_value = values.get("ROBOCLAW_SAM3_INPUT_ROOTS", "").strip()
        if roots_value:
            input_roots = tuple(
                _resolve_path(item, root)
                for item in roots_value.split(os.pathsep)
                if item.strip()
            )
            if not input_roots:
                raise _configuration_error(
                    "ROBOCLAW_SAM3_INPUT_ROOTS contains no usable paths."
                )
        else:
            input_roots = (root,)

        output_value = values.get("ROBOCLAW_SAM3_OUTPUT_ROOT", "").strip()
        output_root = _resolve_path(
            output_value or str(root / "runtime_data" / "sam3"),
            root,
        )

        device = values.get("ROBOCLAW_SAM3_DEVICE", "cuda").strip().lower()
        if device not in {"cuda", "cpu"}:
            raise _configuration_error("ROBOCLAW_SAM3_DEVICE must be cuda or cpu.")

        request_timeout = _positive_float(
            values.get("ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC", "120"),
            "ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC",
        )
        python_executable = values.get(
            "ROBOCLAW_SAM3_PYTHON", sys.executable
        ).strip()
        if not python_executable:
            raise _configuration_error("ROBOCLAW_SAM3_PYTHON cannot be blank.")

        checkpoint_sha256 = values.get(
            "ROBOCLAW_SAM3_CHECKPOINT_SHA256",
            EXPECTED_CHECKPOINT_SHA256,
        ).strip().lower()
        if len(checkpoint_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in checkpoint_sha256
        ):
            raise _configuration_error(
                "ROBOCLAW_SAM3_CHECKPOINT_SHA256 must contain 64 hexadecimal characters."
            )

        return cls(
            source_path=source_path,
            checkpoint_path=checkpoint_path,
            output_root=output_root,
            input_roots=input_roots,
            python_executable=python_executable,
            device=device,
            request_timeout_sec=request_timeout,
            checkpoint_sha256=checkpoint_sha256,
        )


def _resolve_path(value: str, repository_root: Path) -> Path:
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = repository_root / path
    return path.resolve()


def _positive_float(value: str, variable: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise _configuration_error(f"{variable} must be a finite number.") from error
    if not math.isfinite(parsed):
        raise _configuration_error(f"{variable} must be a finite number.")
    if parsed <= 0:
        raise _configuration_error(f"{variable} must be greater than zero.")
    return parsed


def _configuration_error(message: str) -> Sam3RuntimeError:
    return Sam3RuntimeError(Sam3ErrorCode.MODEL_UNAVAILABLE, message)
